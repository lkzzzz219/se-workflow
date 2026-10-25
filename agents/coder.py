"""编码 Agent：根据需求生成代码。"""

from __future__ import annotations

from workflow.state import WorkflowState

from .base import BaseAgent, extract_code
from .prompts import CODER_PROMPT


class CoderAgent(BaseAgent):
    name = "coder"

    def __init__(self, llm):
        super().__init__(llm, CODER_PROMPT)

    def handle(self, state: WorkflowState) -> None:
        raw = self.ask(f"请根据以下需求编写 Python 代码：\n\n{state.requirement}")
        state.current_code = extract_code(raw)
        state.send(self.name, "reviewer", "code",
                   f"已按需求生成代码（{len(state.current_code.splitlines())} 行）")
