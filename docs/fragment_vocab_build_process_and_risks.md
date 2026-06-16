# fragment 词表构建过程与风险说明

本文档说明四件事：

1. SMILES 如何从 64,071 条 CSV 记录聚合到 11,580 个唯一标准化 repeat-unit。
2. 两个词表构建脚本在第 5/6 两类问题上的状态和差异。
3. 第 5/6 两类问题的可行解决方案。
4. 词表构建过程中还可能出现的其它常见问题。

注：文中提到的 `fragment_construct.py` 是已从 `main` 移除的旧流程脚本，仅作为风险来源和设计对照，不再是当前可运行入口。

---

## 1. 从 64,071 条记录到 11,580 个唯一标准化 SMILES 的过程

原始数据文件：

```text
data/all_polymers_experiment_final.csv
```

原始 CSV 是 long-format 属性表：

```text
smiles, 性质分类, 性质名, 值, 单位
```

也就是说，同一个 polymer SMILES 可能因为有多个性质记录而出现多行。因此，不能直接把 CSV 行数当作 polymer 数量。

当前构建流程中的关键数量如下：

```text
CSV 总行数: 64,071
raw unique polymer strings: 23,956
两连接点 main repeat-unit raw candidates: 23,791
attachment-normalized main unique: 12,184
RDKit canonical repeat-unit unique: 11,580
repeat-unit graph hash unique: 11,439
```

### 1.1 CSV 行级记录 -> raw unique polymer strings

第一步是按原始 `smiles` 字符串聚合。

```text
64,071 CSV rows
-> 23,956 raw unique polymer strings
```

减少的原因不是删除结构，而是同一个 SMILES 在属性表中有多条性质记录。例如同一个 polymer 可以同时有：

```text
Tg
band gap chain
band gap bulk
crystallization tendency
```

如果按 CSV 行统计，会把“性质记录多”的 polymer 错误当成高频结构。词表构建必须先按 unique polymer string 聚合。

### 1.2 raw unique -> main repeat-unit candidates

对 23,956 个 raw unique string 做主构建准入判断。

当前 record type 统计为：

```text
main_repeat_unit: 23,791
monomer_or_descriptor_record: 105
copolymer_candidate: 47
incomplete_attachment: 6
ionomer_or_multicomponent_candidate: 5
unresolved_R_group: 2
```

所以：

```text
23,956 raw unique
- 165 non-main records
= 23,791 main repeat-unit raw candidates
```

不进入主构建集的典型情况：

```text
0 个 *: 小分子、单体、描述符记录
1 个 *: 连接点不完整
4 个 *: 共聚物或多 repeat-unit 候选
含 ".": 盐、离子配对、多组分形式
含 ",": 多 repeat-unit 拼接
含 [R] / [R1] / [R2]: 未定义 R 基
```

主构建集要求恰好有两个 attachment points，并且不含多组分、共聚物拼接和未定义 R 基。

### 1.3 main raw candidates -> attachment-normalized unique

第二步是统一 attachment 写法。

当前规则包括：

```text
[[[*]]] -> *
[[*]]   -> *
[*]     -> *
[*:1]   -> *
[*:2]   -> *
```

执行后：

```text
23,791 main repeat-unit raw candidates
-> 12,184 attachment-normalized main unique
```

这里合并了：

```text
23,791 - 12,184 = 11,607
```

这一步是数量下降最大的地方。原因是同一结构在数据中有多种 attachment 表示。

例如下面三条 raw SMILES 只是连接点写法不同：

```text
*/C(=C(/*)c1ccc(CCCC)cc1)c1ccccc1
[[*]]/C(=C(/[[*]])c1ccc(CCCC)cc1)c1ccccc1
[[[*]]]/C(=C(/[[[*]]])c1ccc(CCCC)cc1)c1ccccc1
```

attachment 统一后都变成：

```text
*/C(=C(/*)c1ccc(CCCC)cc1)c1ccccc1
```

这不是丢失结构，而是把文本表示不同但 attachment 语义相同的记录合并。

需要注意的是：

```text
[R] / [R1] / [R2]
```

不属于 attachment token，不能自动替换成 `*`。它们是未定义 R 基，应进入 `unresolved_R_group`。

### 1.4 attachment-normalized unique -> RDKit canonical repeat-unit unique

第三步使用 RDKit 对 attachment-normalized SMILES 做 canonicalization。

