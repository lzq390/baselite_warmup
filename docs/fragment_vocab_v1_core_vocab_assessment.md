# fragment_vocab_v1.0 相对 periods2 数据的核心片段评估报告

生成时间：2026-05-06

## 结论摘要

本报告评估 `fragments/vocab/fragment_vocab_v1.0.jsonl` 中 60 条核心词表规则，相对数据为 `data/processed/periods2_from_unique_standardized_smiles.csv` 中 55060 条 sliding period SMILES。

总体结论：这 60 条规则比 `fragments_1/base_fragments.json` 更接近可用核心词表。它已经修正了很多 base 规则中的过宽问题，例如 `ketone`、`sulfone`、`thioether`、`carboxylic_acid` 等 SMARTS 更具体；同时补充了 composite motif、ring、mainchain linker 和 side group 层级。但它仍不适合被理解成“60 个互斥核心片段”。更准确的定位是：一个高覆盖、层级化、有父子重叠的 fragment feature vocabulary。

主要结论：

1. 覆盖能力很强：55060 条 period 中 55051 条至少命中一个 fragment，period 覆盖率为 99.984%；10444 个 source 中 10441 个至少命中一个 fragment，source 覆盖率为 99.971%。
2. 规则全部可被 RDKit 解析，且当前 60 条都至少有一次命中。
3. 平均每条 period 命中 10.26 种 fragment，median 为 9 种，说明词表存在大量父子/泛化/专化重叠。
4. 需要保留 overlap resolver，否则 `FG_CARBONYL`、`FG_AMIDE`、`FG_ETHER`、`RING_AROMATIC_6`、`LINK_ALKYL` 等高频泛化规则会淹没更具体规则。
5. 有一组完全重复 SMARTS：`COMP_AROMATIC_ETHER` 和 `FG_AROMATIC_ETHER` 都使用 `[c:1][OX2:2][c:3]`，建议合并或明确一个是 alias。

## 统计口径

输入文件：

- `fragments/vocab/fragment_vocab_v1.0.jsonl`
- `data/processed/periods2_from_unique_standardized_smiles.csv`

数据规模：

- period SMILES 行数：55060
- period 中涉及的唯一 `source_canonical_id` 数：10444
- 核心词表规则数：60
- RDKit 可解析 SMARTS 数：60

整体覆盖：

- period 中至少命中一个 fragment：55051 / 55060，99.984%
- source 中至少命中一个 fragment：10441 / 10444，99.971%
- 每个 period 平均命中 fragment type 数：10.26
- 每个 period 命中 fragment type 中位数：9
- 每个 period 平均 match instance 数：35.93
- 每个 period match instance 中位数：33

注意：本统计只执行 `match_rule.pattern` 的 RDKit SMARTS 匹配。当前 60 条规则的 `constraints` 都为空，因此没有额外 constraint 过滤。

## 规则分布

| category | 规则数 | 角色判断 |
|---|---:|---|
| functional_group | 24 | 核心功能团主体，整体质量较好，但 carbonyl/amide/ether/amine 类需要父子重叠处理。 |
| side_group | 10 | 适合作为 side feature，不一定都适合作为最小核心片段。 |
| composite_motif | 9 | 多为高价值组合片段，但部分和 functional_group 完全重复或应作为 child motif。 |
| ring_structure | 9 | 覆盖关键环结构，适合作为核心结构特征；融合环和 lactam/imide 需要 overlap。 |
| mainchain_linker | 8 | 对聚合物主链有价值，但 alkyl/methylene/phenylene 规则有过泛风险。 |

## 逐条评估

