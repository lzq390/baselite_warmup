# fragment_vocab_v1 构建方案：main repeat-unit 生产版

本文档是 `fragment_vocab_v1` 的生产执行说明。目标是从
`D:\database\mllm_data\all_polymers_experiment_final.csv` 中清洗出可用的两连接点聚合物 repeat-unit SMILES，构建一份可执行、可验证、可复现的 fragment 规则词表。

核心规则文件只包含匹配和归属所需字段；统计、示例、审核和下游模型配置放到辅助文件中。

字段定义见：

```text
fragment_vocab_v1_schema_fields.md
```

---

## 1. 输入数据

原始文件：

```text
D:\database\mllm_data\all_polymers_experiment_final.csv
```

原始字段：

```text
smiles, 性质分类, 性质名, 值, 单位
```

数据审计结果：

```text
CSV 数据行：64,071
唯一 raw smiles：23,956
恰好 2 个连接点的唯一 raw smiles：23,798
剔除 "." / "," / "[R]" / "[R1]" / "[R2]" 等未定义 R 基后的两连接点唯一 raw smiles：23,791
按生产 attachment 规则统一后的两连接点主构建唯一 smiles：12,184
```

连接点分布：

```text
2 个 *：48,465 行 / 23,798 唯一 smiles
0 个 *：13,646 行 / 105 唯一 smiles
4 个 *：1,954 行 / 47 唯一 smiles
1 个 *：6 行 / 6 唯一 smiles
```

---

## 2. 主数据准入规则

CSV 是 long-format 属性表，同一个 polymer string 可能有多条性质记录。构建词表时必须先聚合到 unique polymer string，再给每个 unique string 分配 `record_type`。

推荐 `record_type`：

```text
main_repeat_unit: 进入 fragment_vocab_v1 主构建集。
monomer_or_descriptor_record: 0 个连接点的小分子、单体、comonomer 描述符记录，不进入主词表，但单独保留。
incomplete_attachment: 1 个连接点，进入 failed_cases。
copolymer_candidate: 4 个连接点或含 "," 的多 repeat-unit 拼接，进入人工队列或后续共聚物流程。
ionomer_or_multicomponent_candidate: 含 "." 的盐、离子配对或多组分形式，先进入人工队列，不直接混入主构建集。
unresolved_R_group: 含 "[R]"、"[R1]"、"[R2]" 等未定义取代基，默认进入 failed_cases，除非后续有明确专用解析规则。
parser_failed: 连接点形式合格但化学工具无法解析或无法构图。
```

进入 `fragment_vocab_v1` 主构建集的样本必须满足：

```text
1. 连接点数量为 2。
2. 不含 "." 盐/溶剂/添加剂形式，除非已被人工确认为可转成单一 repeat-unit graph。
3. 不含 "," 共聚物拼接形式。
4. 不含 "[R]"、"[R1]"、"[R2]" 等未定义取代基。
5. 可被化学工具解析并标准化。
6. 可构建 repeat_unit_graph。
```

不进入主构建集的样本：

```text
0 个 *：小分子、单体、comonomer 描述符或辅助分子，进入 monomer_or_descriptor_record。
1 个 *：连接点不完整，进入 failed_cases。
4 个 *：共聚物或多 repeat-unit 表示，进入 copolymer_candidates。
含 "."：盐/多组分，优先进入 ionomer_or_multicomponent_candidate 人工队列；确认无法解析时才进入 failed_cases。
含 ","：多 repeat-unit 拼接，进入 copolymer_candidates。
含 [R] / [R1] / [R2] 等：未定义取代基，默认进入 failed_cases。
```

---

## 3. 标准化规则

先做 attachment 文本统一：

```text
[[[*]]]  -> *
[[*]]    -> *
[*]      -> *
[*:1]    -> *
[*:2]    -> *
```

执行顺序必须采用最长匹配优先。当前 CSV 中 `[[*]]` 和 `[[[*]]]` 都大量存在；如果漏掉 `[[*]] -> *`，会残留 `[*]`，导致 level 2 去重和后续 parser 输入口径错误。

