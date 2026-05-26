# base_fragments 相对 periods2 数据的核心片段评估报告

生成时间：2026-05-06

## 结论摘要

本次评估对象是 `fragments_1/base_fragments.json` 中的 40 条基础 fragment 规则，数据对象是 `data/processed/periods2_from_unique_standardized_smiles.csv` 中 55060 条去重后的 sliding period SMILES。

结论是：`base_fragments.json` 不能直接作为最终核心词表使用。它适合作为“初始人工 seed 清单”，但其中一部分规则需要重命名、收窄 SMARTS、补充可执行 constraint、合并重复项或降级为非核心辅助片段。

最主要的问题有四类：

1. `periods2` 的 55060 行不是 55060 个独立聚合物，而是由 11580 个标准化 RU 派生出的 period 候选；同一个 `source_canonical_id` 可能贡献多个 period。因此判断核心性时必须同时看 period 命中数和 source 命中数。
2. 多数 `constraints.exclude` 是自然语言标签，不是可执行 SMARTS 或函数约束；如果后续脚本不实现 constraint registry，这些规则不会真正生效。
3. 多个通用规则过宽，例如 `ketone` 的 `[*][C](=O)[*]` 实际会匹配大量 ester、amide、urethane、urea、imide 等 carbonyl family。
4. 环规则里存在命名和 SMARTS 不一致、重复规则和零命中规则，尤其 `fragment_030` 到 `fragment_033` 与 `fragment_020` 到 `fragment_023` 完全重复，但名称写成 aromatic。

建议把当前 40 条规则分成三类处理：

- 可直接进入核心候选：`imide`、`ester`、`sulfone`、`nitrile`、`carboxylic_acid`、`vinylene_linkage`、`ethynylene_linkage`。
- 修改后进入核心候选：`amide`、`ether`、`carbonate`、`urethane`、`urea`、`thioether`、`sulfoxide`、`hydroxyl`、`amine`、`ketone`、`five/six_membered_aliphatic_ring`、`five/six_membered_aromatic_ring`、`halogen_substituent`、`trifluoromethyl`。
- 不建议作为核心片段，建议删除、合并或降级：三/四元小环取代模式细分规则、零命中规则、重复的 030-033、`methyl` 这类过于常见但语义贡献弱的侧基。

## 统计口径

输入文件：

- `fragments_1/base_fragments.json`
- `data/processed/periods2_from_unique_standardized_smiles.csv`

数据规模：

- period SMILES 行数：55060
- period 中涉及的唯一 `source_canonical_id` 数：10444
- base fragment 规则数：40
- RDKit 可解析 SMARTS 数：40

统计字段说明：

- `period_hits`：55060 条 period 中至少命中一次该 SMARTS 的行数。
- `period_hit_rate`：`period_hits / 55060`。
- `match_total`：所有 period 上的总 match instance 数。
- `source_hits`：至少有一个 period 命中该 SMARTS 的唯一 `source_canonical_id` 数。
- `source_hit_rate`：`source_hits / 10444`。

注意：本统计只执行 `match_rule.pattern` 的 RDKit SMARTS 匹配，没有执行自然语言 `exclude`、`exact_fluorine_count` 等 constraint。因此表中的命中率代表“当前 SMARTS 原始覆盖”，不是最终可信覆盖。

## 总体质量判断

适合作为核心 fragment 的规则应至少满足：

1. 化学语义明确，名称与 SMARTS 一致。
2. SMARTS 不应明显过宽，不能主要依赖未实现的自然语言 constraint 才能成立。
3. 与同 family 片段的重叠关系要可通过 priority 或 overlap resolver 解释。
4. 在当前数据上有足够支持；低频但化学意义强的片段可以保留，但应标为低优先级。
5. 不能用重复规则表达不同名称。

按这个标准，当前 base JSON 中最大的问题不是“有没有命中”，而是“命中是否代表这个 fragment 的真实语义”。

## 每个片段评估

