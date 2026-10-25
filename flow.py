"""流程编排：编码 → 审查 →(条件分支)→ 修复 → 回到审查（循环）。

对应作业方向「代码审查流程」：
    编码Agent + 审查Agent + 修复Agent

流程图：
    requirement
        │
        ▼
    ┌────────┐
    │ coder  │  生成代码
    └───┬────┘
        ▼
  ┌─► reviewer ──PASS──► END
  │     │
  │   FAIL 且 round < max_rounds
  │     ▼
  │   fixer ──（循环回边）──┘
  │
  FAIL 且 round 达到上限 ──► END（状态标记为 FAILED）
"""

from __future__ import annotations

from agents.coder import CoderAgent
from agents.fixer import FixerAgent
from agents.reviewer import ReviewerAgent
from workflow.engine import END, Workflow
from workflow.state import WorkflowState


def route_after_review(state: WorkflowState) -> str:
    """条件分支：通过则结束；未通过且未超预算则去修复；超预算则终止。"""
    if state.review_verdict == "PASS":
        return END
    if state.round >= state.max_rounds:
        state.status = "FAILED"
        state.error = f"修复 {state.max_rounds} 轮后仍未通过审查，流程终止"
        return END
    return "fixer"


def build_workflow(llm, max_rounds: int = 3) -> Workflow:
    """装配 Workflow。llm 可以是真实 LLMClient，也可以是测试用的模拟实现。"""
    coder = CoderAgent(llm)
    reviewer = ReviewerAgent(llm)
    fixer = FixerAgent(llm)

    wf = Workflow(name="code-review-pipeline")
    wf.add_node(coder.name, coder.run)
    wf.add_node(reviewer.name, reviewer.run)
    wf.add_node(fixer.name, fixer.run)

    wf.add_edge(coder.name, reviewer.name)                    # 顺序：编码 → 审查
    wf.add_conditional_edge(reviewer.name, route_after_review)  # 条件分支
    wf.add_edge(fixer.name, reviewer.name)                    # 循环：修复 → 复审
    return wf


def run_pipeline(requirement: str, llm, max_rounds: int = 3, log_dir: str | None = None) -> WorkflowState:
    wf = build_workflow(llm, max_rounds=max_rounds)
    state = WorkflowState(requirement=requirement, max_rounds=max_rounds)
    state.send("user", "coder", "requirement", f"提交需求：{requirement[:50]}")
    return wf.run("coder", state, log_dir=log_dir)
