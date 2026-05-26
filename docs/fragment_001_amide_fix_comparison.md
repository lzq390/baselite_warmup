# fragment_001 amide 修复前后匹配统计对比

- 核心词表：`fragments_1/base_fragment_new2.json`
- 匹配数据：`data/processed/periods2_from_unique_standardized_smiles.csv`
- period 总数：55060
- 唯一 source 总数：10444
- 无法解析 period SMILES：0

## 修复内容

- 从 `fragment_001` 的 `match_rule.constraints` 中移除全局 `not_smarts`。
- 将 `fragment_001.overlap_policy.priority` 从 50 调整为 40。
- 修复后的统计使用实例级 overlap 过滤：当 amide match 的核心原子 `{amide N, carbonyl C, carbonyl O}` 被 `imide`、`urethane` 或 `urea` match 覆盖时，丢弃该 amide match；同一 molecule 中其它独立 amide match 保留。

## 统计对比

| 口径 | period_hits | period_coverage | source_hits | source_coverage | match_total | max_per_period |
|---|---:|---:|---:|---:|---:|---:|
| 原始 SMARTS，不执行约束 | 27559 | 50.05% | 3934 | 37.67% | 124626 | 18 |
| 旧全局 not_smarts 模拟 | 15411 | 27.99% | 1888 | 18.08% | 29806 | 9 |
| 修复后实例级 overlap 过滤 | 16579 | 30.11% | 2392 | 22.90% | 31319 | 8 |

## 差异解读

- 原始 SMARTS 命中 124626 个 amide-like match，覆盖 27559 条 period。这个值包含 imide、urethane、urea 内部的 `N-C(=O)` 局部命中。
- 旧全局 `not_smarts` 模拟只剩 29806 个 match，覆盖 15411 条 period。它会把含有 imide/urea 局部的整个 molecule 排除，容易误删同一 period 里的其它独立 amide。
- 修复后实例级过滤保留 31319 个 match，覆盖 16579 条 period。它只删除被更具体结构覆盖的 amide match，不删除同一 molecule 中其它合法 amide。
- 实例级过滤从原始 SMARTS 中删除 93307 个 match；按更具体片段归因：`urethane`=5187, `imide`=85034, `urea`=3086。

## 示例

| row_index | source | raw_amide_matches | fixed_kept_matches | dropped_matches | old_global_blocked | smiles |
|---:|---|---:|---:|---:|---|---|
| 11 | `ru_001719` | 2 | 0 | 2 | False | `*#CC#CCOC(=O)NCCCCCCNC(=O)OCC#*` |
| 12 | `ru_001720` | 2 | 0 | 2 | False | `*#CC#CCOC(=O)Nc1ccc(Cc2ccc(NC(=O)OCC#*)cc2)cc1` |
| 14 | `ru_004761` | 2 | 0 | 2 | False | `*#CC#CCOCCOCCOC(=O)NCCCCCCNC(=O)OCCOCCOCC#*` |
| 32 | `ru_000243` | 1 | 0 | 1 | False | `*#CC(CCCCOC(=O)NCC(=O)OCCCC)=C(C#*)c1cncnc1` |
| 44 | `ru_001727` | 2 | 0 | 2 | False | `*#CCOC(=O)NCCCCCCNC(=O)OCC#*` |
| 76 | `ru_000964` | 8 | 0 | 8 | True | `*#Cc1cccc(N2C(=O)c3ccc(C(=O)c4ccc5c(c4)C(=O)N(c4cccc(C#*)c4)C5=O)cc3C2=O)c1` |
| 77 | `ru_000506` | 5 | 1 | 4 | True | `*#Cc1cccc(NC(=O)c2ccc3c(c2)C(=O)N(c2cccc(C#*)c2)C3=O)c1` |
| 120 | `ru_005707` | 2 | 0 | 2 | False | `*/C=C(\C#N)C(=O)OCCCCCCOC(=O)/C(C#N)=C/c1ccc2c(c1)c1ccccc1n2CCCCOC(=O)Nc1cc(NC(=O)OCCCCn2c3ccccc3c3cc(*)ccc32)ccc1C` |
| 121 | `ru_010147` | 2 | 0 | 2 | False | `*/C=C(\C#N)C(=O)OCCCCCCOC(=O)/C(C#N)=C/c1ccc2c(c1)c1ccccc1n2CCCCOC(=O)Nc1ccc(-c2ccc(NC(=O)OCCCCn3c4ccccc4c4cc(*)ccc43)c(C)c2)cc1C` |
| 122 | `ru_005707` | 2 | 0 | 2 | False | `*/C=C(\C#N)C(=O)OCCCCCCOC(=O)/C(C#N)=C/c1ccc2c(c1)c1ccccc1n2CCCCOC(=O)Nc1ccc(C)c(NC(=O)OCCCCn2c3ccccc3c3cc(*)ccc32)c1` |
| 132 | `ru_000177` | 2 | 0 | 2 | False | `*/C=C(\C#N)C(=O)OCCCCCCOC(=O)C(C#N)Cc1ccc2c(c1)c1ccccc1n2CCCCOC(=O)Nc1ccc(Cc2ccc(NC(=O)OCCCCn3c4ccccc4c4cc(*)ccc43)cc2)cc1` |
| 184 | `ru_005690` | 2 | 0 | 2 | False | `*/C=C/C1=CC(=C(C#N)C#N)C=C(/C=C/c2ccc(N3CCC(OC(=O)Nc4cc(NC(=O)OC5CCN(c6ccc(*)s6)CC5)ccc4C)CC3)s2)O1` |

## 结论

修复后的 amide 仍是高覆盖核心片段，但不再用 molecule 级 `not_smarts` 粗暴排除。后续正式 matcher 应按同样逻辑在 carbonyl family 内执行 priority：`imide/urethane/urea > amide > generic carbonyl`。