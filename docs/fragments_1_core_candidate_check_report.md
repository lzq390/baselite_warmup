# fragments_1 核心词表与候选词表核查报告

生成时间：2026-05-08

## 核查对象

本次核查 `fragments_1/` 下 3 个文件：

- `fragments_1/base_fragment_new2.json`
- `fragments_1/extracted_fragments1.json`
- `fragments_1/extracted_fragments1_match_count_distribution.csv`

对应数据口径：

- `data/processed/periods2_from_unique_standardized_smiles.csv`
- period SMILES 数：55060 条

## 总体结论

`fragments_1` 这批结果目前不能直接作为“已确认核心词表 + 已清洗候选词表”使用。

核心问题是：

1. `base_fragment_new2.json` 只有 36 条，不是之前计划的 40 条核心词表。
2. `extracted_fragments1.json` 有 2946 条候选，但只有 31 个唯一 `fragment_id`，候选 ID 不稳定，不能直接作为词表主键。
3. CSV 与候选 JSON 数量一致，但 CSV 是 `match_count -> fragment_number` 的分布表，不是 per-candidate 明细表。
4. 候选词表中存在 exact duplicate pattern，尤其五/六元环规则重复严重。
5. 核心词表和候选词表来源 ID 不一致：候选中出现 `fragment_037`，但当前核心文件没有 `fragment_037`。
6. 所有 SMARTS 都能被 RDKit 解析，但核心和候选全部没有 atom map number，不符合当前生产 schema 要求。
7. 多个高频规则过宽，match_count 很高不等于片段质量高。

因此这批文件适合作为“原始实验结果”保留，但不适合直接进入后续候选筛选和最终完整词表生成。建议先修复核心 40 条，再重新生成候选词表。

## 文件数量核对

| 文件 | 记录数/行数 | 说明 |
|---|---:|---|
| `base_fragment_new2.json` | 36 条 | 当前核心/基础规则文件。 |
| `extracted_fragments1.json` | 2946 条 | 当前候选规则文件。 |
| `extracted_fragments1_match_count_distribution.csv` | 416 行 | 候选规则 match_count 分布。 |
| `periods2_from_unique_standardized_smiles.csv` | 55061 行 | 55060 条数据 + header。 |

CSV 分布校验：

- `fragment_number` 求和：2946
- 与 `extracted_fragments1.json` 候选数量一致
- `match_count * fragment_number` 加权求和：913656

这说明 CSV 和候选 JSON 在数量上是一致的。

## 核心词表核查

### 基本情况

`base_fragment_new2.json`：

- 规则数：36
- RDKit 不可解析 SMARTS：0
- 缺少 atom map number 的 SMARTS：36
- 缺少 `match_count`：0
- exact duplicate pattern：0

### 明显问题

#### 1. 核心数量不是 40

当前核心文件只有 36 条。和前面讨论的“7 条保留 + 15 条修正后保留 + 18 条补入 = 40 条”不一致。

当前文件不能代表新的 40 条核心词表方案。

#### 2. 所有 SMARTS 都没有 atom map number

例如：

```text
[*][NX3][CX3](=O)[*]
[*][CX3](=O)[OX2][*]
[*][OX2][*]
```

这些可以匹配，但无法稳定映射 `atom_roles`，后续 anchor、dedup、overlap 都会不稳。生产词表应改成 atom-mapped SMARTS，例如：

```text
[NX3:1][CX3:2](=[OX1:3])
```

#### 3. 有 4 条核心规则文件内 match_count 为 0，但重算不为 0

| fragment_id | name | pattern |
|---|---|---|
| `fragment_031` | diacylamine_linker | `[*]C(=O)NC(=O)[*]` |
| `fragment_032` | secondary_amine_linker | `[*][NH][*]` |
| `fragment_033` | azo_linker | `[*]N=N[*]` |
| `fragment_034` | ester_linker | `[*]C(=O)O[*]` |

这 4 条在 `base_fragment_new2.json` 文件内写的是 `match_count: 0`。但重新用这些 SMARTS 对 55060 条 `periods2` 计算后，结果并不是 0：

| fragment_id | name | file_match_count | recomputed_period_hits | recomputed_match_total |
|---|---|---:|---:|---:|
| `fragment_031` | diacylamine_linker | 0 | 11348 | 21357 |
| `fragment_032` | secondary_amine_linker | 0 | 20794 | 42737 |
| `fragment_033` | azo_linker | 0 | 1719 | 2167 |
| `fragment_034` | ester_linker | 0 | 21707 | 44034 |

