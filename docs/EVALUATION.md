# Evaluation

Council Benchmark v1 用固定的 12 个案例比较五种策略：单模型直接回答、单模型加强直接回答、两次调用的自我修正、同模型四角色审议、跨模型四席审议。案例覆盖决策、事实核查、风险与规划，并保存参考检查点和禁止编造的主张。

## 能证明什么

- Mock 运行只证明工作流、输出文件和计分代码可重复，不代表任何真实模型的质量。
- 每个案例与策略默认重复 3 次，并按每个案例确定性打乱执行顺序，降低单次采样和固定顺序偏差。
- 执行结果会记录完成率、失败率、模型调用、Token、耗时、均值/中位数/P95/95% 置信区间和可选的估算成本。
- 盲评除五项 1–5 分外，可逐答案填写引用支持数/引用总数与未经支持主张数量。
- 质量结论必须来自真实 Provider 输出和人工盲评；程序不会根据模型自述生成“准确率”。
- 评测结果不等于外部事实认证，案例和评分仍需要独立复核。

应用内 `/evaluations` 页面在没有有效结果时只显示 `—`，不会展示硬编码成绩。命令行评测输出保存在 `evals/results/`，该目录默认不提交个人运行结果。

## 运行 Mock 回归

```bash
backend/.venv/bin/python evals/run_benchmark.py --provider-id mock
```

这会生成：

- `benchmark-*.json`：执行数据和未打分答案；
- `benchmark-*-blind.md`：隐藏方案名称的盲评材料；
- `benchmark-*-reviews.json`：待填写的五项评分模板；
- `benchmark-*-key.json`：盲评标签与策略映射，评分前不要打开。

Mock 没有真实的跨模型差异；跨模型策略会复用 Mock 五席，仅验证编排、重复、匿名和计分链路，且结果始终禁止形成质量结论。

## 运行真实 Provider

先在 Council 中配置并验证 Provider。真实评测可能产生较多费用，命令必须显式添加 `--confirm-cost`：

```bash
backend/.venv/bin/python evals/run_benchmark.py \
  --provider-id deepseek \
  --model deepseek-chat \
  --confirm-cost
```

跨模型策略读取“设置 → 角色分配”中已保存的五席配置，并要求至少两个不同的 Provider/model 组合。可以用 `--case CASE_ID` 限定案例，用 `--strategies direct,self_refine,same_model_council` 限定策略，或用 `--repetitions 1..10` 调整重复次数。费用确认前显示的最大调用数已经包含重复次数；五种策略每轮每题 14 次，默认 3 轮即每题 42 次、全量共 504 次模型请求。

加强直接回答仍是单次 API 调用，只改用更完整的分析指令；self-refine 使用同一模型先写草稿再独立复核。它们用于区分“提示更充分”“多一次修正”和“四席流程”带来的增益。不同 Provider 不一定遵守相同输出长度，因此这里不声称预先严格等 Token；应根据结果中的实际 Token 做等预算子集或回归比较，并同时披露调用次数与延迟。

## 完成人工盲评

1. 评审者只阅读 `*-blind.md`，按事实准确、证据使用、关键覆盖、可执行性和不确定性处理各给 1–5 分。
2. 在 `*-reviews.json` 中为每个匿名答案填写五项分数、引用支持数/引用总数和未经支持主张数量，并为每个案例选择一个偏好答案；没有引用时填写 `0 / 0`，不要留空冒充已检查。
3. 生成摘要：

```bash
backend/.venv/bin/python evals/score_results.py \
  evals/results/benchmark-*.json \
  evals/results/benchmark-*-reviews.json
```

摘要只有在真实 Provider 完成且盲评分有效时才允许形成质量比较。公开结果时应同时给出数据集版本、Provider/model、运行日期、失败率、Token、延迟、评分人数和原始匿名结果。

“有效”要求本次比较涉及的所有 Provider 都不是 Mock，五种策略按声明重复次数生成每个答案，并且全部案例的五项分数、引用检查、未经支持主张计数和偏好都已填写。只跑部分策略、调用失败或只评一部分案例仍可保存阶段性结果，但 `quality_claims_allowed` 会保持 `false`。当前 95% 区间使用独立样本的正态近似；样本很少或重复来自同一时段时只能作为波动提示，不能替代多评审者、跨日期复现实验或配对统计检验。

## 可选成本估算

项目不内置容易过期的模型价格。需要估算时自行建立 JSON，例如：

```json
{
  "deepseek:deepseek-chat": {
    "input_per_million": 1.0,
    "output_per_million": 2.0
  },
  "zhipu": {
    "input_per_million": 2.0,
    "output_per_million": 5.0
  }
}
```

键可写成精确的 `provider_id:model`，也可只写 `provider_id` 作为该 Provider 的统一价格。运行时添加 `--pricing ./pricing.json`。只要某个实际使用的模型没有价格，该策略的估算成本就显示为不可用，不用部分价格冒充总成本。