```text
12,184 attachment-normalized main unique
-> 11,580 RDKit canonical repeat-unit unique
```

这里继续合并了：

```text
12,184 - 11,580 = 604
```

原因是同一个化学图可以有多种合法 SMILES 写法。RDKit canonicalization 会把它们归一成同一个 canonical string。

例如：

```text
*O[Si](*)(C)C
*[Si](C)(C)O*
C[Si](C)(O*)*
```

canonical 后会归到同一个 repeat-unit。

另一个常见情况是芳香环、支链和环闭合编号的书写顺序不同，但分子图相同。

### 1.5 canonical repeat-unit unique -> graph hash unique

当前报告还生成了一个粗略 graph hash：

```text
11,580 canonical repeat-unit unique
-> 11,439 repeat-unit graph hash unique
```

但这个 `graph_hash` 目前只是基于 RDKit molecule 的 atom/bond signature 做的粗略 hash，不是严格的 canonical graph isomorphism hash。

因此：

```text
level 4 graph hash unique = 11,439
```

只能作为参考统计，不能作为最终生产去重依据。

### 1.6 当前流程还没有完成的 level 5

文档中规划的 level 5 是：

```text
primitive periodic graph hash
```

它需要真正的 periodic repeat-unit graph builder。当前脚本尚未实现 centered periodic expansion 和 primitive periodic reduction，所以：

```text
level_5_primitive_periodic_graph_hash_unique: 未实现
```

---

## 2. 两个脚本在第 5/6 两类问题上的状态

本节对比两个脚本：

```text
scripts/fragment_construct.py
scripts/build_fragment_vocab_v1.py
```

两个脚本的定位不同。

`fragment_construct.py` 的基本思路是：

1. 读取 base fragment SMARTS。
2. 在 CSV 的 SMILES 上做 substructure match。
3. 找到 pattern 中的 `[*]` wildcard。
4. 用真实匹配到的原子替换 `[*]`。
5. 生成新的 expanded fragment rules。

`build_fragment_vocab_v1.py` 的基本思路是：

1. 按当前主构建规则清洗原始 CSV。
2. 做 attachment normalization 和 RDKit canonical 去重。
3. 人工定义 atom-mapped seed rules。
4. 在 canonical repeat-unit molecule 上统计覆盖率。
5. 按频率阈值冻结核心词表，并输出统计、示例和验证报告。

因此，第 5/6 两点在两个脚本中的问题并不完全相同。

### 2.1 第 5 点：constraints / overlap 裁决没有完整解决

#### 2.1.1 constraints 是用来做什么的

`constraints` 是 SMARTS 主模式匹配之后的第二层过滤规则。

SMARTS 主 pattern 往往只能表达“长得像某类结构”，但不能完整表达所有排除逻辑。

例如 amide 的基础 pattern 可能类似：

```text
[*][NX3][CX3](=O)[*]
```

它可以匹配普通 amide，但也可能覆盖更具体的结构，例如：

```text
imide
urea
urethane
aromatic amide
```

这时就需要 constraints 来避免过匹配。

约束的主要用途包括：

1. 避免普通 fragment 吃掉更具体 fragment。
2. 处理互斥类别，例如 carbonyl / amide / ester / ketone。
3. 限定特殊化学条件，例如 trifluoromethyl 必须刚好有 3 个 F。
4. 排除无机盐、多组分或不属于目标语义的匹配。
5. 保证后续生成的新 fragment 语义干净。

#### 2.1.2 `fragment_construct.py` 的问题：写了 constraints，但大多数没有执行

`fragment_construct.py` 中的约束函数是：

```python
def pass_constraints(mol, fragment):
    constraints = fragment.get("match_rule", {}).get("constraints", {})
    not_smarts_list = constraints.get("not_smarts", [])

    for not_smarts in not_smarts_list:
        q = Chem.MolFromSmarts(not_smarts)
        if q is None:
            continue
        if mol.HasSubstructMatch(q):
            return False

    return True
```

它只读取：

```text
constraints.not_smarts
```

但 `fragments_core_v1/core_fragment_v1.json` 中实际存在多种 constraints 写法，例如：

```json
"constraints": {
  "exclude": [
    "carboxylic_acid",
    "ester_if_single_alkoxy",
    "anhydride_if_more_specific"
  ]
}
```

```json
"constraints": {
  "exact_fluorine_count": 3,
  "exclude_perfluoroalkyl_chain": true
}
```