未定义 R 基不属于 attachment token，不做自动连接点替换：

```text
[R] / [R1] / [R2] / ... -> unresolved_R_group
```

然后执行化学标准化：

```text
1. 去空值、去首尾空格、去不可见字符。
2. 统一芳香性模型。
3. 统一显式/隐式氢策略。
4. 统一电荷和 isotope 策略。
5. 生成 canonical_repeat_unit_string。
6. 构建 repeat_unit_graph。
7. 生成 canonical graph hash。
```

去重层级：

```text
level 1: raw smiles exact dedup
level 2: attachment-normalized string dedup
level 3: canonical_repeat_unit_string dedup
level 4: repeat_unit_graph canonical hash dedup
level 5: primitive periodic graph hash dedup
```

生产报告必须记录每一层去重后的样本数。

当前 CSV 已确认的前两层口径：

```text
level 1 raw unique: 23,956
level 1 raw two-attachment main candidates after text exclusions: 23,791
level 2 attachment-normalized two-attachment main unique: 12,184
```

level 3-5 必须在 canonicalizer、repeat_unit_graph builder 和 primitive periodic reduction 固定版本后重新统计，不允许继续沿用 raw unique 或 level 2 unique 作为最终训练 / mining 分母。

---

## 4. repeat_unit_graph 要求

节点最小字段：

```text
element
aromatic
formal_charge
hybridization
degree
ring_membership
is_attachment
attachment_role
```

边最小字段：

```text
bond_type
aromatic
is_repeat_connection
is_periodic_edge
```

默认使用 centered 3-mer expansion：

```text
RU[-1] + RU[0] + RU[+1]
```

用途：

```text
1. 捕获跨边界 fragment。
2. 验证 cut-shift 稳定性。
3. 通过 anchor ownership 避免重复计数。
```

---

## 5. 词表规模

生产版建议规模：

```text
核心词表：50-100 个 fragment type
候选池：150-500 个 candidate motif
```

核心词表只收录同时满足以下条件的 fragment：

```text
1. 高频或明确性质相关。
2. 化学含义清楚。
3. 可稳定匹配。
4. 可定义 anchor。
5. 对 repeat-unit 切分起点稳定。
6. 与已有 fragment 不产生不可控冗余。
```

---

## 6. Seed Rules

先人工定义 50-80 个 seed fragment rules，再用数据驱动 mining 补充。

seed 类别：

```text
官能团：amide, imide, ester, carbonate, urethane, urea, ether, thioether,
       sulfone, sulfoxide, nitrile, hydroxyl, amine, ketone, carboxylic_acid,
       nitro, azo, carboxylate, sulfonate, quaternary_ammonium

环结构：aromatic_ring, phenylene, fused_aromatic_ring, heteroaromatic_ring,
       cycloaliphatic_ring, imide_ring

主链连接：alkyl_linker, ether_linkage, amide_linkage, ester_linkage,
         carbonate_linkage, sulfone_linkage, imide_linkage, vinylene_linkage,
         ethynylene_linkage, phenylene_linkage

侧基/取代基：halogen_substituent, fluorinated_group, trifluoromethyl,
           methyl, ethyl, phenyl_side_group, alkoxy_side_group,
           hydroxyl_side_group, nitrile_side_group, silyl_side_group

复合 motif：aromatic_amide, aromatic_imide, aromatic_sulfone,
          fluorinated_aromatic, conjugated_aromatic_segment,
          rigid_linear_backbone_segment, hydrogen_bonding_unit,
          siloxane_segment, phosphazene_segment, ionic_group_pair
```

---

## 7. Motif Mining

在清洗后的主构建集上挖候选 motif。生产分母必须使用固定版本 pipeline 输出的 level 3-5 之一，并在报告中写明；在当前仅有文本规范化结果时，临时分母为 level 2 的 12,184 个主构建 unique strings。

