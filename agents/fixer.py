"""修复 Agent：依据审查报告修复代码。"""

from __future__ import annotations

from workflow.state import WorkflowState

from .base import BaseAgent, extract_code
from .prompts import FIXER_PROMPT


class FixerAgent(BaseAgent):
    name = "fixer"

    def __init__(self, llm):
        super().__init__(llm, FIXER_PROMPT)

    def handle(self, state: WorkflowState) -> None:
        raw = self.ask(
            f"## 当前代码\n```python\n{state.current_code}\n```\n\n"
            f"## 审查报告（第 {state.round} 轮）\n{state.review_report}\n\n"
            "请输出修复后的完整代码。"
        )
        fixed = extract_code(raw)
        if fixed:  # 修复输出为空时保留原代码，避免流程崩溃
            state.current_code = fixed
        state.send(self.name, "reviewer", "fix",
                   f"已按第 {state.round} 轮审查报告完成修复，提交复审")