```json
"constraints": {
  "exclude_inorganic_halides": true
}
```

```json
"constraints": {
  "exclude_methane": true
}
```

这些当前脚本全部不会执行。

所以 JSON 里看起来写了约束，但实际匹配时大多数约束没有参与过滤。

另外，脚本没有 constraint type registry 或 schema validator。也就是说，即使 JSON 中新增一个 constraint key，只要脚本没有显式处理，它就会被静默忽略，不会进入 invalid rule report。

#### 2.1.3 `fragment_construct.py` 中 `not_smarts` 的判断粒度也不对

当前逻辑是：

```python
if mol.HasSubstructMatch(q):
    return False
```

这表示：只要整个 molecule 里出现 forbidden SMARTS，就跳过这个 fragment 对整个 molecule 的所有匹配。

但合理粒度应该是：

```text
只排除当前 match instance
```

而不是排除整个 molecule。

举例：

一个 polymer 里可能同时有：

```text
一个合法普通 amide
一个 imide
```

如果 `not_smarts` 检测到 imide，当前脚本可能把这个 molecule 里的所有 amide 匹配都跳过，包括合法的普通 amide。

这会导致误杀。

#### 2.1.4 对词表质量的影响

如果 constraints 没有正确生效，会出现：

```text
普通 fragment 过匹配
更具体 fragment 被普通 fragment 混淆
expanded fragment 语义不干净
match_count 不可信
后续 priority / overlap_policy 难以补救
```

尤其对 carbonyl family、sulfur family、halogen family、ring family 影响较大。

#### 2.1.5 `build_fragment_vocab_v1.py` 的问题：没有假约束，但也没有实例级裁决

`build_fragment_vocab_v1.py` 避开了 `fragment_construct.py` 的一部分问题：

```text
核心词表中 match_rule.constraints 统一为 {}
```

因此它没有出现“JSON 里写了 constraints，但脚本悄悄忽略”的情况。

但是它仍然没有完整解决第 5 点，因为它没有真正执行：

```text
match-level constraints
overlap_policy.priority 裁决
parent-child fragment 裁决
exclusive_group 内互斥裁决
```

当前流程是对每条规则独立做 substructure match，再统计 coverage。`overlap_policy` 被写入核心词表，`overlap_report` 也会报告高重叠规则对，但这些策略没有用于过滤或合并实例。

这会导致：

```text
carbonyl / amide / ester / imide 同时命中同一区域
ether / aromatic_ether 同时命中
halogen / fluoro / trifluoromethyl 同时命中
ring / phenylene_linkage 同时命中
```

因此，`build_fragment_vocab_v1.py` 在第 5 点上的状态是：

```text
没有假装执行未实现的 constraints；
但仍缺少真正的 match-level overlap resolver。
```

### 2.2 第 6 点：RU 边缘 fragment 匹配没有被可靠解决

#### 2.2.1 RU 边缘问题是什么

RU 边缘问题指的是：

```text
某个 fragment 跨越 repeat unit 的左右边界。
```

例如一个 amide 可能被 RU 切分点切开：

```text
RU[-1] 的 N  --  RU0 的 C(=O)
```

如果只在单个 RU0 内匹配，就看不到完整的：

```text
N-C(=O)
```

因此需要边界处理。

#### 2.2.2 `fragment_construct.py` 的问题：试图做边界/邻接上下文扩展，但方法不可靠

`fragment_construct.py` 试图通过 `[*]` wildcard 捕获边界或邻接上下文。例如 base pattern：

```text
[*][NX3][CX3](=O)[*]
```

匹配后把 `[*]` 替换成真实原子，生成更具体的新 pattern。

需要特别注意：

```text
RDKit SMARTS 中的 [*] 默认匹配任意原子。
```

它不等价于 repeat-unit attachment dummy atom。只有当 `[*]` 恰好匹配到 attachment dummy atom 时，它才和 RU 边界有关。更多时候，它只是一个非常宽的 wildcard。

因此，这个脚本实际做的是：

```text
wildcard 位置的局部邻接上下文扩展
```

而不是严格的 RU 边界匹配。

##### 2.2.2.1 `atom_to_simple_smarts` 只保留了很少信息

当前函数：

```python
def atom_to_simple_smarts(atom):
    if atom.GetAtomicNum() == 0:
        return "[*]"

    symbol = atom.GetSymbol()

    if atom.GetIsAromatic():
        symbol = symbol.lower()

    charge = atom.GetFormalCharge()
    charge_text = ""

    ...

    return f"[{symbol}{charge_text}]"
```

