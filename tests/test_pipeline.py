"""端到端流程测试：用模拟 LLM 验证 编码→审查→修复→复审 完整闭环。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.llm import LLMResponse
from flow import run_pipeline
from workflow.engine import END, Workflow, WorkflowError
from workflow.state import WorkflowState

BUGGY_CODE = '''def compute(data=[]):
    """计算"""
    result = eval(data[0])
    return result
'''

CLEAN_CODE = '''def compute(values):
    """计算首元素对应数值。

    Args:
        values: 数值列表。

    Returns:
        列表首元素。

    Raises:
        ValueError: 列表为空。
    """
    if not values:
        raise ValueError("values 不能为空")
    return values[0]
'''


class FakeLLM:
    """按 system prompt 区分角色的模拟 LLM。

    - coder：第一轮返回带高危缺陷的代码（eval + 可变默认参数）
    - reviewer：检查代码中是否含 eval，有则 FAIL 无则 PASS（与真实工具结论一致）
    - fixer：返回修复后的干净代码
    """

    def __init__(self, always_buggy_fix: bool = False):
        self.always_buggy_fix = always_buggy_fix
        self.calls = {"coder": 0, "reviewer": 0, "fixer": 0}

    def chat(self, messages, tools=None):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "编码节点" in system:
            self.calls["coder"] += 1
            return LLMResponse(content=f"```python\n{BUGGY_CODE}\n```")
        if "审查节点" in system:
            self.calls["reviewer"] += 1
            if "eval(" in user:
                return LLMResponse(content="VERDICT: FAIL\n发现 eval 注入风险与可变默认参数，必须修复。")
            return LLMResponse(content="VERDICT: PASS\n代码无高危问题，通过。")
        if "修复节点" in system:
            self.calls["fixer"] += 1
            code = BUGGY_CODE if self.always_buggy_fix else CLEAN_CODE
            return LLMResponse(content=f"```python\n{code}\n```")
        raise AssertionError("未知角色")


def test_full_pipeline_converges():
    """完整闭环：编码 → 审查FAIL → 修复 → 复审PASS → DONE。"""
    state = run_pipeline("写一个计算函数", FakeLLM(), max_rounds=3)
    assert state.status == "DONE"
    assert state.review_verdict == "PASS"
    assert state.round == 2                       # 两轮审查
    assert "eval" not in state.current_code       # 最终代码已修复
    # 节点顺序：coder → reviewer → fixer → reviewer
    assert [r.node for r in state.history] == ["coder", "reviewer", "fixer", "reviewer"]
    # Agent 间消息传递链完整
    pairs = [(m.sender, m.receiver) for m in state.messages]
    assert pairs == [("user", "coder"), ("coder", "reviewer"),
                     ("reviewer", "fixer"), ("fixer", "reviewer"),
                     ("reviewer", "user")]


def test_max_rounds_terminates_as_failed():
    """修复无效时，循环在 max_rounds 处终止而不是死循环。"""
    state = run_pipeline("写一个计算函数", FakeLLM(always_buggy_fix=True), max_rounds=2)
    assert state.status == "FAILED"
    assert state.round == 2
    assert "未通过审查" in state.error


def test_state_sharing_across_agents():
    """下游 Agent 能读到上游写入共享状态的内容。"""
    state = run_pipeline("需求X", FakeLLM())
    assert state.requirement == "需求X"           # user 写入
    assert state.review_report                    # reviewer 写入
    assert state.current_code == CLEAN_CODE.strip()  # fixer 写入并被最终保留


def test_engine_guards():
    """引擎级保护：路由到不存在节点 / 超步数。"""
    wf = Workflow("t", max_steps=5)
    wf.add_node("a", lambda s: None)
    wf.add_edge("a", "ghost")
    state = wf.run("a", WorkflowState())
    assert state.status == "FAILED" and "不存在的节点" in state.error


def test_execution_log_written(tmp_path):
    """执行日志落盘，包含 history 与 messages。"""
    import json
    state = run_pipeline("需求", FakeLLM(), log_dir=str(tmp_path))
    logs = list(tmp_path.glob("run-*.json"))
    assert len(logs) == 1
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["status"] == "DONE"
    assert len(data["history"]) == 4
    assert len(data["messages"]) == 5
