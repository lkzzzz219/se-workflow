"""Workflow 编排引擎。

支持：
- 顺序执行（固定边）
- 条件分支（路由函数根据共享状态决定下一节点）
- 循环（边指向前序节点，由路由条件和 max_steps 兜底）
- 执行日志与状态追踪（每节点记录耗时，结束落盘 JSON）

节点协议：`fn(state) -> None`，直接读写共享状态。
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

from .state import NodeRecord, WorkflowState

END = "__end__"

NodeFn = Callable[[WorkflowState], None]
RouterFn = Callable[[WorkflowState], str]


class WorkflowError(Exception):
    pass


class Workflow:
    def __init__(self, name: str, max_steps: int = 20) -> None:
        self.name = name
        self.max_steps = max_steps
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}                 # 固定边：node -> next
        self._routers: dict[str, RouterFn] = {}          # 条件边：node -> router(state) -> next

    # ---------- 编排 API ----------
    def add_node(self, name: str, fn: NodeFn) -> None:
        if name == END:
            raise WorkflowError(f"{END} 是保留节点名")
        self._nodes[name] = fn

    def add_edge(self, src: str, dst: str) -> None:
        """固定顺序边。"""
        self._edges[src] = dst

    def add_conditional_edge(self, src: str, router: RouterFn) -> None:
        """条件分支边：router 返回下一节点名或 END。"""
        self._routers[src] = router

    # ---------- 执行 ----------
    def run(self, start: str, state: WorkflowState, log_dir: str | None = None) -> WorkflowState:
        if start not in self._nodes:
            raise WorkflowError(f"起点节点不存在: {start}")
        state.status = "RUNNING"
        current = start
        steps = 0
        try:
            while current != END:
                if current not in self._nodes:
                    raise WorkflowError(f"路由到不存在的节点: {current}")
                steps += 1
                if steps > self.max_steps:
                    raise WorkflowError(f"超过最大步数 {self.max_steps}，流程强制终止")

                fn = self._nodes[current]
                t0 = time.time()
                print(f"\033[35m[workflow] → {current} (step {steps}, round {state.round})\033[0m")
                fn(state)
                state.history.append(
                    NodeRecord(node=current, round=state.round,
                               summary=self._summarize(current, state),
                               started_at=t0, finished_at=time.time())
                )
                current = self._route(current, state)
            if state.status != "FAILED":      # 路由函数可能已判定失败
                state.status = "DONE"
        except Exception as exc:  # noqa: BLE001 - 统一转为 FAILED 状态，保证日志落盘
            state.status = "FAILED"
            state.error = str(exc)
        if log_dir:
            self._dump_log(state, log_dir)
        return state

    def _route(self, current: str, state: WorkflowState) -> str:
        if current in self._routers:           # 条件分支优先
            return self._routers[current](state)
        if current in self._edges:             # 固定顺序
            return self._edges[current]
        return END                              # 无出边即终点

    @staticmethod
    def _summarize(node: str, state: WorkflowState) -> str:
        if state.messages:
            return state.messages[-1].summary
        return f"{node} 完成"

    def _dump_log(self, state: WorkflowState, log_dir: str) -> None:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"run-{time.strftime('%Y%m%d-%H%M%S')}.json")
        data = state.to_dict()
        data["workflow"] = self.name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\033[2m[workflow] 执行日志已保存: {path}\033[0m")