它只保留：

```text
元素
芳香性
形式电荷
```

但会丢失：

```text
H 数
价态
degree
ring membership
hybridization
连接键类型
芳香键上下文
手性
同位素
dummy attachment role
```

因此真实匹配环境中的具体原子可能被简化成非常宽泛的：

```text
[C]
[N]
[O]
[c]
```

这会让新 SMARTS 规则匹配到很多不该匹配的结构。

##### 2.2.2.2 字符串替换无法可靠表达图结构

当前更新 pattern 的方式是：

```python
updated_pattern = re.sub(
    r"\[\*\]",
    lambda _: next(replacement_iter),
    pattern,
    count=len(replacements)
)
```

这是字符串替换，不是基于分子图重建 SMARTS。

它不知道真实连接中的 bond 是：

```text
single bond
double bond
aromatic bond
directional bond
ring bond
periodic edge
```

例如边界处真实结构可能是芳香连接，但替换后只得到：

```text
[*][c]
```

或者普通碳环境被简化成：

```text
[C][*]
```

这些都不能稳定表达原始图结构。

##### 2.2.2.3 它处理的是“局部上下文扩展”，不是周期图匹配

更关键的是：

`fragment_construct.py` 没有真正构造：

```text
RU[-1] + RU0 + RU[+1]
```

它只是用当前 SMILES 中的 wildcard 匹配结果生成新 SMARTS。

这种方法无法完整解决：

```text
anchor 是否属于 RU0
boundary_pattern 是 cross_left 还是 cross_right
cut-shift 后实例是否稳定
跨边界重复实例如何去重
```

所以它是一个边界启发式扩展，只用于词表构建候选生成；它不是当前 BaseLite 训练数据生成流程，也不是严格 periodic graph matcher。

#### 2.2.3 `build_fragment_vocab_v1.py` 的问题：避开了错误扩展，但没有处理边界匹配

`build_fragment_vocab_v1.py` 不做 `[*]` 字符串替换，也不会把某个匹配到的原子简化成 `[C]`、`[N]`、`[O]` 后写回新 SMARTS。

它的核心规则是人工定义的 atom-mapped SMARTS，例如：

```text
[NX3:1][CX3:2](=[OX1:3])
[CX3:1](=[OX1:2])[OX2:3]
```

因此它避开了 `fragment_construct.py` 中“扩展 SMARTS 丢化学信息”的问题。

但它没有真正处理 RU 边缘 fragment 匹配。

当前脚本只是记录 attachment atom：

```text
attachment_atom_ids
is_attachment
attachment_role
```

但 repeat-unit graph 中明确是：

```text
periodic_expansion: not_materialized
periodic_radius: 0
is_repeat_connection: false
is_periodic_edge: false
```

匹配阶段也只是对单个 canonical RDKit molecule 执行 substructure match：

```text
rec.mol.GetSubstructMatches(query)
```

它没有构造：

```text
RU[-1] + RU0 + RU[+1]
```

也没有添加跨 repeat-unit 的 periodic edge。

所以 `build_fragment_vocab_v1.py` 在第 6 点上的状态是：

```text
没有使用错误的 wildcard 字符串扩展；
但也没有实现真正的 periodic 3-mer boundary matcher。
```

---

## 3. 解决第 5/6 两类问题的可行方案

### 3.1 解决第 5 点：实现 match-level constraints 和 overlap resolver

#### 3.1.1 约束必须变成可执行规则

不要只在 JSON 中写自然语言式的：

```json
"exclude": ["amide_if_adjacent_N"]
```

除非脚本知道如何执行它。

建议把 constraints 分成两类：

```text
machine_executable_constraints
human_review_notes
```

机器可执行约束可以包括：

```json
{
  "not_smarts_overlap_anchor": ["[NX3][CX3](=O)[NX3]"],
  "not_smarts_overlap_match": ["[CX3](=O)[NX3][CX3](=O)"],
  "required_atom_count": {"F": 3},
  "forbid_atom_count_gt": {"F": 3},
  "anchor_neighbor_must_not_be": ["N", "O"],
  "match_must_be_internal": true
}
```

不能自动执行的说明放到：

```json
"review_notes": [
  "exclude ester_if_single_alkoxy after manual review"
]
```

避免 JSON 看起来有约束，但程序实际不执行。

