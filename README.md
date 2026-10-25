# SE Workflow：编码 → 审查 → 修复 多 Agent 协作工作流

三个 Agent 协作完成"写代码 → 审查 → 修复 → 复审"的完整软件开发小流程。复用 Homework 1（code-review-agent）的 LLM 客户端与 AST 静态分析工具作为工作流节点能力。

## 功能特性

- **3 个 Agent 协作**：编码 Agent、审查 Agent、修复 Agent，各持有独立系统提示词
- **Workflow 编排引擎**：
  - 顺序执行（编码 → 审查）
  - **条件分支**：审查通过则结束，未通过则进入修复
  - **循环**：修复后自动回到审查节点复审，直到通过或达到轮次上限
- **Agent 间通信**：显式消息传递（每条消息记录发送方/接收方/类型）+ 共享状态对象
- **状态管理**：`WorkflowState` 贯穿全程，记录当前代码、审查结论、轮次、执行轨迹
- **错误处理与恢复**：节点异常统一转为 FAILED 状态并保留现场；引擎级保护（路由到不存在节点、超最大步数兜底）；修复轮次预算防止死循环
- **执行日志与状态追踪**：每节点记录耗时，运行结束自动落盘 JSON 日志到 `runs/`
- **可扩展**：新增 Agent = 写一个节点函数 + `add_node` / `add_edge` 两行编排代码

## 安装与配置

```bash
pip install -r requirements.txt

# 配置 LLM（与 HW1 相同，支持任意 OpenAI 兼容服务）
export OPENAI_API_KEY="sk-xxx"
# 可选：
export OPENAI_BASE_URL="https://api.deepseek.com/v1"
export MODEL_NAME="deepseek-chat"
```

## 使用方法

```bash
# 直接给需求
python main.py "写一个计算 BMI 的函数，非法输入抛 ValueError"

# 从文件读需求
python main.py --file examples/requirement.txt

# 调整修复轮次上限与日志目录
python main.py "需求..." --max-rounds 2 --output runs
```

运行时会打印流程推进过程（`[workflow] → coder → reviewer → fixer → reviewer`），结束后输出执行轨迹、Agent 间消息记录、最终代码与审查报告。

## 运行示例

```text
[workflow] → coder (step 1, round 0)
[workflow] → reviewer (step 2, round 0)
[workflow] → fixer (step 3, round 1)
[workflow] → reviewer (step 4, round 1)

============================================================
流程状态: DONE
审查轮次: 2，最终判定: PASS

--- 执行轨迹 ---
  [   coder] round 0  耗时 8.3s  已按需求生成代码（24 行）
  [reviewer] round 1  耗时 6.1s  第 1 轮审查：FAIL（检出 3 项，高危 1 项）
  [   fixer] round 1  耗时 7.4s  已按第 1 轮审查报告完成修复，提交复审
  [reviewer] round 2  耗时 5.2s  第 2 轮审查：PASS（检出 0 项）

--- Agent 间消息 ---
  user -> coder [requirement] 提交需求：写一个计算 BMI 的函数…
  coder -> reviewer [code] 已按需求生成代码（24 行）
  reviewer -> fixer [verdict] 第 1 轮审查：FAIL…
  fixer -> reviewer [fix] 已按第 1 轮审查报告完成修复，提交复审
  reviewer -> user [verdict] 第 2 轮审查：PASS…
```

## 运行测试

```bash
pip install pytest
python -m pytest tests/ -v
```

测试使用模拟 LLM，不需要 API Key，覆盖：完整闭环收敛、循环上限终止、跨 Agent 状态共享、引擎保护、日志落盘。

## 项目结构

```
se-workflow/
├── main.py                # CLI 入口
├── flow.py                # 流程编排（节点 + 边 + 条件路由）
├── workflow/
│   ├── engine.py          # Workflow 引擎（顺序/条件/循环/日志）
│   └── state.py           # 共享状态 + 消息 + 执行轨迹
├── agents/
│   ├── base.py            # Agent 基类（节点协议、代码提取）
│   ├── coder.py           # 编码 Agent
│   ├── reviewer.py        # 审查 Agent（工具事实 + LLM 判定）
│   ├── fixer.py           # 修复 Agent
│   └── prompts.py         # 三个 Agent 的系统提示词
├── common/                # 复用自 HW1：LLM 客户端、AST 静态分析、文件操作
│   ├── llm.py
│   └── tools/
├── examples/requirement.txt
├── tests/test_pipeline.py # 端到端流程测试（模拟 LLM）
└── runs/                  # 执行日志输出目录
```

## 设计文档

架构、状态设计、通信机制与扩展方式详见 [Design.md](Design.md)。
