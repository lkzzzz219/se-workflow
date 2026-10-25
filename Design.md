# 设计文档 —— SE Workflow（编码 → 审查 → 修复）

## 1. 项目目标

搭建 3 个 Agent 协作的 Workflow，覆盖作业要求的核心概念：Workflow 编排、Agent 间通信、状态管理、顺序/条件/循环流程控制。选择「代码审查流程」方向，复用 Homework 1 的 LLM 客户端与 AST 静态分析工具。

## 2. 总体架构

```
                ┌─────────────────────────────────────────────┐
                │              WorkflowState（共享状态）        │
                │  requirement / current_code / verdict /     │
                │  round / messages[] / history[]             │
                └───────▲──────────────────────▲──────────────┘
                        │ 读写                  │ 读写
┌──────────┐   ┌────────┴─────┐   ┌───────────┴───┐   ┌───────┴──────┐
│  用户需求  │─►│  CoderAgent  │─►│ ReviewerAgent │─►│  FixerAgent  │
└──────────┘   │ （生成代码）  │   │ （工具+LLM判定）│   │ （按报告修复） │
               └──────────────┘   └───────┬───────┘   └──────┬───────┘
                                          │ PASS → 结束        │
                                          ▼ FAIL               │
                                        条件分支 ◄─────────────┘
                                          （轮次上限兜底）  循环回边
```

三层职责：

| 层 | 模块 | 职责 |
|----|------|------|
| 编排层 | `workflow/engine.py` + `flow.py` | 节点注册、边定义、路由、步数保护、日志落盘 |
| 状态层 | `workflow/state.py` | 共享数据、消息列表、执行轨迹 |
| 节点层 | `agents/` | 三个 Agent 各自的 LLM 调用与工具使用 |

## 3. Workflow 引擎设计

引擎只有三个编排原语，但足以表达本流程及更复杂的扩展：

```python
wf.add_node("coder", coder.run)                        # 注册节点
wf.add_edge("coder", "reviewer")                       # 固定顺序边
wf.add_conditional_edge("reviewer", route_after_review) # 条件分支
wf.add_edge("fixer", "reviewer")                       # 循环回边
```

- **节点协议**：`fn(state) -> None`，节点只读写共享状态，不感知彼此——新增 Agent 不需要改动已有节点，对应评审的"可扩展性"。
- **路由优先级**：条件边 > 固定边 > 无出边即结束。
- **安全兜底**：`max_steps`（默认 20）防止任何意外的无限循环；`route_after_review` 中的 `max_rounds`（默认 3）防止修复无效时死循环，超限明确标记 FAILED 而非静默退出。
- **错误处理**：节点异常包装为带节点名的 RuntimeError，引擎统一捕获后置 `status=FAILED`，保留完整 history 与 messages 现场，日志照常落盘——失败可解释、可复盘。

## 4. Agent 间通信与状态管理

采用**共享状态 + 显式消息**的双通道设计：

- **数据走共享状态**：代码、审查结论、轮次等大内容存 `WorkflowState` 字段，避免消息里反复拷贝大文本。
- **事件走消息列表**：每个 Agent 完成工作后 `state.send(sender, receiver, kind, summary)`，形成可追溯的通信链（user→coder→reviewer→fixer→reviewer→user），CLI 与日志中完整展示。
- **执行轨迹**：引擎为每个节点记录 `NodeRecord`（节点名、轮次、开始/结束时间、耗时、摘要），对应"执行日志与状态追踪"的推荐项；运行结束自动写入 `runs/run-<时间戳>.json`。

## 5. 三个 Agent 的分工与 Prompt 设计

| Agent | 输入 | 输出 | 关键设计 |
|-------|------|------|---------|
| CoderAgent | 需求 | 代码 | Prompt 强制只输出代码块、禁止 eval/硬编码密钥 |
| ReviewerAgent | 代码 + **工具客观事实** | VERDICT + 报告 | 先调 `syntax_check` / `analyze_code` 拿到带行号的检出结果，LLM 只做综合判定；**确定性兜底**：语法错误或存在高危问题时强制 FAIL，不依赖模型自觉 |
| FixerAgent | 代码 + 审查报告 | 修复后的完整代码 | 要求不改变对外功能与签名；修复输出为空时保留原代码，避免流程崩溃 |

Reviewer 的"工具给出事实、LLM 负责判断"模式复用自 HW1：静态分析保证行号可追溯、不编造；LLM 负责把事实组织成可读的判定与建议。

## 6. 流程控制覆盖情况（对照技术要求）

| 要求 | 实现 |
|------|------|
| 顺序执行（必须） | coder → reviewer 固定边 |
| Agent 间消息传递/状态共享（必须） | messages 列表 + WorkflowState 双通道 |
| 条件分支（推荐） | reviewer 后按 verdict 分流：PASS→END / FAIL→fixer / 超轮次→END(FAILED) |
| 循环（推荐） | fixer → reviewer 回边，轮次计数 + 上限 |
| 执行日志与状态追踪（推荐） | NodeRecord 轨迹 + JSON 日志落盘 |
| 错误处理与恢复（推荐） | 节点异常→FAILED 保留现场；引擎 max_steps 兜底 |
| 从项目 1 复用（推荐） | `common/` 直接复用 HW1 的 LLM 客户端、AST 分析、文件操作 |

## 7. 测试策略

`tests/test_pipeline.py` 用按角色分发的模拟 LLM（coder 产出带缺陷代码、reviewer 按是否含 eval 判定、fixer 产出干净代码）验证 5 条端到端断言：

1. **完整闭环收敛**：节点序列 coder→reviewer→fixer→reviewer，两轮审查后 DONE/PASS，最终代码无 eval；
2. **循环终止**：修复持续无效时 max_rounds=2 处终止为 FAILED，错误信息明确；
3. **状态共享**：需求、报告、最终代码均由对应 Agent 写入共享状态并被下游读取；
4. **引擎保护**：路由到不存在节点时 FAILED 而非崩溃；
5. **日志落盘**：JSON 日志包含完整 history 与 messages。

测试不需要真实 API Key，CI 可直接运行。

## 8. 评审标准对照

| 维度 | 对应实现 |
|------|---------|
| 流程完整性（40%） | 需求→代码→审查→修复→复审→交付 端到端跑通；CLI 一条命令启动；日志/轨迹可复盘 |
| Agent 协作（30%） | 消息链 + 共享状态双通道；Reviewer 的工具事实作为 Agent 间的可信交接物；轮次与结论在状态中显式流转 |
| 可扩展性（20%） | 节点/边/路由三原语，新增 Agent 只需实现 `handle(state)` 并注册；引擎与具体 Agent 完全解耦 |
| 文档（10%） | README（安装/使用/示例）+ 本文档（架构图、通信机制、流程控制对照、测试策略） |

## 9. 已知限制与扩展方向

- 目前是线性单分支流程，未实现并行节点（原语层面已支持：路由函数返回多个下游后再 join，可作为 HW3 扩展）；
- Reviewer 的 LLM 判定只取首行 VERDICT，模型不遵守格式时由确定性规则兜底，但报告质量仍依赖模型遵守程度；
- 可增加可视化编排界面（把 flow.py 的节点/边定义渲染成图），对应作业的可选加分项。
