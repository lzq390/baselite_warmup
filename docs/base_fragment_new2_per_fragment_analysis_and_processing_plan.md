# base_fragment_new2 片段规则整体 Review 与修复结果

- 生成日期：2026-06-04
- 片段规则表：`fragments_1/base_fragment_new2.json`
- 统计文件：`data/processed/base_fragment_new2_resolved_stats.csv`
- ring match attributes：`data/processed/base_fragment_new2_ring_matches.jsonl`
- 规则总数：27
- active core：26
- derived_attribute：1
- deprecated_alias：0
- rejected：0
- RDKit parser_failed：0
- 11580 canonical 覆盖：11329/11580 (97.8325%)

## 统计口径

- `raw_substruct_*`：执行 SMARTS 或 `rdkit_ring` 原始匹配。
- `normalized_*`：执行 constraints 和 dedup 后的实例；`rdkit_ring` 以 ring atom set 去重。
- `resolved_*`：仅 active core 在 normalized 基础上继续执行 overlap `instance_suppression`；非 active 条目的 resolved 固定为 0。
- 当前编号按类别重排，主词表连续为 `fragment_001` 到 `fragment_027`。
- 四元环、五元环、六元环均使用 RDKit ring info；环子类、杂原子组成、稠合/多环、取代拓扑和主链穿环判定作为 match attributes 输出。

## 主要修复

- 主词表按类别重排编号，不再保留历史空号。
- 删除语义已被覆盖且不进入核心输出的旧四元环派生/模板占位。
- 删除语义已被 `fragment_002 imide` / `fragment_003 ester` 覆盖的旧 deprecated alias。
- 保留 `fragment_027 methyl` 为派生属性，因为当前 active core 中没有等价语义覆盖。
- `fragment_016 four_membered_ring` 是四元环唯一 active core。
- `fragment_017 five_membered_aromatic_ring` 与 `fragment_018 five_membered_not_fully_aromatic_ring` 是五元环两个 active core。
- `fragment_019 six_membered_aromatic_ring` 与 `fragment_020 six_membered_not_fully_aromatic_ring` 是六元环两个 active core。
- 六元杂环、稠合六元环、多取代六元环不作为独立 active core，而是通过 ring attributes 表达。
- ring match attribute `aromaticity` 与 `ring_aromaticity_class` 均为三分类：`fully_aromatic` / `partially_aromatic` / `nonaromatic`。
- `mainchain_through_ring` 采用保守口径：`attachment_count >= 2` 时为 `true`，证据不足时为 `unknown`。

## 环结构 canonical 属性分布

- `fragment_016 four_membered_ring`：69 records / 73 rings。
- 四元环芳香性：nonaromatic=67 rings, partially_aromatic=5 rings, fully_aromatic=1 ring。
- 四元环原子类别：carbocycle=64 rings, heterocycle=9 rings。

- `fragment_017 five_membered_aromatic_ring`：1523 records / 2473 rings。
- 五元芳香环原子类别：heterocycle=2465 rings, carbocycle=8 rings。
- 五元芳香环杂原子 signature top：S=773, N=767, N2=377, N,O=129, O=126, N2,O=125。

- `fragment_018 five_membered_not_fully_aromatic_ring`：2918 records / 5353 rings。
- 五元 not fully aromatic 环芳香性：partially_aromatic=4240 rings, nonaromatic=1113 rings。
- 五元 not fully aromatic 环原子类别：heterocycle=4489 rings, carbocycle=864 rings。

- `fragment_019 six_membered_aromatic_ring`：8277 records / 29514 rings。
- 六元芳香环原子类别：carbocycle=28558 rings, heterocycle=956 rings。
- 六元芳香环杂原子 signature top：none=28558, N=439, N2=353, N3=82, O=46, O2=19。
- 六元芳香环稠合/多环：false=21588 rings, true=7926 rings。

