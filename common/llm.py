"""LLM 客户端封装。

基于 OpenAI 兼容 API（Function Calling），支持任意兼容服务
（Kimi/Moonshot、DeepSeek、OpenAI 等），通过环境变量配置。
内置重试机制与错误处理。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # 允许在未安装 openai 时导入模块（例如仅运行工具测试）
    OpenAI = None  # type: ignore[assignment]


@dataclass
class ToolCall:
    """一次工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 单次响应的统一表示。"""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMError(Exception):
    """LLM 调用失败（重试后仍失败）。"""


class LLMClient:
    """OpenAI 兼容 API 客户端，带指数退避重试。

    环境变量：
        OPENAI_API_KEY  / MOONSHOT_API_KEY：API 密钥（必填）
        OPENAI_BASE_URL：API 地址，默认 https://api.moonshot.cn/v1
        MODEL_NAME      ：模型名，默认 kimi-k2-0905-preview
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        if OpenAI is None:
            raise LLMError("未安装 openai 包，请先执行 pip install -r requirements.txt")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        if not self.api_key:
            raise LLMError("未找到 API Key，请设置环境变量 OPENAI_API_KEY 或 MOONSHOT_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1")
        self.model = model or os.getenv("MODEL_NAME", "kimi-k2-0905-preview")
        self.max_retries = max_retries
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """发起一轮对话，支持工具调用，失败时按指数退避重试。"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return self._parse_response(resp)
            except Exception as exc:  # noqa: BLE001 - 统一封装为 LLMError
                last_error = exc
                if not self._retryable(exc) or attempt == self.max_retries - 1:
                    break
                time.sleep(2**attempt)  # 1s, 2s, 4s 指数退避
        raise LLMError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_error}") from last_error

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        """鉴权/参数类错误不重试，限流/超时/服务端错误重试。"""
        status = getattr(exc, "status_code", None)
        if status is None:  # 网络错误等，允许重试
            return True
        return status in (408, 409, 429) or status >= 500

    @staticmethod
    def _parse_response(resp: Any) -> LLMResponse:
        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResponse(content=msg.content, tool_calls=calls)
