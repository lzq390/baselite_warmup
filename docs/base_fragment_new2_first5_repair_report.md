# base_fragment_new2 前 5 个核心片段修复报告

- 核心词表：`fragments_1/base_fragment_new2.json`
- 定位：修复前五项后的过渡基准词表，用于保留和审计当前 `fragments_1` 工作；最终 fragment v1 主线以 `fragments/vocab/fragment_vocab_v1.0.*` 为准。
- 匹配数据：`data/processed/periods2_from_unique_standardized_smiles.csv`
- period 总数：55060
- 唯一 source 总数：10444

## 修复范围

| fragment_id | 片段 | 修复内容 |
|---|---|---|
| `fragment_001` | `amide` | 移除全局 not_smarts，priority=40；最终统计采用实例级 overlap 过滤。 |
| `fragment_002` | `imide` | SMARTS 不变，priority 由 50 调到 70，高于 amide/ester。 |
| `fragment_003` | `ester` | SMARTS 和 priority 保持，作为 ester 基础核心。 |
| `fragment_004` | `ether` | SMARTS 从宽泛 [*][OX2][*] 收窄为非 carbonyl-adjacent 的 C-O-C，priority=30。 |
| `fragment_005` | `carbonate` | 移除自然语言 exclude，priority 由 50 调到 70，高于 ester/ether。 |

## 修复前后统计

| fragment_id | old_period_hits | old_source_hits | old_match_total | old_max | new_period_hits | new_source_hits | new_match_total | new_max | priority |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `fragment_001` | 27559 (50.05%) | 3934 (37.67%) | 124626 | 18 | 16579 (30.11%) | 2392 (22.90%) | 31319 | 8 | 40 |
| `fragment_002` | 11348 (20.61%) | 1993 (19.08%) | 21357 | 6 | 11348 (20.61%) | 1993 (19.08%) | 21357 | 6 | 70 |
| `fragment_003` | 21707 (39.42%) | 3455 (33.08%) | 44034 | 8 | 21707 (39.42%) | 3455 (33.08%) | 44034 | 8 | 50 |
| `fragment_004` | 40715 (73.95%) | 6868 (65.76%) | 108289 | 38 | 23780 (43.19%) | 4113 (39.38%) | 48102 | 24 | 30 |
| `fragment_005` | 1428 (2.59%) | 283 (2.71%) | 2082 | 3 | 1428 (2.59%) | 283 (2.71%) | 2082 | 3 | 70 |

## 关键验证

- `fragment_004 ether` 从 `[*][OX2][*]` 收窄到 `[#6;!$(C=O)][OX2][#6;!$(C=O)]` 后，match_total 从 108289 降到 48102。
- 新 ether 与 `C(=O)-O` carbonyl-adjacent O 的重叠检查为 0，说明 ester/carbonate/urethane 中的单键 O 已被排除。
- `fragment_001 amide` 的最终统计采用实例级 overlap 过滤，保留普通 amide，排除被 imide/urethane/urea 覆盖的 amide-like 局部。
- `fragment_002 imide` 和 `fragment_005 carbonate` 通过 priority=70 压过 amide/ester/ether 等更泛化片段。