因此这里的问题不是“这些片段真实零匹配”，而是 `base_fragment_new2.json` 中这 4 条的 `match_count` 字段没有按当前 55060 条 `periods2` 口径更新。候选词表中来自 `fragment_031`、`fragment_032`、`fragment_034` 的大量候选也支持这一点。

结论：当前核心文件里的 `match_count` 字段不能直接作为最终统计依据，应统一用同一份 `periods2` 数据重新计算。

#### 4. 多条规则过宽

以下核心规则的 `match_count` 超过 55060，因为它们统计的是总 match instance，不是 period 行数：

| fragment_id | name | match_count | 问题 |
|---|---|---:|---|
| `fragment_035` | six_membered_aromatic_heterocycle | 161069 | SMARTS 同时允许大写/小写原子，实际是泛化五/六元环，不是严格 heterocycle。 |
| `fragment_014` | ketone | 129013 | 原规则是 generic carbonyl，会覆盖 ester、amide、urethane、urea 等。 |
| `fragment_013` | amine | 120746 | 会覆盖 amide/urea/imide/aromatic amine 等 N 环境。 |
| `fragment_004` | ether | 108215 | 会覆盖 ester/carbonate/urethane 中的 O。 |
| `fragment_028` | halogen_substituent | 85252 | 多卤/全氟结构会重复放大。 |
| `fragment_030` | methyl | 78948 | 过于普通，不适合作为核心片段。 |

这些高频不代表更适合作为核心词表，反而说明规则需要收窄或降级。

#### 5. 环规则命名仍不干净

当前仍存在命名/类别风险：

- `fragment_021` 到 `fragment_024` 名称是 `four_membered_aromatic_heterocycle_*`，但 category 是 `cycloaliphatic_ring`。
- `fragment_035` / `fragment_036` 名称是 aromatic heterocycle，但 SMARTS 允许 `C,N,O,S,c,n,o,s`，会混入非芳香/全碳环。
- 五/六元环没有取代模式派生字段，因此现在不能区分 para/meta/ortho 或五元环 1,2/1,3 等模式。

## 候选词表核查

### 基本情况

`extracted_fragments1.json`：

- 候选数：2946
- RDKit 不可解析 SMARTS：0
- 缺少 atom map number 的 SMARTS：2946
- 唯一 `fragment_id` 数：31
- exact duplicate pattern：2 类
- exact duplicate `(source, pattern)`：2 类

### CSV 分布解释

CSV 字段是：

```text
match_count,fragment_number
```

含义是：有多少个候选 fragment 的 `match_count` 等于某个数。

它不是 per-candidate 明细表，因此不能从这个 CSV 直接知道某条候选规则是什么，只能看分布。

候选 match_count 分布：

| 条件 | 候选数 |
|---|---:|
| `match_count >= 1` | 2946 |
| `match_count >= 10` | 1254 |
| `match_count >= 50` | 604 |
| `match_count >= 100` | 422 |
| `match_count >= 500` | 176 |
| `match_count >= 1000` | 131 |
| `match_count >= 5000` | 43 |
| `match_count >= 10000` | 21 |

低频候选很多：

| 条件 | 候选数 |
|---|---:|
| `match_count <= 1` | 576 |
| `match_count <= 5` | 1399 |
| `match_count <= 10` | 1743 |
| `match_count <= 100` | 2527 |

这说明候选池需要强过滤，不能直接进入最终词表。

### 核心与候选 source 不一致

候选中出现了当前核心文件不存在的来源：

```text
fragment_037
```

当前核心文件中没有对应候选来源的规则：

```text
fragment_006
fragment_022
fragment_023
fragment_024
fragment_028
fragment_036
```

这说明 `extracted_fragments1.json` 很可能不是基于当前 `base_fragment_new2.json` 重新生成的，或者中间发生过手工改动/重编号。后续不能把二者当成同一版本配套使用。

### 候选 ID 不稳定

候选文件有 2946 条，但唯一 `fragment_id` 只有 31 个。例如：

| fragment_id | 候选条数 |
|---|---:|
| `fragment_035` | 1757 |
| `fragment_037` | 535 |
| `fragment_004` | 64 |
| `fragment_013` | 59 |
| `fragment_032` | 47 |
| `fragment_014` | 44 |

这说明候选没有独立 ID。后续必须重新编号，例如：

```text
CAND_FRAGMENT_000001
CAND_FRAGMENT_000002
...
```

并保留：

```text
source_fragment_id
source_fragment_name
source_pattern
candidate_pattern
```

### exact duplicate pattern

候选中存在完全重复 pattern，主要来自五/六元环：

```text
[C,N,O,S,c,n,o,s;R]1[C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R]1
```

以及：

```text
[C,N,O,S,c,n,o,s;R]1[C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R][C,N,O,S,c,n,o,s;R]1
```

