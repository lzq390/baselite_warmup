# base_fragment_new2 第一批核心片段修复报告

- 核心词表：`fragments_1/base_fragment_new2.json`
- 统计文件：`data/processed/base_fragment_new2_resolved_stats.csv`
- 匹配数据：`data/processed/periods2_from_unique_standardized_smiles.csv`
- period 总数：55060
- 唯一 source 总数：10444
- 口径：raw_substruct 是 RDKit 原始 SMARTS 命中；normalized 是执行 constraints 和 dedup 后；resolved 是 active core 再执行 overlap suppression 后。

## 修复范围

原“前 5 项”仍是 001-005；006/007 因为参与 suppress amide/ester，本轮一并收尾。

| fragment_id | 片段 | priority | resolved_period_hits | resolved_match_total | 说明 |
|---|---|---:|---:|---:|---|
| `fragment_001` | `amide` | 40 | 16600 (30.15%) | 30312 | 实例级过滤，排除 imide/urethane/urea 覆盖的 amide-like 局部。 |
| `fragment_002` | `imide` | 70 | 11348 (20.61%) | 21309 | 保留核心，priority=70，dedup 后去掉少量对称重复。 |
| `fragment_003` | `ester` | 50 | 18291 (33.22%) | 34707 | 按 carbonyl anchor 排除 carbonate/urethane 覆盖。 |
| `fragment_004` | `ether` | 30 | 23780 (43.19%) | 48102 | 已收窄为非 carbonyl-adjacent C-O-C。 |
| `fragment_005` | `carbonate` | 70 | 1428 (2.59%) | 2082 | 保留 carbonate，priority=70。 |
| `fragment_006` | `urethane` | 70 | 3027 (5.50%) | 5163 | 移除自然语言 constraints，按 carbonyl/O/N 核心去重。 |
| `fragment_007` | `urea` | 70 | 1117 (2.03%) | 1762 | 移除自然语言 constraints，按 carbonyl + unordered 两个 N 去重。 |

## 关键验证

- `fragment_001 amide` raw match_total=124626，resolved match_total=30312，只删除被更具体 carbonyl-N 片段覆盖的实例。
- `fragment_006 urethane` raw max=6，normalized max=4，说明 wildcard/方向重复已被核心去重压掉。
- `fragment_007 urea` raw max=8，normalized max=3，对称 N-C(=O)-N 重复已被去重。
- 主词表 JSON 不再内嵌 `match_count`，统计全部外置。
