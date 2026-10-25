"""共享状态：Agent 间通信与状态管理的核心。

所有 Agent 节点读写同一个 WorkflowState 实例：
- 数据字段（requirement / current_code / review_verdict ...）承担"状态共享"；
- messages 列表承担显式"消息传递"，记录每个 Agent 发给下游的内容；
- history 列表承担执行日志与状态追踪。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Message:
    sender: str
    receiver: str
    kind: str          # requirement / code / verdict / fix
    summary: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class NodeRecord:
    node: str
    round: int
    summary: str
    started_at: float
    finished_at: float

    @property
    def duration(self) -> float:
        return round(self.finished_at - self.started_at, 2)


@dataclass
class WorkflowState:
    """贯穿整个 Workflow 的共享状态。"""

    requirement: str = ""
    current_code: str = ""
    review_verdict: str = ""        # PASS / FAIL
    review_report: str = ""
    issue_count: int = 0
    high_severity_count: int = 0
    round: int = 0                  # 审查-修复循环轮次
    max_rounds: int = 3
    status: str = "PENDING"         # PENDING / RUNNING / DONE / FAILED
    error: str = ""
    messages: list[Message] = field(default_factory=list)
    history: list[NodeRecord] = field(default_factory=list)

    def send(self, sender: str, receiver: str, kind: str, summary: str) -> None:
        """Agent 间显式消息传递。"""
        self.messages.append(Message(sender=sender, receiver=receiver, kind=kind, summary=summary))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
