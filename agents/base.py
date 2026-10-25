"""Agent 基类：统一封装 LLM 调用与消息发送。"""

from __future__ import annotations

import re
from typing import Any, Protocol

from common.llm import LLMResponse
from workflow.state import WorkflowState


class ChatModel(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse: ...


def extract_code(text: str) -> str:
    """从 LLM 输出中提取 ```python 代码块；没有代码块时按全文处理。"""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


class BaseAgent:
    """所有 Agent 节点的基类。

    子类实现 `handle(state)`；`run` 负责节点协议、异常包装与消息记录。
    """

    name = "base"

    def __init__(self, llm: ChatModel, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def ask(self, user_content: str) -> str:
        resp = self.llm.chat(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
        return resp.content or ""

    def run(self, state: WorkflowState) -> None:
        try:
            self.handle(state)
        except Exception as exc:  # noqa: BLE001 - 交由引擎统一置 FAILED
            raise RuntimeError(f"[{self.name}] 执行失败: {exc}") from exc

    def handle(self, state: WorkflowState) -> None:
        raise NotImplementedError
