"""审查 Agent：静态分析工具给出客观事实，LLM 综合判定 PASS / FAIL。"""

from __future__ import annotations

import json

from common.tools.code_analysis import analyze_code, syntax_check
from workflow.state import WorkflowState

from .base import BaseAgent
from .prompts import REVIEWER_PROMPT


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def __init__(self, llm):
        super().__init__(llm, REVIEWER_PROMPT)

    def handle(self, state: WorkflowState) -> None:
        state.round += 1

        # 1. 工具给出可核验的客观事实
        syntax = json.loads(syntax_check(code=state.current_code))
        analysis = json.loads(analyze_code(code=state.current_code))
        issues = analysis.get("issues", [])
        state.issue_count = analysis.get("issue_count", 0)
        state.high_severity_count = sum(1 for i in issues if i["severity"] == "high")

        # 2. LLM 基于事实综合判定
        facts = (
            f"## 待审查代码\n```python\n{state.current_code}\n```\n\n"
            f"## 语法检查\n{json.dumps(syntax, ensure_ascii=False)}\n\n"
            f"## 静态分析检出（共 {state.issue_count} 项，高危 {state.high_severity_count} 项）\n"
            f"{json.dumps(issues, ensure_ascii=False, indent=2)}"
        )
        report = self.ask(facts)
        state.review_report = report

        # 3. 判定：LLM 结论 + 确定性兜底（语法错误或存在高危则不可能 PASS）
        verdict = "PASS" if "VERDICT: PASS" in report.splitlines()[0] else "FAIL"
        if not syntax.get("ok") or state.high_severity_count > 0:
            verdict = "FAIL"
        state.review_verdict = verdict

        receiver = "fixer" if verdict == "FAIL" else "user"
        state.send(self.name, receiver, "verdict",
                   f"第 {state.round} 轮审查：{verdict}（检出 {state.issue_count} 项，高危 {state.high_severity_count} 项）")
