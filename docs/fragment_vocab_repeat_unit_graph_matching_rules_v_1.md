# fragment_vocab_v1 与 repeat_unit_graph 的详细片段匹配规则

## 0. 文档定位

本文档定义的是：**已有 `fragment_vocab_v1` 如何在 `repeat_unit_graph` 上匹配出稳定的 `fragment_instances`**。

它不是“如何生成 fragment 词表”的文档。词表已经存在，本规则只负责：

```text
repeat_unit_graph + fragment_vocab_v1
-> fragment matching
-> fragment_instances
-> fragment_presence_labels
```

核心目标：

1. 同一个聚合物因为 repeat unit 切分起点不同，不应得到不同的片段实例。
2. 跨 RU 边界的片段要能完整匹配。
3. 滑动窗口只作为候选补充，不直接决定是否添加片段。
4. 最终只输出归属于中心重复单元 RU0 的片段实例。

最终推荐方案：

```text
centered periodic expansion
+ optional cut-shift sliding scan
+ fragment-specific anchor
+ anchor ownership check
+ canonical instance key dedup
```

最终判断公式：

```python
if owner(anchor) == "RU0" and canonical_instance_key not in seen:
    add()
else:
    discard()
```

---

## 1. 输入对象

## 1.1 repeat_unit_graph

`repeat_unit_graph` 是规则层从聚合物字符串生成的重复单元图。它至少需要包含：

```json
{
  "nodes": [
    {
      "atom_id": 0,
      "canonical_atom_id": 0,
      "element": "C",
      "aromatic": false,
      "formal_charge": 0,
      "hybridization": "sp2",
      "is_attachment": false,
      "attachment_role": null,
      "unit_offset": 0
    }
  ],
  "edges": [
    {
      "src": 0,
      "dst": 1,
      "bond_type": "single",
      "aromatic": false,
      "is_repeat_connection": false,
      "is_periodic_edge": false
    }
  ],
  "metadata": {
    "canonical_repeat_unit_string": "...",
    "left_attachment_atom": 0,
    "right_attachment_atom": 12,
    "primitive_reduction_status": "applied|not_applied|failed"
  }
}
```

其中：

```text
unit_offset = 0
```

表示中心重复单元 RU0。周期展开后会出现：

```text
RU[-1], RU[0], RU[+1]
```

即：

```text
unit_offset = -1, 0, +1
```

---

## 1.2 fragment_vocab_v1

每个 fragment 词表项不应只包含 `fragment_name + SMARTS`，而应包含匹配、角色、anchor、周期半径和去重规则。

推荐字段：

```json
{
  "fragment_id": "FG_AMIDE",
  "fragment_name": "amide",
  "match_rule": {
    "type": "smarts",
    "pattern": "[NX3][CX3](=O)"
  },
  "atom_roles": {
    "N": "amide_nitrogen",
    "C": "carbonyl_carbon",
    "O": "carbonyl_oxygen"
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
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern"
  ]
}
```

---

## 2. fragment type 与 fragment instance

必须区分两个层次。

## 2.1 fragment type

片段类型，例如：

```text
amide
ester
ether
aromatic_ring
imide
carbonate
urethane
sulfone
nitrile
```

`fragment_presence_labels` 只记录类型是否存在：

```json
{
  "amide": 1,
  "aromatic_ring": 1
}
```

同一种类型出现多次，presence 仍然是 1。

## 2.2 fragment instance

`fragment instance` 是具体片段实例。

例如一个 RU0 中可能有两个酰胺：

```text
amide_A
amide_B
```

它们类型相同，但 anchor 不同，atom set 不同，后续做 attribution 时可能需要分别 mask。

因此：

```text
fragment type 重复 ≠ fragment instance 重复
```

最终不能用 `fragment_name` 去重，必须用：

```text
canonical_instance_key
```

---

## 3. 总体匹配流程

完整流程如下：