| id | name | category | period_hits | source_hits | 判断 | 说明 |
|---|---|---|---:|---:|---|---|
| COMP_AROMATIC_AMIDE_N | aromatic_amide_n_linkage | composite_motif | 16118 | 2537 | 保留 | 语义明确，是 amide 的芳香 N 侧组合 motif；应作为 `FG_AMIDE` child，priority 高于 generic amide。 |
| COMP_AROMATIC_AMIDE_C | aromatic_amide_c_linkage | composite_motif | 15410 | 2484 | 保留 | 语义明确，是芳香 acyl amide motif；与上一条互补，适合作为核心 composite。 |
| COMP_CONJUGATED_AROMATIC_PAIR | conjugated_aromatic_pair | composite_motif | 10761 | 2244 | 修改后保留 | `[c]-[c]` 实际是芳香 C-C 单键局部关系，不是完整 aromatic pair；可作为局部 conjugation feature，但不宜当独立核心片段。 |
| COMP_AROMATIC_ETHER | aromatic_ether_linkage | composite_motif | 12277 | 2112 | 合并/保留其一 | 与 `FG_AROMATIC_ETHER` SMARTS 完全相同；建议保留一个 ID，或明确 composite 是 alias/child。 |
| COMP_AROMATIC_IMIDE | aromatic_imide | composite_motif | 9250 | 1679 | 保留 | 高价值特异 motif，priority 高于 imide/lactam 合理。 |
| COMP_POLYSILOXANE_SIDE | polysiloxane_side_substituted | composite_motif | 869 | 266 | 保留 | 命中不高但聚合物语义强，可作为特定材料族核心 composite。 |
| COMP_PERFLUOROALKYL | perfluoroalkyl_segment | composite_motif | 842 | 245 | 保留 | 支持较低但材料语义强；应高于单个 fluoro/CF3 side group。 |
| COMP_BISPHENOL_A_BRIDGE | bisphenol_a_bridge | composite_motif | 2723 | 507 | 保留 | 语义清晰，适合作为高价值结构 motif。 |
| COMP_FLUORINATED_AROMATIC | fluorinated_aromatic | composite_motif | 593 | 165 | 保留 | 支持较低但语义明确，可作为 fluorinated aromatic child motif。 |
| FG_CARBONYL | carbonyl | functional_group | 44247 | 7096 | 父级保留 | 覆盖极高，是 generic carbonyl；适合作为父级 feature，不应在最终解释中压过 ester/amide/imide/urethane 等具体规则。 |
| FG_ETHER | ether | functional_group | 38270 | 6476 | 修改后保留 | 覆盖高，包含 ester/carbonate/urethane 的 alkoxy O；建议作为 oxygen-linkage 父级或加排除规则。 |
| FG_AMIDE | amide | functional_group | 27567 | 3939 | 父级保留 | 仍会覆盖 urea、urethane、imide 等更具体 carbonyl-N 结构；必须依赖 priority/overlap。 |
| FG_ESTER | ester | functional_group | 21909 | 3510 | 保留 | 语义明确、覆盖充分；与 carbonate/urethane/anhydride 的重叠需用 priority。 |
| FG_TERTIARY_AMINE | tertiary_amine | functional_group | 13307 | 2472 | 修改后保留 | 会把部分 amide/imide N 当作三级胺风险较高；需要排除 carbonyl-adjacent N 或改名为 generic tertiary NX3。 |
| FG_SECONDARY_AMINE | secondary_amine | functional_group | 19074 | 2362 | 修改后保留 | 可能包含 secondary amide/urethane N；需要排除 carbonyl-adjacent N。 |
| FG_IMIDE | imide | functional_group | 11353 | 1996 | 保留 | 具体、覆盖充分，适合作为核心功能团。 |
| FG_AROMATIC_ETHER | aromatic_ether | functional_group | 12277 | 2112 | 合并/保留其一 | 与 `COMP_AROMATIC_ETHER` 完全重复；不建议两个都作为独立核心。 |
| FG_KETONE | ketone | functional_group | 4807 | 949 | 保留 | 相比 base 版本已明显收窄为 C-C(=O)-C，适合作为核心。 |
| FG_HYDROXYL | hydroxyl | functional_group | 1958 | 472 | 修改后保留 | 语义明确但需区分 alcohol、phenol、acid OH；当前可作为泛化 hydroxyl。 |
| FG_SULFONE | sulfone | functional_group | 2451 | 512 | 保留 | SMARTS 具体，适合作为 sulfur family 核心。 |
| FG_NITRILE | nitrile | functional_group | 1789 | 368 | 保留 | 语义明确，适合作为核心功能团。 |
| FG_URETHANE | urethane | functional_group | 3027 | 315 | 保留 | 语义明确，支持足够；应高于 amide/ester generic 父级。 |
| FG_THIOETHER | thioether | functional_group | 1869 | 360 | 保留 | `[SX2]` 已避开 sulfone/sulfoxide，规则质量比 base 版好。 |
| FG_SILANE | silane | functional_group | 1280 | 333 | 保留 | 聚合物材料中有语义价值，适合作为材料族功能团。 |
| FG_AZO | azo | functional_group | 1719 | 282 | 保留 | 语义明确，命中支持足够。 |
| FG_CARBONATE | carbonate | functional_group | 1428 | 283 | 保留 | 具体、语义明确，应作为 ester/ether 的更高优先级 child。 |
| FG_THIOCARBONYL | thiocarbonyl | functional_group | 753 | 197 | 低优先级保留 | 命中较低但语义明确，可作为低频核心。 |
| FG_NITRO | nitro | functional_group | 1189 | 196 | 保留 | 语义明确，适合作为侧基/功能团核心。 |
| FG_UREA | urea | functional_group | 1118 | 144 | 保留 | 低频但具体，应高于 amide generic。 |
| FG_PHOSPHAZENE | phosphazene | functional_group | 266 | 131 | 低优先级保留 | period 命中低于 1%，但聚合物材料语义强，可以保留为低频核心。 |
| FG_SILOXANE | siloxane | functional_group | 616 | 124 | 保留 | 命中不高但聚合物语义强；应与 silane/polysiloxane composite 建层级关系。 |
| FG_CARBOXYLIC_ACID | carboxylic_acid | functional_group | 226 | 63 | 低优先级保留 | 低频但语义明确；可保留为低频核心。 |
| FG_ANHYDRIDE | anhydride | functional_group | 351 | 94 | 低优先级保留 | 命中低但具体，应高于 ester/carbonyl 父级。 |
| LINK_ALKYL | alkyl_linker | mainchain_linker | 40678 | 7280 | 父级/辅助 | 覆盖极高且 match instance 很多；适合作为 backbone flexibility feature，不适合作为独立解释性核心片段。 |
| LINK_METHYLENE | methylene_linker | mainchain_linker | 38344 | 6745 | 辅助 | `[CH2]` 过于原子级，更多是统计特征；建议不进入“最小核心片段”，可保留为辅助 linker feature。 |
| LINK_PHENYLENE_PARA | para_phenylene_linkage | mainchain_linker | 33447 | 5631 | 修改后保留 | 当前 SMARTS 可匹配普通苯环，不严格限定 para-phenylene linkage；需要加入取代位点/连接点约束。 |
| LINK_VINYLENE | vinylene_linker | mainchain_linker | 5022 | 956 | 保留 | 语义明确，适合作为主链 unsaturated linker。 |
| LINK_AROMATIC_CARBONYL | aromatic_carbonyl_linkage | mainchain_linker | 3584 | 729 | 保留 | 语义明确，是 ketone/carbonyl 的芳香 linker child。 |
| LINK_AROMATIC_SULFONE | aromatic_sulfone_linkage | mainchain_linker | 2079 | 438 | 保留 | 语义明确，适合作为 sulfone linker child。 |
| LINK_AROMATIC_SULFIDE | aromatic_sulfide_linkage | mainchain_linker | 855 | 179 | 保留 | 支持较低但语义明确，适合保留。 |
| LINK_ETHYNYLENE | ethynylene_linker | mainchain_linker | 525 | 93 | 低优先级保留 | 命中低但主链语义强；需避免把 side-chain alkyne 当 linker。 |
| RING_AROMATIC_6 | aromatic_six_member_ring | ring_structure | 41191 | 7475 | 父级保留 | 覆盖极高，是核心环结构父级；解释时应低于 phenylene、heteroaromatic、fused ring 等具体 motif。 |
| RING_FUSED_AROMATIC_ATOM | fused_aromatic_ring_atom | ring_structure | 16791 | 3210 | 修改后保留 | 当前是 fused aromatic atom 局部特征，不是完整 fused ring；建议改名或升级为 ring-level matcher。 |
| RING_LACTAM | lactam_ring | ring_structure | 11345 | 1993 | 保留 | 支持充分，但与 imide ring 大量重叠；应低于 `RING_IMIDE`。 |
| RING_IMIDE | imide_ring | ring_structure | 11224 | 1961 | 保留 | 具体、高价值，适合作为核心环结构。 |
| RING_HETEROAROMATIC_5 | heteroaromatic_five_member_ring | ring_structure | 6295 | 1434 | 保留 | 语义明确，适合作为核心 ring feature。 |
| RING_HETEROAROMATIC_6 | heteroaromatic_six_member_ring | ring_structure | 2638 | 599 | 保留 | 语义明确，适合作为核心 ring feature。 |
| RING_CYCLOALIPHATIC_6 | cycloaliphatic_six_member_ring | ring_structure | 2669 | 538 | 保留 | 规则与名称一致，适合作为核心 ring feature。 |
| RING_CYCLOALIPHATIC_5 | cycloaliphatic_five_member_ring | ring_structure | 738 | 207 | 保留 | 支持较低但语义明确，适合低频 ring feature。 |
| RING_LACTONE | lactone_ring | ring_structure | 372 | 83 | 低优先级保留 | 命中低但语义明确，应高于 ester/carbonyl 父级。 |
| SUB_ALKOXY | alkoxy_side_group | side_group | 24038 | 3970 | 修改后保留 | 覆盖高，但不区分 backbone ether、ester alkoxy 和 side group；需要 side/backbone ownership 或降级为 oxygen substituent feature。 |
| SUB_METHYL | methyl | side_group | 18212 | 3769 | 辅助 | 常见但语义贡献弱；可保留为 side feature，不建议作为解释性核心片段。 |
| SUB_HALOGEN | halogen_substituent | side_group | 6461 | 1659 | 保留 | 语义明确，适合作为 side group 父级。 |
| SUB_FLUORO | fluoro_substituent | side_group | 5051 | 1246 | 保留 | 语义明确，但与 halogen/perfluoro/CF3 重叠；应作为 child 或同 family 规则。 |
| SUB_ETHYL | ethyl | side_group | 4241 | 1098 | 辅助/保留 | 常见侧基，语义中等；可保留但优先级不应高于材料特异 motif。 |
| SUB_TRIFLUOROMETHYL | trifluoromethyl | side_group | 3888 | 909 | 保留 | 语义明确，适合作为 fluorinated family 核心侧基。 |
| SUB_CHLORO | chloro_substituent | side_group | 1001 | 285 | 保留 | 语义明确，作为 halogen child。 |
| SUB_TERT_BUTYL | tert_butyl | side_group | 1080 | 214 | 保留 | 语义明确，适合作为 bulky side group。 |
| SUB_BROMO | bromo_substituent | side_group | 554 | 156 | 保留 | 语义明确，作为 halogen child。 |
| SUB_ISOPROPYL | isopropyl | side_group | 656 | 141 | 保留 | 语义明确，但低频，可作为 alkyl side group child。 |