- `fragment_020 six_membered_not_fully_aromatic_ring`：913 records / 1388 rings。
- 六元 not fully aromatic 环芳香性：nonaromatic=1183 rings, partially_aromatic=205 rings。
- 六元 not fully aromatic 环原子类别：carbocycle=996 rings, heterocycle=392 rings。
- 六元 not fully aromatic 环稠合/多环：false=759 rings, true=629 rings。

## 当前状态总览

| id | name | status | active | priority | resolved_period_hits | resolved_match_total | resolved_max |
|---|---|---|---:|---:|---:|---:|---:|
| `fragment_001` | `amide` | `core` | 1 | 40 | 16600 | 30312 | 8 |
| `fragment_002` | `imide` | `core` | 1 | 70 | 11348 | 21309 | 4 |
| `fragment_003` | `ester` | `core` | 1 | 50 | 18291 | 34707 | 8 |
| `fragment_004` | `ether` | `core` | 1 | 30 | 23780 | 48102 | 24 |
| `fragment_005` | `carbonate` | `core` | 1 | 70 | 1428 | 2082 | 3 |
| `fragment_006` | `urethane` | `core` | 1 | 70 | 3027 | 5163 | 4 |
| `fragment_007` | `urea` | `core` | 1 | 70 | 1117 | 1762 | 3 |
| `fragment_008` | `thioether` | `core` | 1 | 50 | 1771 | 2656 | 7 |
| `fragment_009` | `sulfone` | `core` | 1 | 80 | 3233 | 3883 | 3 |
| `fragment_010` | `sulfoxide` | `core` | 1 | 70 | 30 | 30 | 1 |
| `fragment_011` | `nitrile` | `core` | 1 | 50 | 1789 | 3279 | 11 |
| `fragment_012` | `hydroxyl` | `core` | 1 | 30 | 1740 | 3216 | 8 |
| `fragment_013` | `amine` | `core` | 1 | 35 | 2907 | 4562 | 4 |
| `fragment_014` | `carbonyl` | `core` | 1 | 20 | 10045 | 12733 | 19 |
| `fragment_015` | `carboxylic_acid` | `core` | 1 | 75 | 226 | 337 | 2 |
| `fragment_016` | `four_membered_ring` | `core` | 1 | 60 | 187 | 194 | 2 |
| `fragment_017` | `five_membered_aromatic_ring` | `core` | 1 | 50 | 6299 | 10013 | 6 |
| `fragment_018` | `five_membered_not_fully_aromatic_ring` | `core` | 1 | 50 | 14117 | 26410 | 9 |
| `fragment_019` | `six_membered_aromatic_ring` | `core` | 1 | 50 | 41477 | 161612 | 20 |
| `fragment_020` | `six_membered_not_fully_aromatic_ring` | `core` | 1 | 50 | 3892 | 5788 | 8 |
| `fragment_021` | `vinylene_linkage` | `core` | 1 | 50 | 3001 | 4240 | 4 |
| `fragment_022` | `ethynylene_linkage` | `core` | 1 | 50 | 509 | 955 | 6 |
| `fragment_023` | `secondary_amine_linker` | `core` | 1 | 60 | 4426 | 5387 | 6 |
| `fragment_024` | `azo_linker` | `core` | 1 | 50 | 1719 | 2167 | 3 |
| `fragment_025` | `halogen_substituent` | `core` | 1 | 40 | 3214 | 16468 | 36 |
| `fragment_026` | `trifluoromethyl` | `core` | 1 | 80 | 3620 | 8053 | 9 |
| `fragment_027` | `methyl` | `derived_attribute` | 0 | 50 | 0 | 0 | 0 |

## 验收结论

- 规则总数为 27；active core 为 26。
- `fragment_019 six_membered_aromatic_ring` 在 canonical 口径命中 8277 records / 29514 rings；period-expanded 口径 resolved_match_total=161612。
- `fragment_020 six_membered_not_fully_aromatic_ring` 在 canonical 口径命中 913 records / 1388 rings；period-expanded 口径 resolved_match_total=5788。
- 编号已连续重排为 `fragment_001` 到 `fragment_027`。
- 非 active 条目只剩 `fragment_027 methyl`，其语义未被当前 active core 覆盖，暂保留为派生属性。