| id | name | category | period_hits | source_hits | 判断 | 说明 |
|---|---|---:|---:|---:|---|---|
| fragment_001 | amide | functional_group | 27559 | 3934 | 修改后保留 | amide 是核心片段，但当前约束用 `not_smarts` 在 molecule 级过滤 urea/imide，容易误杀同一 period 中其它合法 amide；应改成 match instance 级 overlap/priority。 |
| fragment_002 | imide | functional_group | 11348 | 1993 | 保留 | 语义明确、支持充分，适合作为 carbonyl family 的高优先级核心片段。 |
| fragment_003 | ester | functional_group | 21707 | 3455 | 保留 | 语义明确、支持充分，适合作为核心片段；后续需处理与 carbonate、ketone、ether 的 overlap。 |
| fragment_004 | ether | functional_group | 40715 | 6868 | 修改后保留 | 覆盖很高，但 `[OX2]` 会命中 ester/carbonate/urethane 中的 O；若作为 ether linkage，需要排除 carbonyl-adjacent O 或用 overlap policy 降级。 |
| fragment_005 | carbonate | functional_group | 1428 | 283 | 修改后保留 | 化学语义明确，但 `exclude` 是自然语言，不会自动生效；应注册可执行约束，并高于 ester/ether 处理。 |
| fragment_006 | urethane | functional_group | 3027 | 315 | 修改后保留 | 语义重要，支持不算高但可保留；右端 `[*,H]` 和自然语言 exclude 需要明确为可执行规则。 |
| fragment_007 | urea | functional_group | 1117 | 143 | 修改后保留 | 语义明确但低频；应作为比 amide 更具体的 carbonyl family 规则，使用 overlap priority 保护。 |
| fragment_008 | thioether | functional_group | 5605 | 1005 | 修改后保留 | 当前 `[S]` 规则可能与 sulfone/sulfoxide 重叠，且 exclude 不可执行；建议收窄为无 S=O 的 divalent sulfur。 |
| fragment_009 | sulfone | functional_group | 3233 | 586 | 保留 | SMARTS 本身较具体，适合作为 sulfur family 核心片段；仍需在 overlap 中优先于 thioether。 |
| fragment_010 | sulfoxide | functional_group | 30 | 9 | 低优先级保留 | 命中极低，但化学意义明确；可保留为低频核心或扩展词，不应影响主覆盖目标。 |
| fragment_011 | nitrile | functional_group | 1789 | 368 | 保留 | SMARTS 具体、语义明确，适合作为核心侧基/功能团。 |
| fragment_012 | hydroxyl | functional_group | 1958 | 472 | 修改后保留 | 当前会混入 carboxylic acid、phenol 等情况；需要明确 alcohol/phenol/acid 的分类边界。 |
| fragment_013 | amine | functional_group | 30741 | 4627 | 修改后保留 | 覆盖很高但过宽，会覆盖 amide/urea/imide/aromatic amine 等；不应按当前规则直接作为核心 amine。 |
| fragment_014 | ketone | functional_group | 44227 | 7085 | 不建议按当前规则保留 | 当前 `[*][C](=O)[*]` 基本是 generic carbonyl，会大量命中 ester、amide、imide、urethane、carbonate；必须改成真正 ketone 后再考虑。 |
| fragment_015 | carboxylic_acid | functional_group | 226 | 63 | 保留 | 低频但 SMARTS 较具体，适合作为低频核心功能团；后续可补 carboxylate/acid 状态处理。 |
| fragment_016 | three_membered_aliphatic_heterocycle_one_substituted | cycloaliphatic_ring | 145 | 32 | 不建议核心 | 支持极低，且 `[C,N,O,S;R]` 并不限定 heterocycle；小环取代数细分不适合作为初始核心。 |
| fragment_017 | three_membered_aliphatic_heterocycle_two_substituted | cycloaliphatic_ring | 79 | 14 | 不建议核心 | 支持极低，规则过细；建议归入小环扩展集或统一 ring feature。 |
| fragment_018 | three_membered_aliphatic_heterocycle_three_substituted | cycloaliphatic_ring | 0 | 0 | 删除或归档 | 当前数据零命中，不适合作为核心。 |
| fragment_019 | four_membered_aliphatic_heterocycle_one_substituted | cycloaliphatic_ring | 162 | 56 | 不建议核心 | 支持很低，且语义与 SMARTS 不完全一致；建议用更通用 ring descriptor 替代。 |
| fragment_020 | four_membered_aliphatic_heterocycle_two_substituted_first | cycloaliphatic_ring | 139 | 42 | 合并/归档 | 与 030 完全重复；取代模式细分过细，不建议进入核心。 |
| fragment_021 | four_membered_aliphatic_heterocycle_two_substituted_second | cycloaliphatic_ring | 150 | 48 | 合并/归档 | 与 031 完全重复；不建议作为独立核心。 |
| fragment_022 | four_membered_aliphatic_heterocycle_three_substituted | cycloaliphatic_ring | 138 | 41 | 合并/归档 | 与 032 完全重复；不建议作为独立核心。 |
| fragment_023 | four_membered_aliphatic_heterocycle_four_substituted | cycloaliphatic_ring | 109 | 33 | 合并/归档 | 与 033 完全重复；不建议作为独立核心。 |
| fragment_024 | five_membered_aliphatic_heterocycle | cycloaliphatic_ring | 2340 | 531 | 修改后保留 | 支持尚可，但名称中的 heterocycle 不准确；SMARTS 允许全碳环，应改名为 five_membered_aliphatic_ring 或补 hetero atom 约束。 |
| fragment_025 | six_membered_aliphatic_heterocycle | cycloaliphatic_ring | 3581 | 743 | 修改后保留 | 支持尚可，但名称和 SMARTS 不一致；建议作为 generic six_membered_aliphatic_ring，或拆成 carbocycle/heterocycle。 |
| fragment_026 | three_membered_aromatic_heterocycle_one_substituted | aromatic_ring | 132 | 12 | 不建议核心 | 支持极低，三元 aromatic heterocycle 很罕见；不适合初始核心。 |
| fragment_027 | three_membered_aromatic_heterocycle_two_substituted | aromatic_ring | 132 | 12 | 不建议核心 | 支持极低；可归档为扩展规则。 |
| fragment_028 | three_membered_aromatic_heterocycle_three_substituted | aromatic_ring | 0 | 0 | 删除或归档 | 当前数据零命中。 |
| fragment_029 | four_membered_aromatic_heterocycle_one_substituted | aromatic_ring | 12 | 1 | 删除或归档 | 只有 1 个 source 命中，不适合作为核心。 |
| fragment_030 | four_membered_aromatic_heterocycle_two_substituted_first | cycloaliphatic_ring | 139 | 42 | 删除 | 与 020 完全相同，且名称 aromatic、category cycloaliphatic、SMARTS aliphatic 三者冲突。 |
| fragment_031 | four_membered_aromatic_heterocycle_two_substituted_second | cycloaliphatic_ring | 150 | 48 | 删除 | 与 021 完全相同，命名错误。 |
| fragment_032 | four_membered_aromatic_heterocycle_three_substituted | cycloaliphatic_ring | 138 | 41 | 删除 | 与 022 完全相同，命名错误。 |
| fragment_033 | four_membered_aromatic_heterocycle_four_substituted | cycloaliphatic_ring | 109 | 33 | 删除 | 与 023 完全相同，命名错误。 |
| fragment_034 | five_membered_aromatic_heterocycle | aromatic_ring | 6296 | 1435 | 修改后保留 | 支持充分；但 `[c,n,o,s]` 包含碳，名称应改为 five_membered_aromatic_ring，若要 heterocycle 需要求至少一个 hetero atom。 |
| fragment_035 | six_membered_aromatic_heterocycle | aromatic_ring | 41477 | 7557 | 修改后保留 | 极高频，实际主要是六元芳香环而不是 heterocycle；应改名为 six_membered_aromatic_ring 或拆分 benzene/heteroaromatic。 |
| fragment_036 | vinylene_linkage | mainchain_linker | 3001 | 530 | 保留 | 语义明确，支持足够，适合作为主链连接片段。 |
| fragment_037 | ethynylene_linkage | mainchain_linker | 509 | 82 | 保留 | 支持较低但化学意义强、规则明确，可作为低频核心 linker。 |
| fragment_038 | halogen_substituent | side_group | 6461 | 1659 | 修改后保留 | 支持高，但最大单 period match 很高，说明 perfluoro/多卤结构会放大计数；`exclude_inorganic_halides` 需要可执行化。 |
| fragment_039 | trifluoromethyl | side_group | 3888 | 909 | 修改后保留 | 支持充分，但 `exact_fluorine_count` 和 `exclude_perfluoroalkyl_chain` 未执行；应防止把 perfluoroalkyl chain 中的局部 CF3 全部当作独立 CF3 侧基。 |
| fragment_040 | methyl | side_group | 18204 | 3764 | 不建议核心 | 命中高但语义贡献弱，容易把普通烷基环境碎片化；建议降级为辅助侧基特征，不进入核心词表。 |

