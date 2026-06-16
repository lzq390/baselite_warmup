# core_fragment_v1 片段规则整体 Review 与修复结果

- 生成日期：2026-06-16
- 片段规则表：`fragments_core_v1/core_fragment_v1.json`
- 统计文件：`data/processed/core_fragment_v1_resolved_stats.csv`
- ring match attributes：`data/processed/core_fragment_v1_ring_matches.jsonl`
- 规则总数：31
- active core：31
- derived_attribute：0
- deprecated_alias：0
- rejected：0
- RDKit parser_failed：0
- 11580 canonical 覆盖：11502/11580 (99.3264%)

## 统计口径

- `raw_substruct_*`：执行 SMARTS 或 `rdkit_ring` 原始匹配。
- `normalized_*`：执行 constraints 和 dedup 后的实例；`rdkit_ring` 以 ring atom set 去重。
- `resolved_*`：仅 active core 在 normalized 基础上继续执行 overlap `instance_suppression`；非 active 条目的 resolved 固定为 0。
- 主词表连续编号为 `fragment_001` 到 `fragment_031`。
- 当前主词表全部为 active core，不再混入 derived attribute。

## 主要修复与扩展

- `fragment_016-020` 使用 RDKit ring info 表达四/五/六元真实环；环子类、杂原子组成、稠合/多环、取代拓扑和主链穿环判定作为 match attributes 输出。
- `fragment_009 sulfonyl_group`、`fragment_010 sulfinyl_group`、`fragment_021 alkenylene_linkage`、`fragment_022 alkynylene_linkage`、`fragment_026 trifluoromethyl` 已按当前语义边界重命名或修正 matcher。
- `fragment_001 amide`、`fragment_006 urethane`、`fragment_007 urea` 已改为 core-motif matcher；端基/terminal 形式不再依赖两侧都有显式重原子连接。
- `fragment_004 ether` 与 `fragment_008 thioether` 已补充 repeat-unit 边界连接口径；`C-O-*` / `C-S-*` 等通过 boundary attributes 表达。
- `fragment_013 amine` 与 `fragment_023 secondary_amine_linker` 已排除 sulfonamide N；sulfonamide 继续作为 `fragment_009 sulfonyl_group` 的属性子类。
- `fragment_025 halogen_substituent` 已增加元素、芳香/脂肪连接碳、强氟化/perfluoroalkyl-like 等属性；`fragment_026 trifluoromethyl` 仍作为更具体 core 优先输出。
- 新增 `fragment_027-031`，补齐 C=S、N-O、-SH、Si、P 五类结构-性质解释层；新增片段默认与已有 core 共存，不触发现有 suppression。

## 新增片段 canonical 覆盖

| id | name | records | matches | max_per_record | 设计口径 |
|---|---|---:|---:|---:|---|
| `fragment_027` | `thiocarbonyl_group` | 203 | 238 | 2 | `[#6]=S` 核心键；thioamide、thiourea、isothiocyanate-like 作为属性 |
| `fragment_028` | `nitrogen_oxygen_bond_motif` | 263 | 533 | 9 | `[N]~[O]` 键 motif；nitro、oxime、hydroxylamine/alkoxyamine 作为属性 |
| `fragment_029` | `sulfanyl_or_thiol_group` | 1 | 2 | 2 | `C/S/*-SH` 父级；不合并进 thioether |
| `fragment_030` | `silicon_center` | 512 | 841 | 8 | Si center 父级；siloxane、silyl aryl/alkyl、halosilane 作为属性 |
| `fragment_031` | `phosphorus_center` | 395 | 471 | 7 | P center 父级；phosphoryl、phosphate、phosphazene 作为属性 |

## 当前状态总览

