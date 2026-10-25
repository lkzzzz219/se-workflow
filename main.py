#!/usr/bin/env python3
"""SE Workflow —— 命令行入口。

用法：
    python main.py "写一个计算 BMI 的函数"
    python main.py --file examples/requirement.txt
    python main.py "需求..." --max-rounds 2 --output runs
"""

from __future__ import annotations

import argparse
import os
import sys

from common.llm import LLMClient, LLMError
from flow import run_pipeline


def print_summary(state) -> None:
    """打印执行轨迹与最终结果。"""
    print("\n" + "=" * 60)
    print(f"流程状态: {state.status}" + (f"（{state.error}）" if state.error else ""))
    print(f"审查轮次: {state.round}，最终判定: {state.review_verdict or '-'}")
    print("\n--- 执行轨迹 ---")
    for rec in state.history:
        print(f"  [{rec.node:>8}] round {rec.round}  耗时 {rec.duration}s  {rec.summary}")
    print("\n--- Agent 间消息 ---")
    for msg in state.messages:
        print(f"  {msg.sender} -> {msg.receiver} [{msg.kind}] {msg.summary}")
    print("\n--- 最终代码 ---")
    print(state.current_code)
    print("\n--- 最终审查报告 ---")
    print(state.review_report)


def main() -> None:
    parser = argparse.ArgumentParser(description="编码→审查→修复 多 Agent Workflow")
    parser.add_argument("requirement", nargs="?", help="代码需求描述")
    parser.add_argument("--file", help="从文件读取需求")
    parser.add_argument("--max-rounds", type=int, default=3, help="最大修复轮次（默认 3）")
    parser.add_argument("--output", default="runs", help="执行日志输出目录（默认 runs/）")
    args = parser.parse_args()

    requirement = args.requirement
    if args.file:
        if not os.path.isfile(args.file):
            print(f"[错误] 需求文件不存在: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(args.file, encoding="utf-8") as f:
            requirement = f.read().strip()
    if not requirement:
        parser.print_help()
        sys.exit(1)

    try:
        llm = LLMClient()
    except LLMError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)

    state = run_pipeline(requirement, llm, max_rounds=args.max_rounds, log_dir=args.output)
    print_summary(state)
    sys.exit(0 if state.status == "DONE" else 2)


if __name__ == "__main__":
    main()