同时需要建立 constraint type registry：

```text
constraint_type_registry:
  not_smarts_overlap_anchor
  not_smarts_overlap_match
  required_atom_count
  forbid_atom_count_gt
  anchor_neighbor_must_not_be
  match_must_be_internal
```

构建时必须校验：

```text
1. 所有 constraint key 都必须在 registry 中注册。
2. constraint value 类型必须符合 schema。
3. 遇到未知 constraint key 时 fail-fast，或写入 invalid_rule_report。
4. 不允许静默忽略未知约束。
```

这样可以避免再次出现“JSON 中写了规则，但脚本没有执行”的问题。

#### 3.1.2 constraints 应该作用于单个 match instance

推荐流程：

```text
for each molecule:
  for each rule:
    matches = mol.GetSubstructMatches(rule.pattern)
    for each match:
      if not pass_match_constraints(mol, match, rule):
        continue
      accept candidate instance
```

也就是说，约束函数签名应该从：

```python
pass_constraints(mol, fragment)
```

改成：

```python
pass_match_constraints(mol, match, query, fragment)
```

约束需要知道当前 match 的原子集合、anchor 原子和 role mapping。

#### 3.1.3 forbidden SMARTS 应该检查是否与当前 match 重叠

错误粒度：

```python
mol.HasSubstructMatch(forbidden_query)
```

合理粒度：

```text
for forbidden_match in mol.GetSubstructMatches(forbidden_query):
  if overlaps(forbidden_match, current_match):
    reject current_match
```

还可以进一步限定：

```text
overlap_anchor
overlap_any_matched_atom
contains_current_match
same_anchor
```

不同约束使用不同粒度。

#### 3.1.4 实现 overlap resolver

匹配后应先得到所有候选实例：

```text
candidate_instances
```

每个实例至少包含：

```text
fragment_id
matched_atoms
anchor
priority
exclusive_group
parent_fragment_id
allow_child_fragments
boundary_pattern
canonical_instance_key
```

然后按 `overlap_policy` 裁决：

```text
1. 同 exclusive_group 内按 priority 从高到低排序。
2. 如果两个实例 atom overlap 严重，保留高优先级。
3. 如果 parent-child 允许共存，则保留 child 和 parent 的 presence label，但 instance 可以只保留更具体规则。
4. 如果 allow_child_fragments = false，则只保留高优先级具体规则。
5. 输出 conflict report，记录被裁掉的实例。
```

这样可以解决：

```text
carbonyl vs amide vs ester vs imide
ether vs aromatic ether
halogen vs fluoro vs trifluoromethyl
ring vs phenylene linker
```

### 3.2 解决第 6 点：用 periodic graph matcher 替代字符串扩展 SMARTS

#### 3.2.1 不建议继续用字符串替换 `[*]`

不建议继续依赖：

```python
re.sub(r"\[\*\]", ...)
```

原因是它无法可靠表达图结构、键型和周期边界。

更稳妥的做法是：

```text
保留人工定义的 atom-mapped SMARTS
在 periodic expanded graph 上直接匹配
```

也就是说，不要把边界上下文硬编码进新 SMARTS，而是把边界真实建成图。

#### 3.2.2 构造 centered 3-mer periodic graph

对每个 repeat unit：

```text
RU[-1] + RU0 + RU[+1]
```

每个 RU copy 保留：

```text
unit_offset: -1 / 0 / +1
original_atom_id
periodic_atom_id
```

在添加跨单元 periodic edge 之前，必须先稳定确定两个 attachment 的角色。

不能简单依赖：

```text
RDKit atom index
canonical SMILES 中的出现顺序
```

因为 canonicalization 和 cut-shift 后，这些顺序不一定稳定。

可行方案包括：

```text
1. 如果原始数据中有 [*:1] / [*:2]，优先保留为 left/right 或 head/tail role。
2. 如果只有两个未标号 *，生成两个 orientation 进行规范化比较。
3. 对两个 orientation 都构造 periodic graph，选择 canonical graph key 较小者作为标准方向。
4. 如果两个方向等价，则记录为 orientation_symmetric。
5. 如果无法稳定判定方向，则进入 boundary_failed_cases，不进入生产匹配统计。
```

完成 attachment role canonicalization 后，再添加跨单元 periodic edge。

示意：

```text
RU[-1].right_neighbor -- RU0.left_neighbor
RU0.right_neighbor   -- RU[+1].left_neighbor
```

