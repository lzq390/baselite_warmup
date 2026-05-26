# fragment_vocab_v1 词表验证完整流程

## 0. 文档定位

本文档定义 `fragment_vocab_v1` 构建完成后，如何验证它是否对当前内部主构建聚合物 / RU 数据可用，并进一步验证它是否能迁移到其它 RU 数据集。

本文档不讨论如何构建词表，只讨论词表构建出来之后如何验证。

当前数据前提：

```text
内部数据：固定版本预处理 pipeline 输出的 main_repeat_unit 数据集
当前 CSV 的临时 level 2 口径：12,184 个 attachment-normalized two-attachment main unique strings
外部数据：其它 RU 数据集，用于 zero-shot 可迁移性验证
```

注意：历史文档中的“内部主构建集”是近似口径，不得作为生产分母直接使用。验证报告必须写明 `dataset_id`、原始 CSV hash、预处理版本和 level 1-5 去重计数。

验证对象：

```text
fragment_vocab_v1_candidate.jsonl
```

目标输出：

```text
fragment_vocab_v1.validation_report.md
rule_validation_report.json
internal_coverage_report.json
internal_stability_report.json
anchor_validation_report.json
overlap_conflict_report.json
manual_audit_report.json
downstream_probe_report.json
external_ru_validation_report.json
failed_cases.jsonl
```

---

## 1. 验证总目标

词表可用不等于“能匹配出很多片段”。一个 fragment 词表只有同时满足下面条件，才可以认为可用：

```text
1. 规则本身可执行
2. 在内部主构建集数据上能稳定运行
3. 对内部主构建集数据有足够覆盖
4. 对不同 repeat unit 切分起点稳定
5. 跨边界片段归属正确
6. anchor 可稳定选择
7. canonical_instance_key 去重稳定
8. 冗余和冲突可控
9. 人工抽样审核正确率足够
10. Base-lite / Prop / attribution 下游任务不劣化
11. 对外部 RU 数据集具有可接受迁移能力
```

最终验收口径：

```text
核心 fragment 少而稳；
anchor 规则可靠；
切分起点不变；
内部主构建集可用；
外部 RU zero-shot 可迁移；
下游任务不劣化。
```

---

## 2. 验证输入与数据划分

### 2.1 输入文件

建议验证流程至少需要以下输入：

```text
fragment_vocab_v1_candidate.jsonl
internal_polymer_strings_main.jsonl
internal_repeat_unit_graphs_main.jsonl
external_ru_dataset_*.jsonl
```

其中 `fragment_vocab_v1_candidate.jsonl` 中每条规则至少包含：

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
    "backbone_possible"
  ],
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3:1][CX3:2](=[OX1:3])",
    "constraints": {}
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

### 2.2 内部数据划分

CSV 是 long-format 属性表，同一个 polymer string 会对应多条性质记录。所有验证划分必须在 unique polymer identity 层完成，禁止按 CSV row 切分。

推荐 split unit 优先级：

```text
1. primitive periodic graph hash
2. repeat_unit_graph canonical hash
3. canonical_repeat_unit_string
4. attachment-normalized polymer string
```

实际使用哪一级必须写入验证报告。如果 level 3-5 尚未生成，MVP 可临时使用 attachment-normalized polymer string，但必须在后续 graph hash 可用后重切分。

推荐划分比例：

```text
vocab_build_set: 70%
internal_validation_set: 15%
internal_stress_set: 15%
```

其中：

```text
vocab_build_set
```

用于构建和调试词表。

```text
internal_validation_set
```

用于正常覆盖率、匹配成功率、anchor 成功率验证。

```text
internal_stress_set
```

用于专门测试边界情况：

```text
跨 RU 边界片段
同一结构不同 repeat unit 切分
芳环 / 对称结构
同类型多实例
长柔性链段
低频结构
滑动窗口候选重复
```

如果数据量较紧，也可以采用：

```text
train/build: 80%
validation: 10%
stress: 10%
```

但必须保留独立 stress set。

必须执行泄漏检查：

```text
同一个 split unit 不能同时出现在 build / validation / stress。
同一个 raw smiles 的不同 attachment 写法不能跨 split。
同一个 canonical graph hash 的不同字符串写法不能跨 split。
```

### 2.3 外部 RU 数据集

外部 RU 数据集只用于验证迁移能力，不参与 `fragment_vocab_v1.0` 的规则调参。

外部验证必须是：

```text
freeze fragment_vocab_v1_candidate
-> zero-shot run on external RU datasets
-> 只评估，不修改
```

如果发现外部覆盖不足，应进入：

```text
fragment_vocab_v1.1_candidate_pool
```

而不是直接修改 v1.0。

---

## 3. 总体验证流程

完整流程如下：

```text
Phase 0: 验证环境准备
Phase 1: 规则可执行性验证
Phase 2: 内部主构建集匹配运行验证
Phase 3: 内部覆盖率验证
Phase 4: 周期稳定性与滑动窗口验证
Phase 5: anchor 可用性验证
Phase 6: canonical key 与去重验证
Phase 7: 冗余与冲突验证
Phase 8: 人工抽样审核
Phase 9: 下游任务可用性验证
Phase 10: 外部 RU zero-shot 验证
Phase 11: 失败样本归因与版本决策
```

