# fragment_001 amide 修复前后匹配统计对比

- 核心词表：`fragments_core_v1/core_fragment_v1.json`
- 统计文件：`data/processed/core_fragment_v1_resolved_stats.csv`
- 口径：当前 resolved 先做 dedup，再按 `instance_suppression` 删除被 imide/urethane/urea 覆盖的 amide 实例。

## 统计对比

| 口径 | period_hits | source_hits | match_total | max_per_period |
|---|---:|---:|---:|---:|
| 原始 SMARTS | 27559 | 3934 | 124626 | 18 |
| constraints + dedup | 27559 | 3934 | 79308 | 10 |
| resolved overlap 过滤 | 16600 | 2396 | 30312 | 8 |

## 结论

- `amide` 保持核心片段，但优先级低于 `imide`、`urethane`、`urea`。
- 过滤发生在 match instance 级别，不再使用 molecule 级全局排除，因此同一 period 内的独立 amide 会被保留。
- 当前 resolved 统计使用通用 dedup normalization。