注意不是简单连接两个 `*` dummy atom，而是通常要找到 dummy atom 各自连接的真实原子：

```text
left_attachment_neighbor
right_attachment_neighbor
```

周期边应连接真实邻接原子，并记录：

```text
is_repeat_connection: true
is_periodic_edge: true
boundary_direction: left/right
```

#### 3.2.3 在 expanded graph 上匹配原始规则

规则保持为 atom-mapped SMARTS，例如：

```text
[NX3:1][CX3:2](=[OX1:3])
```

而不是生成：

```text
[*][N][C](=O)[C][*]
```

匹配流程：

```text
for rule in fragment_vocab:
  expanded_graph = build_centered_periodic_expansion(ru, rule.periodic_radius)
  matches = match(rule.pattern, expanded_graph)
  for match in matches:
    boundary_pattern = compute_boundary_pattern(match)
    if not rule.allow_boundary_crossing and boundary_pattern != internal:
      reject
    anchor = resolve_anchor(match, rule.anchor_rule)
    if anchor.unit_offset != 0:
      reject
    key = canonical_instance_key(match, anchor, boundary_pattern)
    dedup
```

这样可以保留完整化学图信息，也能处理跨边界 fragment。

#### 3.2.4 计算 boundary_pattern

根据 matched atoms 的 unit offsets：

```text
{0}             -> internal
{-1, 0}         -> cross_left
{0, +1}         -> cross_right
{-1, 0, +1}     -> cross_both
其它跨度         -> multi_period
```

这个字段进入 instance key：

```text
fragment_id
anchor_type
anchor_role
anchor_canonical_id_in_RU0
atom_role_pattern
boundary_pattern
```

#### 3.2.5 做 cut-shift scan

对同一个 periodic structure 生成不同切分视角：

```text
shift = -1, 0, +1
```

每个 shift 都跑 matcher，然后映射回原始 periodic coordinate。

验证：

```text
presence_label_consistency >= 0.99
instance_key_jaccard >= 0.95
duplicate_instance_rate <= 0.5%
boundary_ownership_accuracy >= 99%
```

这一步才能证明词表对 repeat-unit 切分位置稳定。

#### 3.2.6 如果短期不能实现 full graph matcher

可以做一个 MVP：

```text
1. 只处理两个 attachment 的 linear repeat unit。
2. 去掉 dummy atom。
3. 记录 left_neighbor / right_neighbor。
4. 复制三份 molecule。
5. 用 RWMol 添加跨 copy 的 single periodic bond。
6. 只对明确 single bond attachment 启用。
7. 输出 coverage gain 和 failed boundary cases。
```

其中第 6 条必须严格执行。只有满足下面条件时才允许构造 single periodic bond：

```text
1. repeat unit 中恰好两个 dummy attachment atoms。
2. 每个 dummy atom 恰好连接一个真实邻接原子。
3. dummy atom 到真实邻接原子的 bond type 都是 SINGLE。
4. attachment 方向已经稳定 canonicalize。
```

以下情况不能默默降级成 single bond，应写入 `boundary_failed_cases`：

```text
aromatic attachment bond
double attachment bond
directional / stereo bond
dummy atom 有多个邻接原子
attachment 数量不是 2
left/right role 无法稳定判定
```

MVP 也比字符串替换 SMARTS 更可控，因为它至少是在图上匹配。

---

## 4. 词表构建过程中的其它常见问题

### 4.1 数据准入污染

如果把以下记录混入主构建集，会污染词表：

```text
0 个连接点的小分子
1 个连接点的不完整记录
4 个连接点的共聚物候选
含 "." 的盐或多组分形式
含 "," 的多 repeat-unit 拼接
含 [R] / [R1] / [R2] 的未定义取代基
```

这些记录应分类保存，不能直接进入主词表。

### 4.2 long-format 属性表导致频率膨胀

原始 CSV 一行是一条性质记录，不是一条 polymer。

如果按 CSV row 统计 fragment frequency，会把性质记录多的 polymer 放大。

正确分母应是：

```text
unique polymer identity
canonical repeat-unit identity
canonical graph identity
```

不能用 CSV row 数。

### 4.3 attachment normalization 过度或不足

不足：

```text
[[*]] 和 [[[*]]] 没统一
```

会导致同一个结构重复进入词表。

过度：

```text
[R] / [R1] / [R2] 被替换成 *
```