```text
repeat_unit_graph
-> 输入检查
-> primitive periodic cell normalization, MVP 可暂不强制
-> 按 periodic_radius 构造 centered periodic expansion
-> 用 fragment_vocab_v1.match_rule 做子图匹配
-> 可选 cut-shift sliding scan 生成补充候选
-> 合并 centered candidates 与 sliding candidates
-> 对每个 candidate 选择 anchor
-> 判断 boundary_pattern
-> 判断 anchor 是否属于 RU0
-> canonicalize candidate
-> 生成 canonical_instance_key
-> 去重
-> 输出 fragment_instances 与 fragment_presence_labels
```

注意：

```text
centered expansion 和 sliding scan 产生的都只是 candidate。
真正决定是否输出的是 anchor ownership + canonical dedup。
```

---

## 4. Centered periodic expansion 主匹配

## 4.1 周期展开方式

对于每个 fragment rule，读取：

```text
periodic_radius = r
```

构造：

```text
RU[-r] + ... + RU[-1] + RU[0] + RU[+1] + ... + RU[+r]
```

常见配置：

```text
r = 0: 只看 RU0
r = 1: 3-mer, RU[-1] + RU0 + RU[+1]
r = 2: 5-mer, RU[-2] + RU[-1] + RU0 + RU[+1] + RU[+2]
```

MVP 默认：

```text
大多数局部官能团 periodic_radius = 1
```

也就是 3-mer。

## 4.2 为什么需要 centered expansion

很多重要片段可能跨越 repeat unit 边界。例如：

```text
amide = N-C(=O)
```

如果当前 repeat unit 切分刚好把 `N` 放在左侧邻居单元，把 `C=O` 放在 RU0 内，那么只看 RU0 会漏掉完整 amide。3-mer 展开后可以完整匹配。

## 4.3 周期展开图的原子标识

展开图中的每个原子必须有：

```text
canonical_atom_id
unit_offset
periodic_atom_id
```

例如：

```json
{
  "periodic_atom_id": "RU-1:atom_7",
  "canonical_atom_id": 7,
  "unit_offset": -1
}
```

同一个周期等价原子在不同 RU 中：

```text
RU[-1]:atom_7
RU[0]:atom_7
RU[+1]:atom_7
```

它们 `canonical_atom_id` 相同，但 `unit_offset` 不同。

---

## 5. Cut-shift sliding scan 补充匹配

## 5.1 滑动窗口的定位

你提出的滑动窗口是：

```text
以中间 RU0 为起点
窗口长度 = 单个 RU
向左一格一格滑动
向右一格一格滑动
每个窗口重新匹配片段
```

本方案保留这个思想，但它只能作为候选发现器。

它不能执行：

```text
发现新的 fragment type 就添加
```

而必须执行：

```text
发现 candidate
-> 映射回原始周期图坐标
-> anchor ownership check
-> canonical key dedup
-> 决定是否添加
```

## 5.2 sliding scan 的正式规则

每次滑动得到一个 shifted view：

```text
shift = -1, -2, ...
shift = +1, +2, ...
```

在 shifted view 中匹配得到 raw match 后，必须映射回原始周期坐标：

```text
shifted local atom id
-> periodic coordinate
-> canonical_atom_id + unit_offset relative to original RU0
```

然后和 centered expansion 得到的候选一起进入统一后处理。

## 5.3 滑动时遇到重复类型片段怎么办

判断表：

| 滑动时遇到的情况 | 是否加入 RU0 fragment_instances |
|---|---|
| 类型重复，anchor 在 RU+1 | 不加入 |
| 类型重复，anchor 在 RU-1 | 不加入 |
| 类型重复，anchor 在 RU0，但 canonical key 已存在 | 不加入 |
| 类型重复，anchor 在 RU0，canonical key 未出现 | 加入 |
| 类型新，anchor 在 RU0 | 加入 |
| 类型新，anchor 不在 RU0 | 不加入 |
| 跨两个 RU，anchor 在 RU0，key 新 | 加入 |
| 跨两个 RU，anchor 不在 RU0 | 不加入 |

核心原则：

```text
同类型不一定丢。
跨边界不一定加。
anchor 在 RU0 且 key 新，才加。
```

---

## 6. Anchor 规则

## 6.1 anchor 的作用

anchor 不是用来完整代表片段化学意义的。