| id | name | status | active | priority | resolved_period_hits | resolved_match_total | resolved_max |
|---|---|---|---:|---:|---:|---:|---:|
| `fragment_001` | `amide` | `core` | 1 | 40 | 16607 | 30321 | 8 |
| `fragment_002` | `imide` | `core` | 1 | 70 | 11348 | 21309 | 4 |
| `fragment_003` | `ester` | `core` | 1 | 50 | 18291 | 34707 | 8 |
| `fragment_004` | `ether` | `core` | 1 | 30 | 27221 | 59025 | 24 |
| `fragment_005` | `carbonate` | `core` | 1 | 70 | 1428 | 2082 | 3 |
| `fragment_006` | `urethane` | `core` | 1 | 70 | 3027 | 5163 | 4 |
| `fragment_007` | `urea` | `core` | 1 | 70 | 1118 | 1763 | 3 |
| `fragment_008` | `thioether` | `core` | 1 | 50 | 2025 | 3157 | 7 |
| `fragment_009` | `sulfonyl_group` | `core` | 1 | 80 | 3233 | 3883 | 3 |
| `fragment_010` | `sulfinyl_group` | `core` | 1 | 70 | 30 | 30 | 1 |
| `fragment_011` | `nitrile` | `core` | 1 | 50 | 1789 | 3279 | 11 |
| `fragment_012` | `hydroxyl` | `core` | 1 | 30 | 1740 | 3216 | 8 |
| `fragment_013` | `amine` | `core` | 1 | 35 | 2478 | 3228 | 4 |
| `fragment_014` | `carbonyl` | `core` | 1 | 20 | 10077 | 12780 | 19 |
| `fragment_015` | `carboxylic_acid` | `core` | 1 | 75 | 226 | 337 | 2 |
| `fragment_016` | `four_membered_ring` | `core` | 1 | 60 | 187 | 194 | 2 |
| `fragment_017` | `five_membered_aromatic_ring` | `core` | 1 | 50 | 6299 | 10013 | 6 |
| `fragment_018` | `five_membered_not_fully_aromatic_ring` | `core` | 1 | 50 | 14117 | 26410 | 9 |
| `fragment_019` | `six_membered_aromatic_ring` | `core` | 1 | 50 | 41477 | 161612 | 20 |
| `fragment_020` | `six_membered_not_fully_aromatic_ring` | `core` | 1 | 50 | 3892 | 5788 | 8 |
| `fragment_021` | `alkenylene_linkage` | `core` | 1 | 50 | 4497 | 7077 | 8 |
| `fragment_022` | `alkynylene_linkage` | `core` | 1 | 50 | 509 | 955 | 6 |
| `fragment_023` | `secondary_amine_linker` | `core` | 1 | 60 | 4389 | 5320 | 6 |
| `fragment_024` | `azo_linker` | `core` | 1 | 50 | 1719 | 2167 | 3 |
| `fragment_025` | `halogen_substituent` | `core` | 1 | 40 | 3188 | 15166 | 30 |
| `fragment_026` | `trifluoromethyl` | `core` | 1 | 80 | 3950 | 8487 | 9 |
| `fragment_027` | `thiocarbonyl_group` | `core` | 1 | 65 | 763 | 898 | 2 |
| `fragment_028` | `nitrogen_oxygen_bond_motif` | `core` | 1 | 55 | 1422 | 2940 | 9 |
| `fragment_029` | `sulfanyl_or_thiol_group` | `core` | 1 | 35 | 4 | 8 | 2 |
| `fragment_030` | `silicon_center` | `core` | 1 | 60 | 1594 | 3236 | 8 |
| `fragment_031` | `phosphorus_center` | `core` | 1 | 60 | 1954 | 2552 | 7 |

## 验收结论

- 规则总数为 31；active core 为 31；derived attribute 为 0。
- 编号连续为 `fragment_001` 到 `fragment_031`。
- 新增 5 条 core 均有 resolved 命中；`fragment_029` 在 11580 中低频，但在 v3 100w 中有明显泛化价值。
- 本轮扩展后 canonical 覆盖提升到 11502/11580 (99.3264%)。
- RDKit parser_failed 为 0。