## 关键问题

### 1. 词表不是互斥集合

同一个 period 往往同时命中 generic parent 和 specific child。例如：

- `FG_CARBONYL` 与 `FG_ESTER`、`FG_AMIDE`、`FG_IMIDE`、`FG_URETHANE`、`FG_UREA` 重叠。
- `FG_ETHER` 与 `FG_AROMATIC_ETHER`、`COMP_AROMATIC_ETHER`、`SUB_ALKOXY` 重叠。
- `RING_AROMATIC_6` 与 `RING_HETEROAROMATIC_6`、`RING_FUSED_AROMATIC_ATOM`、`LINK_PHENYLENE_PARA` 重叠。
- `SUB_HALOGEN` 与 `SUB_FLUORO`、`SUB_CHLORO`、`SUB_BROMO`、`SUB_TRIFLUOROMETHYL`、`COMP_PERFLUOROALKYL` 重叠。

因此，后续使用时必须明确输出策略：

- 如果目标是 coverage feature，可以保留父子同时命中。
- 如果目标是解释性核心片段，应输出最高 priority 的特异片段，并把父级作为 roll-up tag。

### 2. 完全重复规则

`COMP_AROMATIC_ETHER` 和 `FG_AROMATIC_ETHER` 的 SMARTS 完全相同：