anchor 只用于：

```text
片段归属
片段去重
片段实例身份定位
```

真正的 fragment embedding 应该来自：

```text
matched atom set 的 pooling
```

而不是只取 anchor atom embedding。

## 6.2 好 anchor 的标准

一个好的 anchor 应满足：

```text
唯一性
周期稳定性
化学语义强
归属清楚
对称情况下可 canonicalize
```

最重要的是：

```text
周期稳定性
```

即同一真实周期结构换一个 repeat unit 切分起点后，anchor 仍然落在等价位置。

## 6.3 推荐 anchor 类型

### 单原子语义 anchor

适合多数官能团：

| fragment | 推荐 anchor |
|---|---|
| amide | carbonyl carbon |
| ester | carbonyl carbon |
| carbonate | carbonyl carbon |
| urethane / carbamate | carbonyl carbon |
| urea | carbonyl carbon |
| ether | oxygen |
| thioether | sulfur |
| sulfone | sulfur |
| nitrile | nitrile carbon |
| hydroxyl | oxygen |
| amine | nitrogen |

### 键 anchor

适合键本身就是片段中心的情况：

```text
C=C
C≡C
periodic connection bond
backbone single-bond linker
```

表示：

```json
{
  "anchor_type": "bond",
  "anchor_atoms": ["atom_a", "atom_b"],
  "canonical_sort": true
}
```

### 环 anchor

适合芳环、脂环、杂环。

不能使用匹配器返回的第一个原子作为 anchor。

推荐：

```text
canonical_min_rank_atom_in_ring
```

fragment embedding 仍然来自整个 ring atom set。

### composite anchor

适合对称片段或多中心片段：

```text
imide
symmetric carbonate
phenylene linker
long conjugated segment
```

表示：

```json
{
  "anchor_type": "atom_set",
  "anchor_roles": ["carbonyl_carbon", "carbonyl_carbon"],
  "canonical_sort": true
}
```

---

## 7. Ownership 归属规则

## 7.1 单原子 anchor

如果：

```text
anchor.unit_offset == 0
```

则归属于 RU0。

否则丢弃。

## 7.2 键 anchor

键 anchor 由两个原子组成。

MVP 推荐规则：

```text
取 bond anchor 的 canonical representative。
如果 representative 在 RU0，则归属于 RU0。
否则丢弃。
```

canonical representative 可定义为：

```text
sorted(anchor_atoms by canonical rank)[0]
```

正式版可进一步定义 bond midpoint owner。

## 7.3 环 anchor

如果使用 representative atom：

```text
representative_anchor.unit_offset == 0
```

则归属于 RU0。

如果使用 ring tuple，则以 canonical ring representative 的 owner 为准。

## 7.4 composite anchor

MVP 推荐：

```text
composite anchor tuple 中 canonical rank 最小的 atom 作为 representative。
representative 在 RU0，则归属于 RU0。
```

正式版可以启用严格模式：

```text
composite anchor 的 canonical representative 归一后必须属于 RU0。
```

---

## 8. Boundary Pattern

每个 fragment instance 必须记录是否跨 RU 边界。

推荐枚举：

```text
internal
cross_left
cross_right
cross_both
multi_period
```

判断方式：

```python
unit_offsets = set(atom.unit_offset for atom in matched_atom_set)

if unit_offsets == {0}:
    boundary_pattern = "internal"
elif unit_offsets == {-1, 0}:
    boundary_pattern = "cross_left"
elif unit_offsets == {0, 1}:
    boundary_pattern = "cross_right"
elif min(unit_offsets) < 0 and max(unit_offsets) > 0:
    boundary_pattern = "cross_both"
else:
    boundary_pattern = "multi_period"
```

如果 rule 设置：

```text
allow_boundary_crossing = false
```

但候选的 `boundary_pattern != internal`，则丢弃。

---

## 9. canonical_instance_key

## 9.1 目标

`canonical_instance_key` 必须不依赖：

```text
匹配器返回顺序
原始 SMILES atom order
shifted window 局部编号
repeat unit 切分起点
```

## 9.2 推荐组成