## 重复与命名错误

以下规则的 SMARTS 完全重复：

| 重复 SMARTS | 对应 fragment |
|---|---|
| `[C,N,O,S;R]1([*])[C,N,O,S;R]([*])[C,N,O,S;R][C,N,O,S;R]1` | `fragment_020` 和 `fragment_030` |
| `[C,N,O,S;R]1([*])[C,N,O,S;R][C,N,O,S;R]([*])[C,N,O,S;R]1` | `fragment_021` 和 `fragment_031` |
| `[C,N,O,S;R]1([*])[C,N,O,S;R]([*])[C,N,O,S;R]([*])[C,N,O,S;R]1` | `fragment_022` 和 `fragment_032` |
| `[C,N,O,S;R]1([*])[C,N,O,S;R]([*])[C,N,O,S;R]([*])[C,N,O,S;R]([*])1` | `fragment_023` 和 `fragment_033` |

其中 `fragment_030` 到 `fragment_033` 名称包含 `aromatic`，但 SMARTS 使用大写 `[C,N,O,S;R]`，实际是非芳香原子模式；category 又写成 `cycloaliphatic_ring`。这几条不应进入核心词表。

## 约束字段问题

当前 constraints 分三类：

1. `not_smarts`：只有 `fragment_001` 使用，两个值可以被 RDKit 解析为 SMARTS。
2. `exclude`：多数是自然语言标签，例如 `amide_if_adjacent_carbonyl`、`carbonate_if_no_N`，不能被 RDKit 直接执行。
3. 布尔/数值约束：例如 `exclude_inorganic_halides`、`exact_fluorine_count`、`exclude_perfluoroalkyl_chain`，需要单独代码实现。