---

## 4. Phase 0：验证环境准备

### 4.1 目标

确保验证流程中使用的 parser、标准化、构图、周期展开、匹配器、anchor selector、ownership rule 和 dedup key 生成器都已固定版本。

### 4.2 固定依赖

需要记录：

```text
polymer string parser version
canonicalization version
repeat_unit_graph builder version
fragment matcher version
periodic expansion version
registry version
fragment_vocab version
```

建议输出：

```json
{
  "pipeline_versions": {
    "parser": "polychem_parser_v0.3",
    "canonicalizer": "canonical_ru_v0.2",
    "graph_builder": "repeat_unit_graph_v0.4",
    "fragment_matcher": "fragment_matcher_v0.2",
    "fragment_vocab": "fragment_vocab_v1_candidate"
  }
}
```

### 4.3 检查 registry

验证开始前，需要加载并检查：

```text
MATCH_RULE_TYPE_REGISTRY
GRAPH_PATTERN_REGISTRY
ANCHOR_SELECTOR_REGISTRY
OWNERSHIP_RULE_REGISTRY
DEDUP_FIELD_REGISTRY
```

最低要求：

```text
所有词表中引用的 rule type、graph pattern、anchor type、ownership rule、dedup key field 都必须能在 registry 中找到。
```

---

## 5. Phase 1：规则可执行性验证

这一层验证的是：**词表规则本身是否写得正确，能不能被程序解析和执行。**

还不验证覆盖率。

### 5.1 JSON / schema 检查

每条 fragment rule 必须包含：

```text
fragment_id
fragment_name
version
category
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

逐行读取 `fragment_vocab_v1_candidate.jsonl`：

```python
required_fields = [
    "fragment_id",
    "fragment_name",
    "version",
    "category",
    "semantic_tags",
    "match_rule",
    "atom_roles",
    "anchor_rule",
    "ownership_rule",
    "periodic_radius",
    "allow_boundary_crossing",
    "enable_cut_shift_scan",
    "max_cut_shift",
    "dedup_key_fields",
    "overlap_policy"
]

for rule in vocab:
    for field in required_fields:
        if field not in rule:
            record_error(rule, "MISSING_FIELD", field)

    if "match_rule" in rule:
        for field in ["type", "pattern", "constraints"]:
            if field not in rule["match_rule"]:
                record_error(rule, "MISSING_FIELD", f"match_rule.{field}")

    if "anchor_rule" in rule:
        for field in ["anchor_type", "anchor_role"]:
            if field not in rule["anchor_rule"]:
                record_error(rule, "MISSING_FIELD", f"anchor_rule.{field}")

    if "overlap_policy" in rule:
        for field in ["exclusive_group", "priority", "allow_child_fragments"]:
            if field not in rule["overlap_policy"]:
                record_error(rule, "MISSING_FIELD", f"overlap_policy.{field}")
```

通过标准：

```text
missing required field = 0
invalid field type = 0
```

### 5.2 fragment_id 唯一性检查

正式词表中：

```text
fragment_id 必须唯一
```

例如 `FG_AMIDE` 只能出现一次。

```python
seen = set()

for rule in vocab:
    fid = rule["fragment_id"]
    if fid in seen:
        record_error(rule, "DUPLICATE_FRAGMENT_ID", fid)
    seen.add(fid)
```

如果有 amide 子类型，应使用不同 ID：

```text
FG_AMIDE
FG_AROMATIC_AMIDE
FG_BACKBONE_AMIDE
```

并通过 `parent_fragment_id` 记录层级关系。

通过标准：

```text
duplicate_fragment_id_count = 0
```

### 5.3 match_rule 可编译检查

`match_rule 可编译` 是指：

> 词表中的匹配规则能被匹配引擎解析成可执行查询对象。

如果是 SMARTS：

```json
{
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3:1][CX3:2](=[OX1:3])"
  }
}
```

则检查 SMARTS 能否被 RDKit 等工具解析。

如果是 graph pattern：

```json
{
  "match_rule": {
    "type": "graph_pattern",
    "pattern": "six_member_aromatic_ring"
  }
}
```

则检查该 pattern 是否在 `GRAPH_PATTERN_REGISTRY` 中注册。

SMARTS 编译伪代码：

```python
from rdkit import Chem

pattern = rule["match_rule"]["pattern"]
query = Chem.MolFromSmarts(pattern)

if query is None:
    record_error(rule, "MATCH_RULE_COMPILE_FAILED", pattern)

if query.GetNumAtoms() == 0:
    record_error(rule, "MATCH_RULE_EMPTY_QUERY", pattern)