```text
[c:1][OX2:2][c:3]
```

两者当前命中统计完全一致：period_hits 12277，source_hits 2112。建议只保留一个核心 ID；如果需要同时保留，必须明确一个是 alias 或 parent/child，而不是两个独立片段。

### 3. 高频泛化规则需要降级解释

以下规则非常高频，适合作为父级/辅助 feature，但不适合作为最终解释里的核心片段：

- `FG_CARBONYL`
- `LINK_ALKYL`
- `LINK_METHYLENE`
- `RING_AROMATIC_6`
- `SUB_METHYL`
- `FG_ETHER`
- `FG_AMIDE`

这些规则对覆盖率贡献很大，但化学语义偏泛；如果不做 hierarchy roll-up，会导致输出看起来“什么都是 carbonyl/alkyl/aromatic ring”。

### 4. 少数规则命名或边界需要收紧

- `LINK_PHENYLENE_PARA`：当前 SMARTS 不严格表达 para-phenylene linkage，建议加入两个连接位点或 attachment role 约束。
- `RING_FUSED_AROMATIC_ATOM`：当前是 fused aromatic atom 局部模式，不是完整 fused ring，建议改名或升级为 ring-level matcher。
- `SUB_ALKOXY`：当前不区分 side group 与 backbone linkage，需要 ownership/boundary 约束。
- `FG_TERTIARY_AMINE`、`FG_SECONDARY_AMINE`：需要排除 carbonyl-adjacent N，避免与 amide/urethane/urea/imide 混淆。