候选大小：

```text
MVP：3-6 atoms
允许范围：2-8 atoms
```

推荐 mining 方法：

```text
1. 原子半径邻域子图，r = 1 or 2。
2. 键中心子图。
3. 环系统和短路径 motif。
```

频率过滤：

```text
accepted_core 候选：coverage_ratio >= 0.4% 或 coverage_count >= 50
accepted_auxiliary 候选：coverage_ratio >= 0.13% 或 coverage_count >= 15，且有明确化学含义或性质相关性
descriptor_only / rejected_low_frequency：低于 auxiliary 阈值，除非是人工 seed 关键片段
```

如果临时使用 level 2 主构建集 12,184 作为分母：

```text
coverage_count 15  ≈ 0.12%
coverage_count 30  ≈ 0.25%
coverage_count 50  ≈ 0.41%
coverage_count 100 ≈ 0.82%
```

如果后续 canonical graph 去重后的分母发生变化，应保留 ratio 阈值，并重新计算 count 等价值。

---

## 8. 生产核心词表 Schema

核心词表文件：

```text
fragment_vocab_v1.0.jsonl
```

每行一个 fragment rule。只保留生产匹配必需字段：

```text
fragment_id
fragment_name
version
category
parent_fragment_id
semantic_tags
match_rule
atom_roles
anchor_rule
ownership_rule
periodic_radius
allow_boundary_crossing
enable_cut_shift_scan
max_cut_shift
dedup_key_fields
overlap_policy
```

最小示例：

```json
{
  "fragment_id": "FG_AMIDE",
  "fragment_name": "amide",
  "version": "v1.0",
  "category": "functional_group",
  "parent_fragment_id": null,
  "semantic_tags": [
    "polar",
    "hydrogen_bonding",
    "rigidifying",
    "backbone_possible"
  ],
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3:1][CX3:2](=[OX1:3])",
    "constraints": {
      "exclude": ["urea", "imide_if_more_specific"]
    }
  },
  "atom_roles": {
    "1": "amide_nitrogen",
    "2": "carbonyl_carbon",
    "3": "carbonyl_oxygen"
  },
  "anchor_rule": {
    "anchor_type": "atom",
    "anchor_role": "carbonyl_carbon"
  },
  "ownership_rule": "anchor_in_RU0",
  "periodic_radius": 1,
  "allow_boundary_crossing": true,
  "enable_cut_shift_scan": true,
  "max_cut_shift": 1,
  "dedup_key_fields": [
    "fragment_id",
    "anchor_type",
    "anchor_role",
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern"
  ],
  "overlap_policy": {
    "exclusive_group": "carbonyl_family",
    "priority": 80,
    "allow_child_fragments": true
  }
}
```

以下字段不进入核心词表：

```text
display_name      -> UI/report 配置
source_smiles     -> fragment_vocab_v1.0.examples.jsonl
stats             -> fragment_vocab_v1.0.stats.json
review            -> review_report.json
embedding_policy  -> 下游模型配置
```

---

## 9. 辅助文件

统计文件：

```text
fragment_vocab_v1.0.stats.json
```

示例内容：

```json
{
  "FG_AMIDE": {
    "polymer_coverage_count": 4210,
    "polymer_coverage_ratio": 0.1769,
    "match_count": 5080,
    "anchor_success_ratio": 0.999,
    "cut_shift_stability": 0.992
  }
}
```

示例匹配文件：

```text
fragment_vocab_v1.0.examples.jsonl
```

审核文件：

```text
review_report.json
```

失败样本：

```text
fragment_vocab_v1.0.failed_cases.jsonl
```

验证报告：

```text
fragment_vocab_v1.0.validation_report.md
```

---

## 10. 验证标准

规则可执行性：

```text
rule_compile_success_rate = 100%
anchor_rule_defined_rate = 100%
invalid_rule_count = 0
```

覆盖率：