```text
fragment_id
+ anchor_type
+ anchor_canonical_id_in_RU0
+ anchor_role
+ atom_role_pattern
+ boundary_pattern
+ local_context_signature
```

示例：

```text
FG_AMIDE|atom|carbonyl_C|RU0_atom_7|N-C(=O)|cross_left|ctx_abcd1234
```

MVP 可暂时不用 `local_context_signature`，但正式版建议加。

---

## 10. Overlap 处理规则

不同 fragment 可能共享原子，例如：

```text
amide 与 carbonyl
ester 与 carbonyl
aromatic_ring 与 phenylene_linker
```

MVP 默认：

```text
只去除 canonical_instance_key 完全重复的实例。
不因为普通 overlap 删除片段。
```

正式版可引入互斥组：

```json
{
  "exclusive_group": "carbonyl_family",
  "priority": 10
}
```

示例优先级：

```text
amide > carbonyl
ester > carbonyl
carbonate > carbonyl
urethane > carbonyl
```

---

## 11. 输出结构

## 11.1 fragment_instances

推荐输出：

```json
{
  "fragment_instances": [
    {
      "instance_id": "FI_000001",
      "fragment_id": "FG_AMIDE",
      "fragment_name": "amide",
      "matched_atoms_periodic": [
        {"canonical_atom_id": 4, "unit_offset": -1, "role": "amide_nitrogen"},
        {"canonical_atom_id": 5, "unit_offset": 0, "role": "carbonyl_carbon"},
        {"canonical_atom_id": 6, "unit_offset": 0, "role": "carbonyl_oxygen"}
      ],
      "matched_atoms_RU0_equivalent": [4, 5, 6],
      "anchor": {
        "anchor_type": "atom",
        "anchor_role": "carbonyl_carbon",
        "canonical_atom_id": 5,
        "unit_offset": 0
      },
      "owner_unit": "RU0",
      "boundary_pattern": "cross_left",
      "crosses_boundary": true,
      "canonical_instance_key": "FG_AMIDE|atom|carbonyl_C|RU0_atom_5|N-C(=O)|cross_left",
      "source": {
        "matched_by": "centered_expansion",
        "periodic_radius": 1,
        "shift_direction": null,
        "shift_steps": 0
      }
    }
  ]
}
```

## 11.2 fragment_presence_labels

从 instances 汇总得到：

```json
{
  "fragment_presence_labels": {
    "amide": 1,
    "aromatic_ring": 1,
    "ether": 0
  }
}
```

---

## 12. 推荐伪代码

```python
def match_fragments_for_repeat_unit(repeat_unit_graph, fragment_vocab):
    validate_repeat_unit_graph(repeat_unit_graph)
    validate_fragment_vocab(fragment_vocab)

    primitive_ru = reduce_to_primitive_periodic_cell(
        repeat_unit_graph,
        fallback_to_input=True
    )

    candidate_matches = []
    rules_by_radius = group_rules_by_periodic_radius(fragment_vocab)

    for radius, rules in rules_by_radius.items():
        expanded_graph = build_centered_periodic_expansion(primitive_ru, radius)
        for rule in rules:
            for match in subgraph_match(expanded_graph, rule.match_rule):
                match.source = {
                    "matched_by": "centered_expansion",
                    "periodic_radius": radius,
                    "shift_direction": None,
                    "shift_steps": 0
                }
                candidate_matches.append(match)

    for rule in fragment_vocab:
        if not rule.enable_cut_shift_scan:
            continue

        shifted_views = generate_cut_shift_views(
            primitive_ru,
            max_shift=rule.max_cut_shift,
            directions=["left", "right"]
        )

        for view in shifted_views:
            raw_matches = subgraph_match(view.graph, rule.match_rule)
            for raw_match in raw_matches:
                mapped_match = map_match_to_periodic_coordinates(
                    raw_match,
                    shifted_view=view,
                    reference_ru=primitive_ru
                )
                mapped_match.source = {
                    "matched_by": "cut_shift_scan",
                    "periodic_radius": rule.periodic_radius,
                    "shift_direction": view.direction,
                    "shift_steps": view.steps
                }
                candidate_matches.append(mapped_match)

    instances = []
    seen_keys = set()

    for match in candidate_matches:
        rule = get_rule_by_fragment_id(fragment_vocab, match.fragment_id)
        boundary_pattern = compute_boundary_pattern(match)

        if not rule.allow_boundary_crossing and boundary_pattern != "internal":
            continue

        anchor = select_anchor(match, rule.anchor_rule)
        if anchor is None:
            continue

        if not anchor_belongs_to_RU0(anchor):
            continue

        canonical_match = canonicalize_match(match, anchor, rule, primitive_ru)
        key = build_canonical_instance_key(canonical_match, anchor, rule, boundary_pattern)

        if key in seen_keys:
            continue

        seen_keys.add(key)
        instances.append(build_fragment_instance(canonical_match, anchor, rule, boundary_pattern, key))

    return {
        "fragment_instances": instances,
        "fragment_presence_labels": build_fragment_presence_labels(instances)
    }
```

