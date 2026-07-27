# Evaluation

Council Benchmark v1 用固定的 12 个案例比较三种策略：单模型直接回答、同模型四角色审议、跨模型四席审议。案例覆盖决策、事实核查、风险与规划，并保存参考检查点和禁止编造的主张。

## 能证明什么

- Mock 运行只证明工作流、输出文件和计分代码可重复，不代表任何真实模型的质量。
- 执行结果会记录完成率、失败率、模型调用、Token 和耗时。
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

## 运行真实 Provider

先在 Council 中配置并验证 Provider。真实评测可能产生较多费用，命令必须显式添加 `--confirm-cost`：

```bash
backend/.venv/bin/python evals/run_benchmark.py \
  --provider-id deepseek \
  --model deepseek-chat \
  --confirm-cost
```

跨模型策略读取“设置 → 角色分配”中已保存的五席配置，并要求至少两个不同的 Provider/model 组合。可以用 `--case CASE_ID` 限定案例，或用 `--strategies direct,same_model_council` 限定策略。

## 完成人工盲评

1. 评审者只阅读 `*-blind.md`，按事实准确、证据使用、关键覆盖、可执行性和不确定性处理各给 1–5 分。
2. 将分数、偏好和备注填入 `*-reviews.json`。
3. 生成摘要：

```bash
backend/.venv/bin/python evals/score_results.py \
  evals/results/benchmark-*.json \
  evals/results/benchmark-*-reviews.json
```

摘要只有在真实 Provider 完成且盲评分有效时才允许形成质量比较。公开结果时应同时给出数据集版本、Provider/model、运行日期、失败率、Token、延迟、评分人数和原始匿名结果。