## 推荐分层

建议把这 60 条分成四层，而不是平铺成一个“核心片段列表”：

1. 核心特异片段：imide、ester、ketone、urethane、urea、carbonate、sulfone、nitrile、azo、nitro、siloxane、phosphazene、anhydride、lactone 等。
2. 核心结构 motif：aromatic amide、aromatic imide、bisphenol A bridge、perfluoroalkyl、polysiloxane side、aromatic sulfone/sulfide/carbonyl linker 等。
3. 父级 roll-up 片段：carbonyl、amide、ether、aromatic six-member ring、alkyl linker、halogen substituent。
4. 辅助统计 feature：methylene、methyl、ethyl、isopropyl、generic alkoxy 等。

## 最终建议

相对于当前 55060 条 `periods2` 数据，这 60 条词表可以作为 v1.0 核心词表的候选基础，但建议在正式确认前做三件事：

1. 合并或解释 `COMP_AROMATIC_ETHER` / `FG_AROMATIC_ETHER` 的重复关系。
2. 建立 hierarchy 输出策略，避免父级 generic 规则和 child 规则同时被当成独立核心结论。
3. 修正 `LINK_PHENYLENE_PARA`、`RING_FUSED_AROMATIC_ATOM`、`SUB_ALKOXY`、secondary/tertiary amine 的边界问题。

如果目标是“高覆盖 fragment feature vocabulary”，这 60 条整体可用；如果目标是“少量互斥、解释性强的核心片段”，应从 60 条中再筛出特异规则，并把泛化规则降为 roll-up 或辅助 feature。