```text
seed-only draft: polymer_with_at_least_one_fragment >= 90% of valid E0/E1 graphs
seed + mined draft: polymer_with_at_least_one_fragment >= 95% of valid E0/E1 graphs
avg_fragment_types_per_polymer >= 3
avg_fragment_instances_per_polymer >= 4
```

稳定性：

```text
presence_label_consistency >= 0.99
instance_key_jaccard >= 0.95
false_added_neighbor_instance_rate <= 0.1%
duplicate_instance_rate <= 0.5%
boundary_ownership_accuracy >= 99%
```

冗余与冲突：

```text
输出 overlap_matrix
输出 high_overlap_pairs
输出 parent_child_candidates
输出 exclusive_group_conflicts
```

人工抽样：

```text
每类 fragment 至少 20 个实例
核心 fragment 总计 1000-3000 个实例
```

---

## 11. 构建流程

Phase 0：数据准备

```text
读取 all_polymers_experiment_final.csv
聚合 64,071 条属性记录为 unique polymer_string
按 record_type 标记 main_repeat_unit、monomer_or_descriptor_record、copolymer_candidate、ionomer_or_multicomponent_candidate、unresolved_R_group 等样本
过滤/标记 0、1、4 个连接点样本
过滤/标记 "."、","、"[R]"、"[R1]"、"[R2]" 等样本
统一 attachment 表示
生成 clean_polymer_strings_main.jsonl
```

Phase 1：标准化与构图

```text
生成 canonical_repeat_units.jsonl
生成 repeat_unit_graphs.jsonl
生成 graph_failed_cases.jsonl
生成 data_quality_report.md
```

Phase 2：Seed vocab v0

```text
人工定义 50-80 个 seed fragment rules
执行主数据匹配统计
修正 match_rule 和 anchor_rule
生成 seed_coverage_report.md
```

Phase 3：Motif mining

```text
在固定 pipeline 输出的主构建集上挖 3-6 atoms 高频 motif
过滤低频、低解释性、无 anchor 的候选
聚类合并
生成 mined_motif_candidates.jsonl
生成 motif_clusters.jsonl
```

Phase 4：Vocab draft

```text
合并 seed + accepted mined motifs
补齐生产核心 schema
补齐 overlap_policy
生成 fragment_vocab_v1_draft.jsonl
```

Phase 5：规则验证

```text
执行 V1-V4 验证
修正 unstable rules
移除低质量 fragments
生成 validation_report.md
```

Phase 6：冻结发布

```text
冻结 fragment_vocab_v1.0.jsonl
生成 stats/examples/review/failed_cases 辅助文件
记录版本号和数据 hash
```

---

## 12. 推荐目录结构

```text
data/
  raw/
    all_polymers_experiment_final.csv
  processed/
    clean_polymer_strings_main.jsonl
    property_records_by_polymer.jsonl
    canonical_repeat_units.jsonl
    repeat_unit_graphs.jsonl
    graph_failed_cases.jsonl
    data_quality_report.md

fragments/
  seeds/
    seed_fragment_rules_v0.jsonl
  mining/
    mined_motif_candidates.jsonl
    motif_clusters.jsonl
  vocab/
    fragment_vocab_v1.0.jsonl
    fragment_vocab_v1.0.stats.json
    fragment_vocab_v1.0.examples.jsonl
  validation/
    fragment_vocab_v1.0.validation_report.md
    review_report.json
    coverage_report.json
    stability_report.json
    overlap_report.json
    fragment_vocab_v1.0.failed_cases.jsonl
```

---

## 13. 冻结产物

最终发布必须包含：

```text
fragment_vocab_v1.0.jsonl
fragment_vocab_v1.0.stats.json
fragment_vocab_v1.0.examples.jsonl
fragment_vocab_v1.0.validation_report.md
fragment_vocab_v1.0.failed_cases.jsonl
review_report.json
```

`fragment_vocab_v1.0.jsonl` 是唯一生产核心规则文件；匹配器只能读取该文件作为规则来源。