如果核心词表生成或后续匹配阶段不实现 constraint registry，则这些字段只会留在 JSON 里，不会影响匹配结果。建议：

- 所有 constraint key 必须注册到 registry。
- 未知 constraint key 默认 fail-fast，或者输出 invalid rule report。
- `exclude` 这类自然语言字段不能直接进入最终核心词表，应改成可执行规则或迁移到备注字段。
- carbonyl、nitrogen、sulfur family 应优先用 overlap priority + match instance 级过滤，而不是 molecule 级整体排除。

## 推荐的核心词表处理方案

第一批可以进入核心候选的片段：

- `imide`
- `ester`
- `sulfone`
- `nitrile`
- `carboxylic_acid`
- `vinylene_linkage`
- `ethynylene_linkage`

第二批修改后进入核心候选的片段：

- `amide`：去掉 molecule 级 `not_smarts`，改成 carbonyl family overlap。
- `ether`：排除 carbonyl-adjacent O，或者作为低优先级 linkage。
- `carbonate`、`urethane`、`urea`：实现可执行 constraint，并设置高于 ester/amide 的 priority。
- `thioether`：收窄为无 S=O 的 divalent sulfur。
- `sulfoxide`：保留为低频 sulfur family。
- `hydroxyl`：拆分 alcohol、phenol、carboxylic acid OH。
- `amine`：排除 amide/urea/imide/aromatic amine，或改名为 generic_NX3。
- `ketone`：必须重写，排除 N/O/S 连接的 carbonyl。
- `five/six_membered_aliphatic_ring`：修正名称，必要时拆分 carbocycle/heterocycle。
- `five/six_membered_aromatic_ring`：修正名称，必要时拆分 benzene/heteroaromatic。
- `halogen_substituent`、`trifluoromethyl`：实现卤素/氟化侧基专用约束。

不建议进入核心词表的片段：

- `three_membered_*` 和 `four_membered_*` 的细分取代模式规则。
- 零命中的 `fragment_018`、`fragment_028`。
- 与 020-023 重复且命名错误的 `fragment_030` 到 `fragment_033`。
- `methyl`：建议作为辅助 feature，而不是核心 fragment。

## 最终建议

相对于当前 55060 条 periods2 数据，`base_fragments.json` 的片段覆盖能力是够的，但规则质量还没有达到“最终核心词表”的标准。下一步不建议直接把全部 40 条写入核心词表，而应先做以下整理：

1. 删除或归档零命中、重复、命名错误的小环规则。
2. 重命名芳香/脂环规则，确保名称与 SMARTS 一致。
3. 为 carbonyl、nitrogen、sulfur、halogen/fluorinated family 建立可执行 constraint 和 overlap resolver。
4. 把 `ketone`、`amine`、`ether`、`methyl` 这类过宽片段从核心词表中暂缓，待 SMARTS 收窄后再纳入。
5. 用 `source_canonical_id` 覆盖率作为核心词表确认指标之一，避免被 period 派生数量误导。

按当前状态，推荐的核心词表不是 40 条全量 base fragments，而是“7 条可直接保留 + 约 15 条修正后保留 + 小环/重复/过宽规则剔除或降级”的版本。