会把未定义取代基误认为 polymer attachment。

### 4.4 canonicalization 策略不稳定

RDKit canonical SMILES 受以下因素影响：

```text
RDKit 版本
aromaticity model
显式/隐式 H
电荷处理
dummy atom 表示
isomericSmiles 参数
```

生产词表必须记录 RDKit 版本和 canonicalization 参数。

### 4.5 SMARTS 过宽

过宽规则会让 coverage 很好看，但语义不干净。

例如：

```text
[CX3]=[OX1]
```

会覆盖 carbonyl，但也会被 amide、ester、imide、ketone 共享。

如果没有 overlap resolver，标签会高度冗余。

### 4.6 SMARTS 过窄

过窄规则会漏掉常见变体。

例如只匹配某种显式 H 或某种芳香写法，可能导致同类结构因为写法差异被漏掉。

需要通过 examples 和 failed cases 检查。

### 4.7 atom_roles 和 anchor 不稳定

生产规则应使用 atom map number：

```text
[NX3:1][CX3:2](=[OX1:3])
```

并确保：

```text
atom_roles keys == SMARTS atom map ids
anchor_role 能映射到某个 atom map
```

如果使用 `"N"`、`"C"` 这样的角色 key，在同一 SMARTS 中有多个同元素原子时会不稳定。

### 4.8 父子 fragment 冗余

常见父子链：

```text
carbonyl -> amide -> imide -> aromatic_imide
ether -> aromatic_ether
halogen -> fluoro -> trifluoromethyl
ring -> phenylene_linkage
```

如果不裁决，会导致同一个局部结构产生大量重叠 label。

### 4.9 频率阈值误导

高频不一定有价值，低频不一定没价值。

例如：

```text
aromatic ring
alkyl linker
carbonyl
```

通常很高频，但可能只是背景结构。

而某些低频 motif 可能强烈关联特定性质，例如：

```text
phosphazene
ionic group
siloxane
perfluoroalkyl
```

因此频率过滤应结合化学语义和性质相关性。

### 4.10 coverage 指标虚高

如果词表里有非常宽的规则，可能很容易达到：

```text
polymer_with_at_least_one_fragment >= 95%
```

但这不代表词表质量高。

还需要看：

```text
avg fragment types per polymer
high overlap pairs
exclusive group conflicts
人工抽样正确率
cut-shift stability
external dataset transfer
```

### 4.11 输出不可复现

常见原因：

```text
脚本使用绝对路径
依赖没有固定
随机顺序没有固定
输出和脚本配置不一致
没有记录数据 hash
没有记录 RDKit 版本
```

生产构建应输出：

```text
build_summary
data_quality_report
stats
examples
failed_cases
validation_report
source_data_sha256
dependency versions
```

### 4.12 内部数据过拟合

只用当前内部数据构建词表，可能会学到数据集特有的 motif。

发布前应至少做：

```text
内部 train/validation split
冻结词表后外部 RU 数据集验证
failed case 分类
low coverage motif review
```

### 4.13 核心词表和候选池混淆

mined motif candidate 不等于最终入表规则。

候选池可以包含：

```text
高频子图
局部 motif SMILES
待人工审核结构
```

核心词表必须包含：

```text
稳定 fragment_id
明确 fragment_name
atom-mapped SMARTS 或 graph pattern
atom_roles
anchor_rule
ownership_rule
dedup_key_fields
overlap_policy
```

否则 matcher 无法稳定执行。

---

## 总结

当前两个脚本的定位不同：

```text
scripts/fragment_construct.py
  试图通过 wildcard 替换处理 RU 边界上下文，但 constraints 和 SMARTS 扩展方式不可靠。

scripts/build_fragment_vocab_v1.py
  更适合当前项目的可复现构建流程，完成了清洗、canonical 去重、atom-mapped seed rules、覆盖统计和核心词表冻结。
  但它还没有实现真正的 periodic 3-mer matcher、match-level overlap resolver 和 cut-shift stability validation。
```

如果要把词表推进到生产可用，优先级建议是：

```text
P0: 实现 periodic 3-mer repeat-unit matcher
P0: 实现 match-level constraints 和 overlap resolver
P1: 输出 boundary_pattern 和 canonical instance key
P1: 做 cut-shift stability validation
P2: 将 mined motifs 人工审核后转为 atom-mapped SMARTS
P2: 做外部 RU 数据集迁移验证
```