```

编译成功示例：

```text
[NX3:1][CX3:2](=[OX1:3])
```

可以解析为：

```text
N-C(=O)
```

编译失败示例：

```text
[NX3:1][CX3:2](=[OX1:3]
```

少了右括号，应报错：

```text
MATCH_RULE_COMPILE_FAILED
```

graph_pattern 检查：

```python
GRAPH_PATTERN_REGISTRY = {
    "six_member_aromatic_ring": match_six_member_aromatic_ring,
    "fused_aromatic_ring": match_fused_aromatic_ring,
    "phenylene_linker": match_phenylene_linker
}

pattern_name = rule["match_rule"]["pattern"]

if pattern_name not in GRAPH_PATTERN_REGISTRY:
    record_error(rule, "UNKNOWN_GRAPH_PATTERN", pattern_name)
```

通过标准：

```text
match_rule_compile_success_rate = 100%
unknown_graph_pattern_count = 0
empty_query_count = 0
```

### 5.4 positive / negative 单元测试

有些规则可以编译，但语义可能写错。例如 amide rule 不应该匹配 ester。

每条核心规则需要提供测试样例：

```json
{
  "fragment_id": "FG_AMIDE",
  "positive_examples": [
    "CC(=O)NC",
    "O=C(NC)c1ccccc1"
  ],
  "negative_examples": [
    "CC(=O)OC",
    "CC(=O)C",
    "COC"
  ]
}
```

操作：

```python
for smi in rule["positive_examples"]:
    mol = Chem.MolFromSmiles(smi)
    matches = mol.GetSubstructMatches(query)
    if len(matches) == 0:
        record_error(rule, "POSITIVE_EXAMPLE_NOT_MATCHED", smi)

for smi in rule["negative_examples"]:
    mol = Chem.MolFromSmiles(smi)
    matches = mol.GetSubstructMatches(query)
    if len(matches) > 0:
        record_error(rule, "NEGATIVE_EXAMPLE_MATCHED", smi)
```

通过标准：

```text
positive_example_match_rate = 100%
negative_example_reject_rate = 100%
```

### 5.5 atom_roles 完整性检查

如果 SMARTS 使用 atom map number：

```text
[NX3:1][CX3:2](=[OX1:3])
```

则 `atom_roles` 必须覆盖这些 map number：

```json
{
  "1": "amide_nitrogen",
  "2": "carbonyl_carbon",
  "3": "carbonyl_oxygen"
}
```

检查：

```text
1. atom_roles 中的 map_id 是否存在于 SMARTS
2. SMARTS 中的关键 map_id 是否都有 role
3. anchor_rule 引用的 anchor_role 是否存在于 atom_roles
```

常见错误：

```json
{
  "atom_roles": {
    "1": "amide_nitrogen",
    "2": "carbonyl_carbon"
  },
  "anchor_rule": {
    "anchor_type": "atom",
    "anchor_role": "carbonyl_oxygen"
  }
}
```

错误原因：

```text
anchor_role = carbonyl_oxygen
但 atom_roles 中没有 carbonyl_oxygen
```

报错：

```text
ANCHOR_ROLE_NOT_IN_ATOM_ROLES
```

通过标准：

```text
atom_roles_valid_rate = 100%
anchor_role_resolvable_rate = 100%
```

### 5.6 anchor_rule 可执行检查

检查每个 match 是否能选出唯一 anchor。

例如 amide：

```json
{
  "anchor_rule": {
    "anchor_type": "atom",
    "anchor_role": "carbonyl_carbon"
  }
}
```

对匹配结果：

```text
N-C(=O)
```

应选出：

```text
carbonyl carbon
```

作为 anchor。

操作：

```python
matches = run_match(rule, positive_example)

for match in matches:
    anchor = select_anchor(match, rule["anchor_rule"], rule["atom_roles"])

    if anchor is None:
        record_error(rule, "ANCHOR_NOT_FOUND")

    if is_ambiguous(anchor):
        record_error(rule, "ANCHOR_NOT_UNIQUE")
```

支持的 `anchor_type` 至少包括：

```text
atom
bond
ring
atom_set
```

必须在 `ANCHOR_SELECTOR_REGISTRY` 中注册。

通过标准：

```text
anchor_success_on_unit_examples = 100%
anchor_ambiguity_count = 0
```

### 5.7 ownership_rule 合法性检查

当前推荐 ownership rule：

```text
anchor_in_RU0
```

含义：

```text
anchor 在 RU0 -> 保留
anchor 在 RU-1 / RU+1 -> 丢弃
```

检查 ownership rule 是否在 registry 中：

```python
OWNERSHIP_RULE_REGISTRY = {
    "anchor_in_RU0": owner_anchor_in_RU0,
    "representative_anchor_in_RU0": owner_representative_anchor_in_RU0
}

if rule["ownership_rule"] not in OWNERSHIP_RULE_REGISTRY:
    record_error(rule, "UNKNOWN_OWNERSHIP_RULE")
```

最小行为测试：

```text
case A: anchor.unit_offset = 0 -> accept
case B: anchor.unit_offset = +1 -> reject
case C: anchor.unit_offset = -1 -> reject
```

通过标准：

```text
ownership_rule_known_rate = 100%
ownership_behavior_test_pass = 100%
```

### 5.8 periodic_radius 合法性检查

`periodic_radius` 表示匹配时左右展开多少个 RU：

```text
0: 只看 RU0
1: RU[-1] + RU0 + RU[+1]
2: RU[-2] + RU[-1] + RU0 + RU[+1] + RU[+2]
```

检查规则：

```python
r = rule["periodic_radius"]

if not isinstance(r, int):
    record_error(rule, "PERIODIC_RADIUS_NOT_INT")

if r < 0:
    record_error(rule, "PERIODIC_RADIUS_NEGATIVE")

if r > MAX_PERIODIC_RADIUS:
    record_error(rule, "PERIODIC_RADIUS_TOO_LARGE")

if rule["allow_boundary_crossing"] and r == 0:
    record_error(rule, "BOUNDARY_CROSSING_REQUIRES_RADIUS_GE_1")
```

MVP 推荐：

```text
MAX_PERIODIC_RADIUS = 2
大部分 fragment periodic_radius = 1
```

通过标准：

```text
periodic_radius_valid_rate = 100%
```

### 5.9 boundary 设置一致性检查

`allow_boundary_crossing` 必须是 boolean。

如果：

```text
allow_boundary_crossing = true
```

则通常要求：

```text
periodic_radius >= 1
```

否则无法看见跨边界完整片段。

错误示例：

```json
{
  "fragment_name": "amide",
  "periodic_radius": 0,
  "allow_boundary_crossing": true
}
```

报错：

```text
BOUNDARY_CROSSING_REQUIRES_RADIUS_GE_1
```

通过标准：

```text
boundary_setting_valid_rate = 100%
```

### 5.10 dedup_key_fields 可生成检查

`dedup_key_fields` 定义如何生成 `canonical_instance_key`。

示例：

```json
{
  "dedup_key_fields": [
    "fragment_id",
    "anchor_type",
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern"
  ]
}
```

这些字段必须在 `DEDUP_FIELD_REGISTRY` 中注册。

操作：

```python
SUPPORTED_DEDUP_FIELDS = {
    "fragment_id",
    "anchor_type",
    "anchor_role",
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern",
    "local_context_signature"
}

for field in rule["dedup_key_fields"]:
    if field not in SUPPORTED_DEDUP_FIELDS:
        record_error(rule, "UNKNOWN_DEDUP_KEY_FIELD", field)
```

对 positive example 生成两次 key：

```python
key1 = build_canonical_instance_key(match, rule)
key2 = build_canonical_instance_key(match, rule)

if key1 != key2:
    record_error(rule, "CANONICAL_KEY_NOT_DETERMINISTIC")

if key1 is None or key1 == "":
    record_error(rule, "CANONICAL_KEY_EMPTY")
```

通过标准：

```text
dedup_key_fields_valid_rate = 100%
canonical_key_generation_success_rate = 100%
canonical_key_deterministic_rate = 100%
```

### 5.11 Phase 1 输出

生成：

```text
rule_validation_report.json
invalid_fragment_rules.jsonl
```

报告摘要示例：

```json
{
  "summary": {
    "total_rules": 72,
    "passed_rules": 72,
    "failed_rules": 0,
    "rule_compile_success_rate": 1.0,
    "anchor_rule_defined_rate": 1.0,
    "dedup_key_valid_rate": 1.0
  }
}
```

Phase 1 通过标准：

```text
所有核心指标必须为 100%
任何 failed rule 都不能进入后续验证
```

---

## 6. Phase 2：内部主构建集匹配运行验证

这一层验证的是：**词表能不能在内部主构建集的 repeat_unit_graph 上稳定跑完。**

### 6.1 具体操作

对所有有效 graph 执行：

```text
repeat_unit_graph
-> centered periodic expansion
-> fragment matching
-> anchor selection
-> ownership check
-> canonical key generation
-> dedup
-> fragment_instances
```

伪代码：

```python
for graph in internal_repeat_unit_graphs:
    try:
        result = match_fragments_for_repeat_unit(graph, fragment_vocab)
        save_result(result)
    except Exception as e:
        record_failed_case(graph, error=e)
```

### 6.2 统计指标

```text
total_graph_count
valid_graph_count
match_success_count
match_failed_count
matcher_crash_count
avg_runtime_per_graph
p95_runtime_per_graph
failed_reason_distribution
```

失败原因必须分类：

```text
graph_missing_attachment
periodic_expansion_failed
subgraph_match_timeout
anchor_not_found
canonical_key_error
unknown_graph_pattern
invalid_valence
```

### 6.3 内部通过标准

```text
matcher_crash_count = 0
valid_graph_match_success_rate >= 99%
failed_cases 都有明确 reason
p95_runtime_per_graph 在工程可接受范围内
```

如果出现大量 timeout，需要检查：

```text
SMARTS 是否太泛
graph pattern 是否复杂
periodic_radius 是否过大
candidate matching 是否无剪枝
```

---

## 7. Phase 3：内部覆盖率验证

这一层验证的是：**当前词表能不能覆盖内部主构建集的主要结构。**

### 7.1 总覆盖率

统计：

```text
polymer_with_at_least_one_fragment_ratio
avg_fragment_types_per_polymer
avg_fragment_instances_per_polymer
median_fragment_types_per_polymer
median_fragment_instances_per_polymer
```

内部主构建集推荐标准：

```text
有效 E0/E1 graph 中 ≥90% 能匹配到至少 1 个 fragment
平均每个 polymer ≥2.5 个 fragment type
平均每个 polymer ≥3 个 fragment instance
```

如果数据中大量简单聚烯烃，可以放宽：

```text
avg_fragment_types_per_polymer >= 2
```

### 7.2 单 fragment 覆盖率

对每个 fragment 统计：

```text
polymer_coverage_count
polymer_coverage_ratio
match_count
avg_instances_per_matched_polymer
boundary_crossing_ratio
anchor_success_ratio
```

内部主构建集数据下推荐分级：

| 覆盖数 | 建议处理 |
|---:|---|
| ≥100 | 可进入核心词表，前提是语义清楚 |
| 20–99 | 可进入辅助词表，或作为重要化学先验保留 |
| 5–19 | 进入候选池，除非非常重要 |
| <5 | v1 不建议进入核心词表 |

注意：

```text
imide、sulfone、nitrile、fluorinated_group 等性质相关片段，即使 coverage 只有 20–99，也可以保留。
```

### 7.3 类别覆盖率

按 polymer class 或结构簇统计：

```text
polyamide
polyimide
polyester
polycarbonate
polyurethane
polyether
polyolefin
polystyrene-like
fluoropolymer
conjugated polymer
```

检查：

```text
不是只覆盖某几类聚合物
柔性链、芳香结构、含氟、含硫、含氮、共轭结构都有基本覆盖
```

### 7.4 Phase 3 输出

```text
internal_coverage_report.json
fragment_coverage_table.csv
coverage_by_polymer_class.csv
unmatched_internal_cases.jsonl
```

---

## 8. Phase 4：周期稳定性与滑动窗口验证

这一层验证的是：**同一个真实周期结构，换不同 repeat unit 切分方式后，fragment 匹配结果是否稳定。**

### 8.1 切分起点不变性测试

对同一 polymer 自动生成多个等价 RU 表示：

```text
RU form A
RU form B
RU form C
```

分别匹配：

```text
fragment_instances_A
fragment_instances_B
fragment_instances_C
```

比较：

```text
fragment_presence_labels
canonical_instance_key set
fragment_count_labels
```

指标：

```text
presence_label_consistency
canonical_instance_key_jaccard
fragment_count_consistency
```

其中：

```text
canonical_instance_key_jaccard = |keys_A ∩ keys_B| / |keys_A ∪ keys_B|
```

内部主构建集推荐标准：

```text
presence_label_consistency >= 0.98
canonical_instance_key_jaccard >= 0.90
fragment_count_consistency >= 0.90
```

正式版目标：

```text
presence_label_consistency >= 0.99
canonical_instance_key_jaccard >= 0.95
```

### 8.2 cut-shift 滑动窗口不误加测试

使用滑动窗口：

```text
以 RU0 为起点
单 RU 窗口向左滑
单 RU 窗口向右滑
每个窗口重新匹配 candidate
```

检查：

```text
anchor 不属于 RU0 的 candidate 不能进入最终 fragment_instances
同一个 RU0-owned instance 不能重复加入
```

指标：

```text
false_added_neighbor_instance_rate
duplicate_instance_rate
```

推荐标准：

```text
false_added_neighbor_instance_rate <= 0.2%
duplicate_instance_rate <= 1.0%
```

正式版目标：

```text
false_added_neighbor_instance_rate <= 0.1%
duplicate_instance_rate <= 0.5%
```

### 8.3 跨边界片段验证

构造或抽样：

```text
cross_left
cross_right
cross_both
```

判断规则：

```text
anchor 在 RU0 -> 应加入
anchor 不在 RU0 -> 应丢弃
```

指标：

```text
boundary_ownership_accuracy
```

推荐标准：

```text
boundary_ownership_accuracy >= 98%
```

正式版目标：

```text
boundary_ownership_accuracy >= 99%
```

### 8.4 Phase 4 输出

```text
internal_stability_report.json
cut_shift_validation_report.json
boundary_ownership_report.json
periodic_invariance_failed_cases.jsonl
```

---

## 9. Phase 5：anchor 可用性验证

这一层验证的是：**每个 fragment 的 anchor 是否能稳定、唯一、可归属。**

### 9.1 统计指标

对每个 fragment 统计：

```text
anchor_success_ratio
anchor_uniqueness_ratio
anchor_in_RU0_ratio
anchor_conflict_ratio
cut_shift_anchor_stability
```

解释：

```text
anchor_success_ratio: 匹配到 fragment 后能否选出 anchor
anchor_uniqueness_ratio: 每个 match 中 anchor 是否唯一
cut_shift_anchor_stability: 换切分点后 anchor 是否仍在等价位置
```

### 9.2 推荐标准

内部主构建集：

```text
anchor_success_ratio >= 0.99
anchor_uniqueness_ratio >= 0.98
cut_shift_anchor_stability >= 0.95
```

如果某 fragment 不达标：

```text
修改 anchor_rule
改用 bond anchor
改用 ring anchor
改用 composite anchor
降级到 auxiliary vocab
从核心词表移除
```

### 9.3 Phase 5 输出

```text
anchor_validation_report.json
anchor_unstable_fragments.jsonl
anchor_failed_cases.jsonl
```

---

## 10. Phase 6：canonical key 与去重验证

这一层验证的是：**同一个片段不会重复加入，不同片段不会被错误合并。**

### 10.1 检查内容

统计：

```text
duplicate_instance_rate
canonical_key_collision_rate
same_match_key_determinism
equivalent_cut_key_consistency
```

### 10.2 具体操作

同一 match 重复生成 key：

```python
key1 = build_key(match)
key2 = build_key(match)

assert key1 == key2
```

如果同一个 RU0-owned instance 被 centered expansion 和 sliding scan 都发现：

```text
canonical_instance_key 必须相同
```

否则说明去重失败。

同一 RU0 中两个 amide：

```text
amide_A anchor = RU0_atom_3
amide_B anchor = RU0_atom_9
```

应该生成不同 key。

### 10.3 推荐标准

```text
duplicate_instance_rate <= 1.0%
canonical_key_collision_rate <= 0.1%
same_match_key_determinism = 100%
```

### 10.4 Phase 6 输出

```text
dedup_key_validation_report.json
duplicate_instance_cases.jsonl
key_collision_cases.jsonl
```

---

## 11. Phase 7：冗余与冲突验证

这一层验证的是：**词表中是否存在大量语义重复、父子重叠或互斥冲突。**

### 11.1 overlap matrix

统计 fragment instance 之间的 atom overlap。

重点检查：

```text
amide vs carbonyl
ester vs carbonyl
carbonate vs carbonyl
aromatic_ring vs phenylene
ether vs aromatic_ether
alkyl_linker vs flexible_chain
```

### 11.2 冗余判定

如果两个 fragment：

```text
经常同时出现
匹配 atom set 高度重叠
语义相近
anchor 相近
```

则可能冗余。

建议阈值：

```text
co_occurrence_ratio >= 0.95
avg_atom_overlap >= 0.8
```

### 11.3 处理策略

```text
同义片段 -> 合并
父子片段 -> 保留层级关系
低价值重复片段 -> 移到 auxiliary
互斥片段 -> 设置 exclusive_group + priority
```

不要简单删除所有子片段。

例如：

```text
amide 包含 carbonyl
ester 包含 carbonyl
```

但 carbonyl 在 ketone、aldehyde、acid 中仍有独立意义，所以可作为 child fragment 保留。

### 11.4 Phase 7 输出

```text
overlap_conflict_report.json
high_overlap_pairs.csv
redundant_fragment_candidates.jsonl
parent_child_fragment_candidates.jsonl
```

---

## 12. Phase 8：人工抽样审核

自动指标不够，必须看真实匹配结果。

### 12.1 抽样策略

建议抽样：

```text
每个核心 fragment 至少 10–20 个实例
高频 fragment 至少 30–50 个实例
跨边界 fragment 至少 100 个实例
同类型多实例样本至少 50 个
总审核量 500–1500 个 fragment instance
```

### 12.2 审核字段

每个抽样实例检查：

```text
match_rule 是否匹配到了正确化学片段
anchor 是否合理
owner_unit 是否正确
boundary_pattern 是否正确
canonical key 是否稳定
是否适合解释输出
```

### 12.3 审核标签

```text
correct
wrong_match
wrong_anchor
wrong_owner
duplicate
too_generic
too_specific
not_interpretable
```

### 12.4 通过标准

```text
core fragment 人工正确率 >= 95%
跨边界 fragment 人工正确率 >= 90%
wrong_owner 严重错误数量接近 0
```

### 12.5 Phase 8 输出

```text
manual_audit_report.json
manual_audit_samples.jsonl
manual_audit_failed_cases.jsonl
```

---

## 13. Phase 9：下游任务可用性验证

这一层验证的是：**词表能否被模型利用，至少不能让下游任务变差。**

### 13.1 Base-lite fragment presence probe

用 `fragment_vocab_v1` 生成：

```text
fragment_presence_labels
fragment_instances
```

训练一个轻量 probe：

```text
graph/text/fused representation -> multi-label fragment presence
```

指标：

```text
micro F1
macro F1
per-fragment precision
per-fragment recall
rare fragment recall
loss convergence speed
```

推荐标准：

```text
micro F1 >= 0.90
macro F1 >= 0.75
高频 fragment F1 >= 0.95
loss 正常收敛
```

如果学不动，可能说明：

```text
词表过细
标签噪声大
fragment 定义不一致
anchor / key 不稳定
图 encoder 输入特征不足
```

### 13.2 fragment embedding 稳定性验证

对同一个 polymer 的不同 RU 切法：

```text
RU form A
RU form B
```

匹配相同 canonical fragment instance，经过 graph encoder + fragment pooling，比较 embedding：

```text
cosine(frag_embedding_A, frag_embedding_B)
```

推荐标准：

```text
same_instance_embedding_cosine >= 0.90
```

### 13.3 Prop-MVP 小样本 ablation

比较：

```text
Model A: no fragment tokens
Model B: with fragment tokens / fragment pooling
```

指标：

```text
MAE
RMSE
R2
训练稳定性
验证集泛化
```

通过标准：

```text
with fragment tokens 不显著变差
最好在 Tg / RI / density / dielectric 至少部分性质上提升
```

### 13.4 Attribution sanity check

用 Prop-MVP 对代表性样本执行：

```text
mask one fragment
-> 重新预测
-> 计算 delta
```

人工检查方向是否基本合理：

```text
rigid aromatic / imide / amide 对 Tg 的贡献通常应有合理趋势
aromatic ring / sulfur-containing group 对 RI 的贡献通常应有合理趋势
polar group / nitrile / carbonyl / sulfone 对 dielectric 的影响应可解释
```

注意：这不是强监督，只是 sanity check。

### 13.5 Phase 9 输出

```text
downstream_probe_report.json
base_lite_presence_probe_report.json
fragment_embedding_stability_report.json
prop_ablation_report.json
attribution_sanity_report.json
```

---

## 14. Phase 10：外部 RU zero-shot 验证

这一层验证的是：**由内部主构建集构建的词表，能否迁移到其它 RU 数据集。**

### 14.1 基本原则

外部验证必须冻结词表：

```text
不修改 fragment_vocab
不根据外部结果临时调规则
直接 zero-shot 跑 external RU dataset
```

### 14.2 外部数据预处理统计

外部数据可能有不同表示方式：

```text
[*]...[*]
[*:1]...[*:2]
BigSMILES-like
端基显式
连接点缺失
多组分混合
copolymer 表示
```

所以要先分开统计：

```text
external_parse_success_rate
external_standardization_success_rate
external_graph_success_rate
external_vocab_match_success_rate
```

要区分失败来源：

```text
parser / standardization 失败
graph construction 失败
vocab matching 失败
```

只有第三类才主要归因于词表。

### 14.3 外部验证指标

对外部有效 graph 统计：

```text
valid_graph_coverage
avg_fragment_types_per_polymer
avg_fragment_instances_per_polymer
per-fragment coverage drift
anchor_success_ratio
boundary_ownership_accuracy
duplicate_instance_rate
unmatched_polymer_ratio
unknown_motif_rate
```

推荐标准：

```text
external valid graph 中 ≥80% 能匹配到至少 1 个 fragment
avg_fragment_types_per_polymer 不低于内部数据的 60%–70%
anchor_success_ratio >= 0.98
duplicate_instance_rate <= 1.5%
```

如果外部数据和内部分布很接近，可以要求：

```text
external coverage >= 90%
```

如果外部分布明显不同，可以接受：

```text
coverage >= 75%
```

但必须记录缺口。

### 14.4 外部结果分级

#### Green：可直接使用

满足：

```text
valid graph coverage >= 85%–90%
anchor_success_ratio >= 0.98
duplicate_instance_rate <= 1%
unmatched cases 有合理解释
```

结论：

```text
fragment_vocab_v1 可迁移到该外部 RU 数据集
```

#### Yellow：可用但需要扩展

表现：

```text
coverage 70%–85%
anchor 稳定
unknown motif 较多
某些聚合物类别覆盖弱
```

结论：

```text
fragment_vocab_v1 可作为基础版使用
需要构建 fragment_vocab_v1.1 candidate pool
```

#### Red：不可直接使用

表现：

```text
coverage <70%
anchor_success_ratio 明显下降
大量构图失败
大量重复或误归属
```

结论：

```text
当前词表不适合该外部 RU 数据集
```

### 14.5 external unknown motif 分析

对外部未覆盖结构做 mining：

```text
unmatched_subgraph_candidates
uncovered_polymer_classes
high_frequency_external_motifs
external_only_motif_clusters
```

注意：

```text
不要直接加入 v1.0
```

应进入：

```text
fragment_vocab_v1.1_candidate_pool
```

再经过同样验证流程。

### 14.6 Phase 10 输出

```text
external_ru_validation_report.json
external_dataset_quality_report.json
external_unmatched_cases.jsonl
external_unknown_motif_candidates.jsonl
external_distribution_shift_report.json
```

---

## 15. Phase 11：失败样本归因与版本决策

### 15.1 失败类型归因

所有失败样本统一归类：

```text
PARSER_FAILED
STANDARDIZATION_FAILED
GRAPH_CONSTRUCTION_FAILED
PERIODIC_EXPANSION_FAILED
MATCH_RULE_FAILED
ANCHOR_NOT_FOUND
ANCHOR_NOT_UNIQUE
WRONG_OWNER
CANONICAL_KEY_ERROR
DUPLICATE_INSTANCE
NO_FRAGMENT_MATCHED
SUBGRAPH_MATCH_TIMEOUT
```

### 15.2 常见问题与处理

#### 覆盖率低

处理：

```text
增加 seed rules
从 unmatched motif 中补充高频片段
检查标准化和构图失败率
```

#### 切分起点不稳定

处理：

```text
增大 periodic_radius
修正 anchor_rule
引入 composite anchor
修正 canonical_instance_key
增加 primitive periodic cell reduction
```

#### 重复实例多

处理：

```text
强化 canonical_instance_key
加入 atom_role_pattern
加入 boundary_pattern
加入 local_context_signature
```

#### 邻居 RU 片段被误加

处理：

```text
严格执行 anchor_in_RU0
sliding window 结果必须映射回原始 periodic coordinate
不能用 shifted window 的局部编号判断归属
```

#### Base-lite probe 学不动

处理：

```text
删掉低频 fragment
合并过细 fragment
剔除 anchor 不稳定 fragment
减少核心词表规模
```

#### Prop 加 fragment 后变差

处理：

```text
减少 fragment token 数量
只保留核心 fragments
降低 fragment 分支权重
改用 gated fusion
只在 graph memory 中保留 top-k fragment tokens
```

---

## 16. 验收标准总表

| 验证层级 | 指标 | 内部主构建集建议标准 | 外部 RU 建议标准 |
|---|---:|---:|---:|
| 规则 | rule compile success | 100% | 100% |
| 规则 | anchor_rule_defined | 100% | 100% |
| 运行 | matcher crash rate | 0 | 0 |
| 覆盖 | ≥1 fragment coverage | ≥90% | ≥80% |
| 覆盖 | avg fragment types/polymer | ≥2.5 | 不低于内部 60%–70% |
| 覆盖 | avg fragment instances/polymer | ≥3 | 不低于内部 60%–70% |
| 稳定 | presence consistency | ≥0.98 | ≥0.95 |
| 稳定 | instance key Jaccard | ≥0.90 | ≥0.85 |
| 边界 | boundary ownership accuracy | ≥98% | ≥95% |
| 去重 | duplicate instance rate | ≤1% | ≤1.5% |
| 误加 | false neighbor added rate | ≤0.2% | ≤0.5% |
| anchor | anchor success | ≥0.99 | ≥0.98 |
| 人工审核 | core fragment correctness | ≥95% | 抽样 ≥90% |
| 下游 | Base-lite presence probe | 可收敛 | 可选 |
| 下游 | Prop ablation | 不劣化 | 可选 |

---

## 17. 发布决策

### 17.1 可以发布为 fragment_vocab_v1.0

满足：

```text
内部主构建集验证通过
外部 RU 至少达到 Green 或较强 Yellow
人工审核通过
下游 probe 不劣化
```

发布名：

```text
fragment_vocab_v1.0
```

### 17.2 只能发布为 internal vocab

如果：

```text
内部主构建集通过
外部 RU 表现弱或未验证
```

建议命名：

```text
fragment_vocab_v0.9_internal_mainset
```

不要宣称为通用词表。

### 17.3 需要进入 v1.1 扩展

如果外部验证为 Yellow：

```text
保留 v1.0
建立 fragment_vocab_v1.1_candidate_pool
对 external unknown motifs 做补充和再验证
```

### 17.4 不应发布

如果出现：

```text
核心 rule 编译失败
anchor 大量失败
切分起点不稳定
外部或内部大量误归属
Base-lite / Prop 明显变差
```

则不发布，退回词表构建阶段。

---

## 18. 最终验证报告结构

最终 `fragment_vocab_v1.validation_report.md` 建议包含：

```text
1. 验证对象与版本信息
2. 内部主构建集数据概况
3. 外部 RU 数据概况
4. Phase 1 规则可执行性结果
5. Phase 2 内部匹配运行结果
6. Phase 3 内部覆盖率结果
7. Phase 4 周期稳定性与滑动窗口结果
8. Phase 5 anchor 可用性结果
9. Phase 6 canonical key 与去重结果
10. Phase 7 冗余与冲突分析
11. Phase 8 人工抽样审核结果
12. Phase 9 下游任务验证结果
13. Phase 10 外部 RU zero-shot 验证结果
14. 失败样本归因
15. 是否允许发布 v1.0
16. v1.1 扩展建议
```

---

## 19. 最终结论

当前只有内部主构建集数据时，词表验证不应追求“覆盖所有化学空间”，而应确认：

```text
对内部主构建集：
稳定、可解释、可复现、下游不劣化。

对外部 RU：
zero-shot 有基本覆盖，anchor 和归属不崩，能发现未覆盖 motif 缺口。
```

一个合格的 `fragment_vocab_v1` 应满足：

```text
规则可执行
内部覆盖足够
切分起点稳定
跨边界归属正确
anchor 稳定
canonical key 去重稳定
冗余可控
人工审核正确
下游 probe 可用
外部 RU 可迁移或至少能清楚暴露缺口
```