---

## 13. MVP 版本规则

当前第一版建议采用 MVP：

```text
1. 输入 repeat_unit_graph，不强制 primitive reduction，但保留状态字段。
2. 默认 centered 3-mer expansion。
3. 大多数 local functional group 使用 periodic_radius = 1。
4. cut-shift scan 只对 allow_boundary_crossing = true 的 fragment 启用。
5. 所有候选必须经过 anchor_in_RU0 判断。
6. 去重只用 canonical_instance_key。
7. 默认不因普通 overlap 删除片段。
8. 输出 fragment_instances 与 fragment_presence_labels。
```

---

## 14. 测试规范

### 14.1 切分起点不变性测试

对同一周期结构构造多个等价 repeat unit：

```text
RU form A
RU form B
RU form C
```

分别抽取 fragment_instances。

要求：

```text
canonical_instance_key set 一致
```

### 14.2 滑动窗口不误加测试

对 RU0 左右滑动若干步。

要求：

```text
anchor 不属于 RU0 的 candidate 不能进入最终 fragment_instances
```

### 14.3 同类型多实例测试

构造一个 RU0 中有两个同类型片段的样本：

```text
amide_A
amide_B
```

要求：

```text
presence_label["amide"] = 1
fragment_instances 中有两个 amide instance
两个 canonical_instance_key 不同
```

### 14.4 跨边界测试

构造跨左边界和跨右边界的片段。

要求：

```text
anchor 在 RU0 -> 加入
anchor 不在 RU0 -> 丢弃
```

---

## 15. 对模型侧的影响

该匹配规则不改变当前模型主架构。

仍然是：

```text
polymer_string
-> repeat_unit_graph
-> fragment_vocab_v1 matching
-> fragment_instances
-> graph encoder
-> fragment pooling
-> graph memory
```

但模型侧需要注意：

```text
anchor 不是 fragment embedding
anchor 只是归属与去重 metadata
fragment embedding 来自整个 matched atom set pooling
```

推荐 fragment pooling：

```text
fragment_embedding
= MLP([
    mean(atom_embeddings[matched_atom_set]);
    max(atom_embeddings[matched_atom_set]);
    fragment_type_embedding;
    boundary_pattern_embedding;
    anchor_role_embedding
])
```

---

## 16. 最终推荐口径

当前项目的 `fragment_vocab_v1 -> repeat_unit_graph` 匹配规则建议定为：

```text
以 centered periodic expansion 为主匹配流程；
以 cut-shift sliding scan 作为候选补充；
所有候选统一通过 fragment-specific anchor 选择；
只保留 anchor 归属于 RU0 的候选；
用 canonical_instance_key 去重；
不按 fragment type 直接添加；
不按是否跨 RU 直接添加；
只添加新的 RU0-owned canonical fragment instance。
```

核心公式：

```python
if owner(anchor) == "RU0" and canonical_instance_key not in seen:
    add()
else:
    discard()
```

这套规则能同时处理：

```text
不同 repeat unit 切分起点
跨边界片段
同类型多实例
滑动窗口重复发现
邻居周期片段误加
后续 fragment attribution 稳定性
```