这些重复说明当前候选生成过程没有在最终输出前做可靠去重。特别是环规则，不能继续用这种方式扩展候选，应改成 ring 派生属性。

### 高频候选主要来自过宽规则

最高频候选包括：

| source | name | match_count | pattern |
|---|---|---:|---|
| `fragment_013` | amine | 49086 | `[*][C][NX3][C][*]` |
| `fragment_030` | methyl | 39008 | `[*][c][#6]-[CH3]` |
| `fragment_004` | ether | 37958 | `[*][C][OX2][C][*]` |
| `fragment_014` | ketone | 27383 | `[*][N][C](=O)[c][*]` |
| `fragment_014` | ketone | 24602 | `[*][c][C](=O)[N][*]` |
| `fragment_004` | ether | 22626 | `[*][c][OX2][c][*]` |
| `fragment_002` | imide | 19500 | `[*][c][CX3](=O)[NX3][CX3](=O)[c][*]` |

其中一部分是有价值的，例如芳香 imide；但很多只是过宽父规则的局部环境变体，不应直接升入最终词表。

### SMARTS 扩展质量问题

候选中存在大量简单原子替换：

| 模式 | 候选数 |
|---|---:|
| 包含 `[C]` | 284 |
| 包含 `[c]` | 209 |
| 包含 `[N]` | 120 |
| 包含 `[O]` | 129 |

这些来自原 `fragment_construct.py` 的 `atom_to_simple_smarts` 简化逻辑，只保留元素/芳香性/电荷，不保留 H 数、degree、价态、ring、键型、立体等信息。候选可能过泛，不能只按 `match_count` 选。

## 对当前 CSV 的判断

CSV 与候选 JSON 数量一致，可以作为“候选 match_count 分布”参考。

但它不够用于最终筛选，因为缺少：

- candidate ID
- source fragment
- SMARTS pattern
- period_hits
- source_hits
- match_count
- duplicate group
- overlap_with_core
- example_smiles

建议后续新增 per-candidate 明细 CSV：

```text
candidate_id,source_fragment_id,fragment_name,pattern,match_count,period_hits,source_hits,duplicate_key,status
```

当前这个 distribution CSV 只能回答“有多少候选是低频/高频”，不能支持逐条审核。

## 建议处理顺序

### 第一步：不要继续基于当前 36 条核心生成最终候选

先按 `docs/base_fragments_repair_40_core_vocab_process.md` 修复成 40 条核心词表。

当前 `base_fragment_new2.json` 和 `extracted_fragments1.json` 不配套，不建议继续往下筛。

### 第二步：重新生成候选词表

候选生成应使用修复后的 40 条核心词表，并满足：

1. 候选有唯一 `candidate_id`。
2. SMARTS 使用 atom map number，或至少保留 role mapping。
3. 去重 key 使用 `(source_fragment_id, normalized_candidate_pattern)`。
4. 环取代模式不通过 wildcard 扩展生成候选，改为派生属性。
5. 统计同时输出 `match_count`、`period_hits`、`source_hits`。

### 第三步：候选初筛

建议先按下面规则过滤：

- 删除 exact duplicate pattern。
- 删除 `match_count <= 5` 的极低频候选，除非人工标记为材料族关键片段。
- 对 `match_count >= 100` 的候选优先人工审核。
- 对 `match_count >= 1000` 的候选重点检查是否只是过宽父规则。
- 对 ring 类候选转入 `derived_ring_attributes`，不直接作为候选 fragment。
- 对 methyl、methylene、alkyl 这类普通片段降级为辅助 feature。

### 第四步：重新生成候选统计 CSV

保留当前 distribution CSV 的同时，增加 per-candidate 明细 CSV。最终筛选完整词表时，不能只看分布。

## 最终判断

当前 `fragments_1` 结果有参考价值，但更适合作为“旧流程候选生成结果”的审计材料。

不能直接使用的原因：

- 核心只有 36 条，且与候选来源不一致。
- 核心文件内部分 `match_count` 字段与当前 55060 条 `periods2` 重算结果不一致。
- 候选 2946 条没有独立 ID。
- CSV 是分布，不是候选明细。
- 低频候选占比很高。
- 环规则重复严重。
- 高频候选主要来自过宽规则。
- 所有 SMARTS 都缺少 atom map number。

建议结论：

```text
base_fragment_new2.json：不作为最终核心词表，需按 40 条方案重建；其中 match_count 需要统一重算。
extracted_fragments1.json：仅作为旧候选池参考，不直接筛最终词表。
extracted_fragments1_match_count_distribution.csv：数量一致，可作为分布参考，但不足以支持候选审核。
```
