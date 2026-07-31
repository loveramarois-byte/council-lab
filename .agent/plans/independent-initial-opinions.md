# Milestone 1 — 独立初答模式

## 当前行为与差距

现有 LangGraph 状态机按席位顺序调用，`build_context_window()` 将已保存的公开 Turn 传给后续席位；因此后席会读取前席输出。用户插话也会写入同一 Turn 列表。项目已有持久 Run JSON、SQLite 迁移、checkpoint、幂等创建、恢复和最终人工确认点，但没有可选的独立初答策略。

## 目标与兼容边界

- 新 Run 可选择 `sequential`（默认、旧行为）或 `independent`。
- independent 每个初答席只读取冻结问题、资料快照、项目上下文和明确选择的记忆，不读取其他席位 Turn 或独立轮插话。
- API 顺序执行即可，不引入并发调度；完成后最终总结读取完整公开记录。
- 旧 Run 缺少新字段时按 sequential 解析；不改写已完成 Run、Turn、审批或审计 payload。
- 不改变高风险审批、事实门禁、外部副作用、调用上限和恢复语义。

## 实施步骤

1. `RunCreate`/`RunRecord` 增加受校验的策略字段，`DiscussionTurn.stage` 标记初答、讨论和用户输入；schema v11 仅推进版本，依靠 Pydantic 默认兼容旧 payload。
2. `_generate_turn` 在 independent 下使用空公开 Turn 上下文，并使用明确禁止读取其他席位的提示；插话仍持久化但不会进入剩余初答上下文。
3. 前端创建请求携带策略，Run 页面/导出显示策略；Benchmark 可将策略作为实验维度。
4. 补充默认兼容、非法输入、上下文隔离、插话、恢复、幂等冲突、高风险控制和迁移失败恢复测试。

## 状态图

```text
queued -> running -> initial_opinion(席位 1..N) -> awaiting_final_input -> summary -> completed
                         independent: 每次只读冻结基础输入
                         sequential:  每次读取公开 Turn
```

## 风险与回滚

新增字段可被旧客户端省略；服务端默认 sequential。回滚代码时 schema v11 仍只包含空迁移，旧程序可安全读取既有 payload。任何上下文隔离失败都应阻止发布；不把独立模式宣称为质量提升。
