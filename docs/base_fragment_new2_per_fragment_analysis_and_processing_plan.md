# base_fragment_new2 核心词表逐条片段分析与处理方案

- 生成日期：2026-05-09
- 核心词表：`fragments_1/base_fragment_new2.json`
- 匹配数据：`data/processed/periods2_from_unique_standardized_smiles.csv`
- 核心规则数：36
- period 行数：55060
- 唯一 source 数：10444
- RDKit 无法解析的 period SMILES：0
- RDKit 无法解析的核心 SMARTS：0

## 1. 分析口径

本报告按 `fragments_1/base_fragment_new2.json` 中的每一条 fragment 逐条分析，而不是按字段分析。

匹配统计使用当前 55060 条 `periods2_from_unique_standardized_smiles.csv` 重新计算。统计时只执行 SMARTS 子结构匹配，未执行 `constraints`，原因是当前约束里仍包含 `exclude`、`exact_fluorine_count`、`exclude_perfluoroalkyl_chain` 等未注册或非统一语义的 key。

因此，本报告中的 `period_hits`、`source_hits` 和 `match_total` 默认是“原始 SMARTS 覆盖能力”，不是最终经过 overlap resolver 和 constraint 二次过滤后的最终词表命中。`fragment_001` 已按本报告方案完成修复，因此统计总览中使用修复后的实例级 overlap 过滤口径；原始 SMARTS 口径保留在该片段小节和单独对比报告中。

指标含义：

- `file_match_count`：核心 JSON 里原有的 `match_count`，只作为旧统计参考。
- `period_hits`：55060 条 period 中至少命中一次该 SMARTS 的行数。
- `period_coverage`：`period_hits / 55060`，表示该片段覆盖当前 period 行的比例。
- `source_hits`：命中该 SMARTS 的唯一原始标准化 RU 来源数。
- `source_coverage`：`source_hits / 10444`，表示该片段覆盖唯一标准化 RU 来源的比例。
- `match_total`：所有 period 上的 match instance 总数。
- `max_per_period`：单条 period 内最多出现的 match instance 数，用于识别过宽或对称重复放大。

## 2. 总体结论

- 可直接保留：7 条，`fragment_002`, `fragment_003`, `fragment_007`, `fragment_009`, `fragment_011`, `fragment_026`, `fragment_033`
- 修正后保留：12 条，`fragment_001`, `fragment_004`, `fragment_005`, `fragment_006`, `fragment_008`, `fragment_012`, `fragment_013`, `fragment_014`, `fragment_025`, `fragment_028`, `fragment_029`, `fragment_032`
- 低频/低优先级保留：3 条，`fragment_010`, `fragment_015`, `fragment_027`
- 合并到其它核心：2 条，`fragment_031`, `fragment_034`
- 降级为派生属性：6 条，`fragment_016`, `fragment_017`, `fragment_018`, `fragment_019`, `fragment_020`, `fragment_030`
- 删除或失败用例：4 条，`fragment_021`, `fragment_022`, `fragment_023`, `fragment_024`
- 拆分重建：2 条，`fragment_035`, `fragment_036`

总体处理方向：

1. 功能团类片段大多可以保留，但必须依赖实例级 overlap/priority 处理，不能只靠当前自然语言 constraints。
2. `ketone`、`ether`、`amine` 三类当前明显过宽，需要重定义或降级为父级 feature。
3. 四元环取代枚举不适合作为核心片段，应改为 ring 派生属性。
4. 五元/六元环不应靠多条 SMARTS 枚举取代模式；建议保留 ring scaffold 父级，再记录 substitution、attachment、hetero signature、fused ring 等派生字段。
5. `fragment_031`/`fragment_034` 与已有 imide/ester 重复，应合并；主链 linker 语义由 `backbone_role` 或 attachment path 计算。
6. `match_count` 不应继续写在核心词表主 JSON 中，应输出到独立 stats/report 文件，并明确统计口径。

## 3. 统计总览

| fragment_id | name | category | file_match_count | period_hits | period_coverage | source_hits | source_coverage | match_total | max_per_period | 处理结论 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `fragment_001` | `amide` | `functional_group` | 29731 | 16579 | 30.11% | 2392 | 22.90% | 31319 | 8 | 已修复，实例级过滤 |
| `fragment_002` | `imide` | `functional_group` | 21343 | 11348 | 20.61% | 1993 | 19.08% | 21357 | 6 | 已修复，priority=70 |
| `fragment_003` | `ester` | `functional_group` | 44044 | 21707 | 39.42% | 3455 | 33.08% | 44034 | 8 | 保留 |
| `fragment_004` | `ether` | `functional_group` | 108215 | 23780 | 43.19% | 4113 | 39.38% | 48102 | 24 | 已修复，排除 carbonyl-adjacent O |
| `fragment_005` | `carbonate` | `functional_group` | 2080 | 1428 | 2.59% | 283 | 2.71% | 2082 | 3 | 已修复，priority=70 |
| `fragment_006` | `urethane` | `functional_group` | 5291 | 3027 | 5.50% | 315 | 3.02% | 5291 | 6 | 保留并修正约束 |
| `fragment_007` | `urea` | `functional_group` | 2464 | 1117 | 2.03% | 143 | 1.37% | 2465 | 8 | 保留 |
| `fragment_008` | `thioether` | `functional_group` | 7945 | 5605 | 10.18% | 1005 | 9.62% | 7976 | 7 | 修正后保留 |
| `fragment_009` | `sulfone` | `functional_group` | 3883 | 3233 | 5.87% | 586 | 5.61% | 3883 | 3 | 保留 |
| `fragment_010` | `sulfoxide` | `functional_group` | 30 | 30 | 0.05% | 9 | 0.09% | 30 | 1 | 低优先级保留 |
| `fragment_011` | `nitrile` | `functional_group` | 3115 | 1789 | 3.25% | 368 | 3.52% | 3279 | 11 | 保留 |
| `fragment_012` | `hydroxyl` | `functional_group` | 3242 | 1958 | 3.56% | 472 | 4.52% | 3553 | 8 | 修正后保留 |
| `fragment_013` | `amine` | `functional_group` | 120746 | 30741 | 55.83% | 4627 | 44.30% | 120912 | 18 | 修正后保留或降级为父级 |
| `fragment_014` | `ketone` | `functional_group` | 129013 | 44227 | 80.33% | 7085 | 67.84% | 129167 | 19 | 重定义后保留 |
| `fragment_015` | `carboxylic_acid` | `functional_group` | 337 | 226 | 0.41% | 63 | 0.60% | 337 | 2 | 低频保留 |
| `fragment_016` | `four_membered_aliphatic_heterocycle_one_substituted` | `cycloaliphatic_ring` | 844 | 162 | 0.29% | 56 | 0.54% | 863 | 8 | 降级为派生属性 |
| `fragment_017` | `four_membered_aliphatic_heterocycle_two_substituted_first` | `cycloaliphatic_ring` | 1174 | 139 | 0.25% | 42 | 0.40% | 1188 | 16 | 降级为派生属性 |
| `fragment_018` | `four_membered_aliphatic_heterocycle_two_substituted_second` | `cycloaliphatic_ring` | 668 | 150 | 0.27% | 48 | 0.46% | 677 | 8 | 降级为派生属性 |
| `fragment_019` | `four_membered_aliphatic_heterocycle_three_substituted` | `cycloaliphatic_ring` | 1929 | 138 | 0.25% | 41 | 0.39% | 1938 | 32 | 降级为派生属性 |
| `fragment_020` | `four_membered_aliphatic_heterocycle_four_substituted` | `cycloaliphatic_ring` | 796 | 109 | 0.20% | 33 | 0.32% | 796 | 16 | 降级为派生属性 |
| `fragment_021` | `four_membered_aromatic_heterocycle_two_substituted_first` | `cycloaliphatic_ring` | 1174 | 12 | 0.02% | 1 | 0.01% | 12 | 1 | 删除或失败用例保留 |
| `fragment_022` | `four_membered_aromatic_heterocycle_two_substituted_second` | `cycloaliphatic_ring` | 668 | 0 | 0.00% | 0 | 0.00% | 0 | 0 | 删除 |
| `fragment_023` | `four_membered_aromatic_heterocycle_three_substituted` | `cycloaliphatic_ring` | 1929 | 0 | 0.00% | 0 | 0.00% | 0 | 0 | 删除 |
| `fragment_024` | `four_membered_aromatic_heterocycle_four_substituted` | `cycloaliphatic_ring` | 796 | 0 | 0.00% | 0 | 0.00% | 0 | 0 | 删除 |
| `fragment_025` | `five_membered_aromatic_heterocycle` | `aromatic_ring` | 9763 | 6296 | 11.43% | 1435 | 13.74% | 10010 | 6 | 修正后保留 |
| `fragment_026` | `vinylene_linkage` | `mainchain_linker` | 4209 | 3001 | 5.45% | 530 | 5.07% | 4243 | 4 | 保留 |
| `fragment_027` | `ethynylene_linkage` | `mainchain_linker` | 955 | 509 | 0.92% | 82 | 0.79% | 955 | 6 | 低频保留 |
| `fragment_028` | `halogen_substituent` | `side_group` | 85252 | 6461 | 11.73% | 1659 | 15.88% | 85570 | 87 | 修正后保留 |
| `fragment_029` | `trifluoromethyl` | `side_group` | 22769 | 3888 | 7.06% | 909 | 8.70% | 22840 | 18 | 修正后保留 |
| `fragment_030` | `methyl` | `side_group` | 78948 | 18204 | 33.06% | 3764 | 36.04% | 79206 | 36 | 降级为派生属性 |
| `fragment_031` | `diacylamine_linker` | `linker` | 0 | 11348 | 20.61% | 1993 | 19.08% | 21357 | 6 | 合并到 fragment_002 |
| `fragment_032` | `secondary_amine_linker` | `linker` | 0 | 20794 | 37.77% | 2560 | 24.51% | 42737 | 8 | 修正后保留 |
| `fragment_033` | `azo_linker` | `linker` | 0 | 1719 | 3.12% | 282 | 2.70% | 2167 | 3 | 保留 |
| `fragment_034` | `ester_linker` | `linker` | 0 | 21707 | 39.42% | 3455 | 33.08% | 44034 | 8 | 合并到 fragment_003 |
| `fragment_035` | `six_membered_aromatic_heterocycle` | `aromatic_ring` | 161069 | 42931 | 77.97% | 7936 | 75.99% | 167375 | 20 | 拆分重建 |
| `fragment_036` | `five_membered_aromatic_heterocycle` | `aromatic_ring` | 9763 | 19585 | 35.57% | 3857 | 36.93% | 36088 | 9 | 拆分重建 |

## 4. 逐条片段分析

### fragment_001 `amide`

- 当前 SMARTS：`[*:1][NX3:2][CX3:3](=[O:4])[*:5]`
- 当前分类：`functional_group`
- 原始 SMARTS 覆盖：period_hits=27559（period_coverage=50.05%），source_hits=3934（source_coverage=37.67%），match_total=124626，max_per_period=18
- 修复后覆盖：period_hits=16579（period_coverage=30.11%），source_hits=2392（source_coverage=22.90%），match_total=31319，max_per_period=8
- 文件内旧 `match_count`：29731
- 当前 constraints：无
- overlap：exclusive_group=`carbonyl_family`，priority=40
- 结论：已修复，实例级过滤
- 分析：amide 是核心功能团，但当前规则会与 imide、urea、urethane 等 carbonyl-N 结构重叠。
- 风险：旧方案使用全局 `not_smarts` 时，只要 molecule 内出现 `N-C(=O)-N` 或 `O=C-N-C=O`，就可能把同一 molecule 中其它合法 amide 一起排除。
- 处理方案：已从核心 JSON 中移除全局 `not_smarts`，并把 amide priority 从 50 降到 40。匹配时先保留原始 amide SMARTS 命中，再做实例级 overlap 过滤：如果 amide match 的核心原子 `{amide N, carbonyl C, carbonyl O}` 被更具体的 `imide`、`urethane` 或 `urea` match 覆盖，则丢弃该 amide match；其它独立 amide 保留。单独对比报告见 `docs/fragment_001_amide_fix_comparison.md`。

### fragment_002 `imide`

- 当前 SMARTS：`[*:1][CX3:2](=[O:3])[NX3:4][CX3:5](=[O:6])[*:7]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=11348（period_coverage=20.61%），source_hits=1993（source_coverage=19.08%），match_total=21357，max_per_period=6
- 文件内旧 `match_count`：21343
- 当前 constraints：无
- overlap：exclusive_group=`carbonyl_family`，priority=70
- 结论：已修复，priority=70
- 分析：imide 语义明确、覆盖充分，是 carbonyl family 中的高价值核心片段。
- 风险：当前文件内 `match_count` 与重算值不完全一致；composite anchor 需要稳定的中心 hash。
- 处理方案：保留为核心；已将 priority 从 50 调整到 70，使其高于 amide、ester、generic carbonyl；dedup 使用两个 carbonyl C 和 imide N 的组合 anchor。

### fragment_003 `ester`

- 当前 SMARTS：`[*:1][CX3:2](=[O:3])[OX2:4][*:5]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=21707（period_coverage=39.42%），source_hits=3455（source_coverage=33.08%），match_total=44034，max_per_period=8
- 文件内旧 `match_count`：44044
- 当前 constraints：无
- overlap：exclusive_group=`carbonyl_family`，priority=50
- 结论：保留
- 分析：ester 语义明确、覆盖充分，适合作为核心功能团。
- 风险：会与 carbonate、urethane、ether、carbonyl 父级发生重叠。
- 处理方案：保留；priority 高于 ether/generic carbonyl，低于 carbonate、lactone、anhydride 等更具体结构；统计从核心 JSON 移到 stats 文件。

### fragment_004 `ether`

- 当前 SMARTS：`[#6;!$(C=O):1][OX2:2][#6;!$(C=O):3]`
- 当前分类：`functional_group`
- 修复前覆盖：period_hits=40715（period_coverage=73.95%），source_hits=6868（source_coverage=65.76%），match_total=108289，max_per_period=38
- 修复后覆盖：period_hits=23780（period_coverage=43.19%），source_hits=4113（source_coverage=39.38%），match_total=48102，max_per_period=24
- 文件内旧 `match_count`：108215
- 当前 constraints：无
- overlap：exclusive_group=`linkage_family`，priority=30
- 结论：已修复，排除 carbonyl-adjacent O
- 分析：原 `[OX2]` 捕获的是通用单键氧连接，覆盖很高，会把 ester、carbonate、urethane 中的单键 O 也算作 ether。当前已收窄为两侧都是非 carbonyl carbon 的 `C-O-C` ether。
- 风险：修复后不再覆盖 `C(=O)-O`，但仍可能同时包含芳香 ether、脂肪 ether、主链 ether 和侧基 alkoxy，后续还需要用 `backbone_role` 或邻接环境做派生分类。
- 处理方案：已将 SMARTS 从 `[*][OX2][*]` 改为 `[#6;!$(C=O)][OX2][#6;!$(C=O)]`，并把 priority 从 50 降到 30。重算验证新 ether 与 `C(=O)-O` carbonyl-adjacent O 的重叠为 0。

### fragment_005 `carbonate`

- 当前 SMARTS：`[*:1][OX2:2][CX3:3](=[O:4])[OX2:5][*:6]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=1428（period_coverage=2.59%），source_hits=283（source_coverage=2.71%），match_total=2082，max_per_period=3
- 文件内旧 `match_count`：2080
- 当前 constraints：无
- overlap：exclusive_group=`carbonyl_family`，priority=70
- 结论：已修复，priority=70
- 分析：carbonate 语义明确，虽然覆盖不高但材料意义强。
- 风险：原 `exclude` 是自然语言或未注册约束，当前构建和匹配流程不会可靠执行。
- 处理方案：已移除自然语言 `exclude`，保留明确的 `O-C(=O)-O` SMARTS，并把 priority 从 50 调整到 70，使 carbonate 高于 ester、ether、generic carbonyl。后续如需额外约束，应进入 constraint registry。

### fragment_006 `urethane`

- 当前 SMARTS：`[*:1][OX2:2][CX3:3](=[O:4])[NX3:5][*:6]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=3027（period_coverage=5.50%），source_hits=315（source_coverage=3.02%），match_total=5291，max_per_period=6
- 文件内旧 `match_count`：5291
- 当前 constraints：`exclude`
- overlap：exclusive_group=`carbonyl_family`，priority=50
- 结论：保留并修正约束
- 分析：urethane/carbamate 是明确且有材料语义的核心片段。
- 风险：与 amide、ester、ether、carbonyl 父级重叠；自然语言 `exclude` 不可依赖。
- 处理方案：保留；注册可执行约束；priority 高于 amide、ester、ether；必要时拆分 N-H urethane 与 N-substituted urethane 派生属性。

### fragment_007 `urea`

- 当前 SMARTS：`[*:1][NX3:2][CX3:3](=[O:4])[NX3:5][*:6]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=1117（period_coverage=2.03%），source_hits=143（source_coverage=1.37%），match_total=2465，max_per_period=8
- 文件内旧 `match_count`：2464
- 当前 constraints：`exclude`
- overlap：exclusive_group=`carbonyl_family`，priority=50
- 结论：保留
- 分析：urea 低频但语义明确，应作为比 amide 更具体的 carbonyl-N 规则。
- 风险：如果只靠 generic amide，会吞掉 urea 语义；当前 `exclude` 类型也需要规范化。
- 处理方案：保留为低频核心；priority 高于 amide；约束统一注册；统计字段外置。

### fragment_008 `thioether`

- 当前 SMARTS：`[*:1]-[S:2]-[*:3]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=5605（period_coverage=10.18%），source_hits=1005（source_coverage=9.62%），match_total=7976，max_per_period=7
- 文件内旧 `match_count`：7945
- 当前 constraints：`exclude`
- overlap：exclusive_group=`sulfur_family`，priority=50
- 结论：修正后保留
- 分析：thioether 是有价值的 sulfur linkage，但当前 `[S]` 规则不够具体。
- 风险：可能与 sulfone、sulfoxide 等氧化硫结构重叠；`exclude` 不一定执行。
- 处理方案：改为更明确的 divalent sulfur 规则，例如基于 `[SX2]` 并排除 S=O；priority 低于 sulfone/sulfoxide。

### fragment_009 `sulfone`

- 当前 SMARTS：`[*:1][SX4:2](=[O:3])(=[O:4])[*:5]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=3233（period_coverage=5.87%），source_hits=586（source_coverage=5.61%），match_total=3883，max_per_period=3
- 文件内旧 `match_count`：3883
- 当前 constraints：`exclude`
- overlap：exclusive_group=`sulfur_family`，priority=50
- 结论：保留
- 分析：sulfone SMARTS 具体，覆盖充分，是 sulfur family 的核心片段。
- 风险：仍需避免被 thioether 父级重复解释。
- 处理方案：保留；priority 高于 thioether；约束改成可执行形式；保留 sulfur oxidation state 作为派生属性。

### fragment_010 `sulfoxide`

- 当前 SMARTS：`[*:1][SX3:2](=[O:3])[*:4]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=30（period_coverage=0.05%），source_hits=9（source_coverage=0.09%），match_total=30，max_per_period=1
- 文件内旧 `match_count`：30
- 当前 constraints：`exclude`
- overlap：exclusive_group=`sulfur_family`，priority=50
- 结论：低优先级保留
- 分析：sulfoxide 命中很低，但化学语义明确。
- 风险：覆盖低，不适合作为提高整体 coverage 的主力；如果规则过严，可能漏掉配位或特殊价态形式。
- 处理方案：保留为低频核心或扩展核心；priority 高于 thioether；在报告中标记 low_support。

### fragment_011 `nitrile`

- 当前 SMARTS：`[*:1][CX2:2]#[NX1:3]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=1789（period_coverage=3.25%），source_hits=368（source_coverage=3.52%），match_total=3279，max_per_period=11
- 文件内旧 `match_count`：3115
- 当前 constraints：`exclude`
- overlap：exclusive_group=`nitrile_family`，priority=50
- 结论：保留
- 分析：nitrile 规则具体，语义明确。
- 风险：文件内 `match_count` 与当前 55060 period 重算值不同，说明统计口径已变化。
- 处理方案：保留；更新外部统计；必要时增加 cyano side group 与 backbone nitrile 的 role 派生字段。

### fragment_012 `hydroxyl`

- 当前 SMARTS：`[*:1][OH:2]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=1958（period_coverage=3.56%），source_hits=472（source_coverage=4.52%），match_total=3553，max_per_period=8
- 文件内旧 `match_count`：3242
- 当前 constraints：`exclude`
- overlap：exclusive_group=`oxygen_hydrogen_family`，priority=50
- 结论：修正后保留
- 分析：hydroxyl 有意义，但当前只表达 O-H，不区分 alcohol、phenol、carboxylic acid OH。
- 风险：会与 carboxylic_acid、phenol 等不同化学环境混在一起。
- 处理方案：保留为 hydroxyl 父级；增加 `hydroxyl_subtype` 派生属性，或拆出 alcohol/phenol/acid_oh；carboxylic_acid 优先。

### fragment_013 `amine`

- 当前 SMARTS：`[*:1][NX3:2][*:3]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=30741（period_coverage=55.83%），source_hits=4627（source_coverage=44.30%），match_total=120912，max_per_period=18
- 文件内旧 `match_count`：120746
- 当前 constraints：`exclude`
- overlap：exclusive_group=`nitrogen_family`，priority=50
- 结论：修正后保留或降级为父级
- 分析：当前 amine 覆盖很高，更像 generic nitrogen single-bond environment。
- 风险：会覆盖 amide、urea、imide、urethane、芳香胺等 N 环境，作为独立核心 amine 过宽。
- 处理方案：如果保留 amine，应排除 carbonyl-adjacent N，并拆分 primary/secondary/tertiary/aromatic amine；priority 低于所有更具体 N-containing fragment。

### fragment_014 `ketone`

- 当前 SMARTS：`[*:1][C:2](=[O:3])[*:4]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=44227（period_coverage=80.33%），source_hits=7085（source_coverage=67.84%），match_total=129167，max_per_period=19
- 文件内旧 `match_count`：129013
- 当前 constraints：`exclude`
- overlap：exclusive_group=`carbonyl_family`，priority=50
- 结论：重定义后保留
- 分析：当前名称是 ketone，但 SMARTS 实际是 generic carbonyl。
- 风险：会大量命中 ester、amide、imide、urethane、carbonate、acid 等所有 C=O，不能直接代表 ketone。
- 处理方案：二选一：改名为 `carbonyl` 并作为低优先级父级；或把 SMARTS 收窄为真正 ketone，即 carbonyl C 两侧都是碳邻接且非酸/酯/酰胺。

### fragment_015 `carboxylic_acid`

- 当前 SMARTS：`[*:1][C:2](=[O:3])[OH:4]`
- 当前分类：`functional_group`
- 重算覆盖：period_hits=226（period_coverage=0.41%），source_hits=63（source_coverage=0.60%），match_total=337，max_per_period=2
- 文件内旧 `match_count`：337
- 当前 constraints：`exclude`
- overlap：exclusive_group=`carbonyl_family`，priority=50
- 结论：低频保留
- 分析：carboxylic_acid 命中低但语义明确。
- 风险：只覆盖 protonated acid，可能漏掉 carboxylate、盐型或数据中其它标准化状态。
- 处理方案：保留为低频核心；补充 carboxylate 或 acid_state 派生属性；priority 高于 hydroxyl 和 generic carbonyl。

### fragment_016 `four_membered_aliphatic_heterocycle_one_substituted`

- 当前 SMARTS：`[C,N,O,S;R:1]1([*:2])[C,N,O,S;R:3][C,N,O,S;R:4][C,N,O,S;R:5]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=162（period_coverage=0.29%），source_hits=56（source_coverage=0.54%），match_total=863，max_per_period=8
- 文件内旧 `match_count`：844
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：降级为派生属性
- 分析：四元脂肪环一取代规则覆盖低，且把取代数量写成独立核心片段。
- 风险：名称含 heterocycle，但 SMARTS 允许全碳环；取代位点由于环对称性容易重复或不稳定。
- 处理方案：不作为单独核心；改为 ring feature 的派生字段：`ring_size=4`、`aromatic=false`、`hetero_atom_signature`、`substitution_count=1`。

### fragment_017 `four_membered_aliphatic_heterocycle_two_substituted_first`

- 当前 SMARTS：`[C,N,O,S;R:1]1([*:2])[C,N,O,S;R:3]([*:4])[C,N,O,S;R:5][C,N,O,S;R:6]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=139（period_coverage=0.25%），source_hits=42（source_coverage=0.40%），match_total=1188，max_per_period=16
- 文件内旧 `match_count`：1174
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：降级为派生属性
- 分析：四元脂肪环二取代第一模式，属于取代模式枚举。
- 风险：取代位点编号未做 canonicalization，first/second 这类名称不稳定。
- 处理方案：不保留为核心；统一用 ring canonical position pattern 表达二取代模式。

### fragment_018 `four_membered_aliphatic_heterocycle_two_substituted_second`

- 当前 SMARTS：`[C,N,O,S;R:1]1([*:2])[C,N,O,S;R:3][C,N,O,S;R:4]([*:5])[C,N,O,S;R:6]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=150（period_coverage=0.27%），source_hits=48（source_coverage=0.46%），match_total=677，max_per_period=8
- 文件内旧 `match_count`：668
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：降级为派生属性
- 分析：四元脂肪环二取代第二模式，与 fragment_017 属同一类派生信息。
- 风险：按 SMARTS 单独枚举会受原子顺序和对称性影响，后续难以去重。
- 处理方案：合并进四元环派生属性；不要作为独立 core fragment。

### fragment_019 `four_membered_aliphatic_heterocycle_three_substituted`

- 当前 SMARTS：`[C,N,O,S;R:1]1([*:2])[C,N,O,S;R:3]([*:4])[C,N,O,S;R:5]([*:6])[C,N,O,S;R:7]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=138（period_coverage=0.25%），source_hits=41（source_coverage=0.39%），match_total=1938，max_per_period=32
- 文件内旧 `match_count`：1929
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：降级为派生属性
- 分析：四元脂肪环三取代规则属于 substitution pattern。
- 风险：match_total 相对 period_hits 放大明显，说明环对称匹配会产生多个等价实例。
- 处理方案：用 canonical substitution pattern 记录，不单独进入核心词表。

### fragment_020 `four_membered_aliphatic_heterocycle_four_substituted`

- 当前 SMARTS：`[C,N,O,S;R:1]1([*:2])[C,N,O,S;R:3]([*:4])[C,N,O,S;R:5]([*:6])[C,N,O,S;R:7]([*:8])1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=109（period_coverage=0.20%），source_hits=33（source_coverage=0.32%），match_total=796，max_per_period=16
- 文件内旧 `match_count`：796
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：降级为派生属性
- 分析：四元脂肪环四取代规则更适合作为 ring substitution attribute。
- 风险：语义不是新的化学片段，而是同一 ring scaffold 的取代状态。
- 处理方案：移出核心；在 ring match 后计算 `substitution_count=4` 和 normalized positions。

### fragment_021 `four_membered_aromatic_heterocycle_two_substituted_first`

- 当前 SMARTS：`[c,n,o,s;R:1]1([*:2])[c,n,o,s;R:3]([*:4])[c,n,o,s;R:5][c,n,o,s;R:6]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=12（period_coverage=0.02%），source_hits=1（source_coverage=0.01%），match_total=12，max_per_period=1
- 文件内旧 `match_count`：1174
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：删除或失败用例保留
- 分析：四元芳香杂环二取代第一模式在当前数据几乎不成立。
- 风险：category 写成 cycloaliphatic_ring，名称与类别矛盾；重算仅 12 个 period 命中且来自 1 个 source。
- 处理方案：不进入核心；如需追踪，放入 failed/rare cases，不参与候选扩展。

### fragment_022 `four_membered_aromatic_heterocycle_two_substituted_second`

- 当前 SMARTS：`[c,n,o,s;R:1]1([*:2])[c,n,o,s;R:3][c,n,o,s;R:4]([*:5])[c,n,o,s;R:6]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=0（period_coverage=0.00%），source_hits=0（source_coverage=0.00%），match_total=0，max_per_period=0
- 文件内旧 `match_count`：668
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：删除
- 分析：四元芳香杂环二取代第二模式当前 0 命中。
- 风险：规则、名称、类别都不稳定，保留会污染核心词表。
- 处理方案：从核心移除；不生成候选。

### fragment_023 `four_membered_aromatic_heterocycle_three_substituted`

- 当前 SMARTS：`[c,n,o,s;R:1]1([*:2])[c,n,o,s;R:3]([*:4])[c,n,o,s;R:5]([*:6])[c,n,o,s;R:7]1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=0（period_coverage=0.00%），source_hits=0（source_coverage=0.00%），match_total=0，max_per_period=0
- 文件内旧 `match_count`：1929
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：删除
- 分析：四元芳香杂环三取代当前 0 命中。
- 风险：同类四元芳香环规则缺少数据支持。
- 处理方案：从核心移除；若未来数据确有该类结构，再以专门规则新增。

### fragment_024 `four_membered_aromatic_heterocycle_four_substituted`

- 当前 SMARTS：`[c,n,o,s;R:1]1([*:2])[c,n,o,s;R:3]([*:4])[c,n,o,s;R:5]([*:6])[c,n,o,s;R:7]([*:8])1`
- 当前分类：`cycloaliphatic_ring`
- 重算覆盖：period_hits=0（period_coverage=0.00%），source_hits=0（source_coverage=0.00%），match_total=0，max_per_period=0
- 文件内旧 `match_count`：796
- 当前 constraints：无
- overlap：exclusive_group=`small_strained_ring_family`，priority=50
- 结论：删除
- 分析：四元芳香杂环四取代当前 0 命中。
- 风险：无当前数据支持，且取代模式不应作为核心片段枚举。
- 处理方案：从核心移除。

### fragment_025 `five_membered_aromatic_heterocycle`

- 当前 SMARTS：`[c,n,o,s;R:1]1[c,n,o,s;R:2][c,n,o,s;R:3][c,n,o,s;R:4][c,n,o,s;R:5]1`
- 当前分类：`aromatic_ring`
- 重算覆盖：period_hits=6296（period_coverage=11.43%），source_hits=1435（source_coverage=13.74%），match_total=10010，max_per_period=6
- 文件内旧 `match_count`：9763
- 当前 constraints：无
- overlap：exclusive_group=`aromatic_ring_family`，priority=50
- 结论：修正后保留
- 分析：五元芳香环覆盖充分，但名称写 heterocycle，SMARTS 并不要求必须有杂原子。
- 风险：会把全碳五元芳香环和真正五元杂芳环混在一起。
- 处理方案：改名为 `five_membered_aromatic_ring` 作为父级；用 `hetero_atom_signature` 和 `hetero_atom_count` 区分 heteroaromatic；取代模式作为派生属性。

### fragment_026 `vinylene_linkage`

- 当前 SMARTS：`[*:1][CX3H1:2]=[CX3H1:3][*:4]`
- 当前分类：`mainchain_linker`
- 重算覆盖：period_hits=3001（period_coverage=5.45%），source_hits=530（source_coverage=5.07%），match_total=4243，max_per_period=4
- 文件内旧 `match_count`：4209
- 当前 constraints：无
- overlap：exclusive_group=`unsaturated_linker_family`，priority=50
- 结论：保留
- 分析：vinylene linkage 语义明确，覆盖适中。
- 风险：当前 SMARTS 只说明 C=C-H，不保证一定处在主链。
- 处理方案：保留；通过 attachment/ownership 或 backbone_role 判定主链/侧链；必要时增加 E/Z 或 conjugation 派生属性。

### fragment_027 `ethynylene_linkage`

- 当前 SMARTS：`[*:1][CX2:2]#[CX2:3][*:4]`
- 当前分类：`mainchain_linker`
- 重算覆盖：period_hits=509（period_coverage=0.92%），source_hits=82（source_coverage=0.79%），match_total=955，max_per_period=6
- 文件内旧 `match_count`：955
- 当前 constraints：无
- overlap：exclusive_group=`unsaturated_linker_family`，priority=50
- 结论：低频保留
- 分析：ethynylene linkage 命中较低但主链语义强。
- 风险：可能把侧链炔基也当作 linker。
- 处理方案：保留为低频 linker；用 backbone_role 或 attachment path 过滤主链实例。

### fragment_028 `halogen_substituent`

- 当前 SMARTS：`[*:1][#6:2]-[F,Cl,Br,I:3]`
- 当前分类：`side_group`
- 重算覆盖：period_hits=6461（period_coverage=11.73%），source_hits=1659（source_coverage=15.88%），match_total=85570，max_per_period=87
- 文件内旧 `match_count`：85252
- 当前 constraints：`exclude_inorganic_halides`
- overlap：exclusive_group=`substituent_family`，priority=50
- 结论：修正后保留
- 分析：halogen substituent 语义明确，但在多卤和全氟结构中 match_total 极高。单个 period 最高 87 个 match 来自 `ru_000311` 的全氟长链结构；该 period 实际包含 36 个 F，但当前 SMARTS 统计出 87 个 match。
- 风险：当前 SMARTS 是 `[*]-C-X` 三原子模式，其中 `[*:1]` 可以匹配卤代碳上的任意其它邻居。在 `CF3` 或 `CF2` 结构中，同一个 C-F 键会因为 `[*]` 可选 R、另一个 F、再另一个 F 等邻居而产生组合放大。因此 `max_per_period=87` 不是 87 个独立卤素取代基，而是全氟/多卤结构叠加 wildcard 组合造成的重复计数。
- 处理方案：保留 halogen 父级，但把统计单位改成唯一 `C-X` bond，而不是当前 `[*]-C-X` match instance。核心 SMARTS 建议收窄为 `[#6:1]-[F,Cl,Br,I:2]`，并按 atom pair `(carbon_atom, halogen_atom)` 去重；如果仍保留三原子上下文，`[*:1]` 至少要排除 F/Cl/Br/I。输出 F/Cl/Br/I 分项计数，`exclude_inorganic_halides` 注册为可执行约束；与 CF3/perfluoro family 做 priority，优先级建议为 `perfluoroalkyl_segment > trifluoromethyl > fluoro_substituent > generic_halogen`。

### fragment_029 `trifluoromethyl`

- 当前 SMARTS：`[*:1][#6:2]-[C:3]([F:4])([F:5])[F:6]`
- 当前分类：`side_group`
- 重算覆盖：period_hits=3888（period_coverage=7.06%），source_hits=909（source_coverage=8.70%），match_total=22840，max_per_period=18
- 文件内旧 `match_count`：22769
- 当前 constraints：`exact_fluorine_count`, `exclude_perfluoroalkyl_chain`
- overlap：exclusive_group=`fluorinated_family`，priority=50
- 结论：修正后保留
- 分析：trifluoromethyl 是高价值含氟侧基。
- 风险：`exact_fluorine_count` 和 `exclude_perfluoroalkyl_chain` 如果不执行，会把长全氟链局部误当作独立 CF3。
- 处理方案：保留；把 exact F count 和 perfluoro chain 排除做成可执行 constraint；作为 fluorinated family 中高于 generic fluoro/halogen 的 child。

### fragment_030 `methyl`

- 当前 SMARTS：`[*:1][#6:2]-[CH3:3]`
- 当前分类：`side_group`
- 重算覆盖：period_hits=18204（period_coverage=33.06%），source_hits=3764（source_coverage=36.04%），match_total=79206，max_per_period=36
- 文件内旧 `match_count`：78948
- 当前 constraints：`exclude_methane`
- overlap：exclusive_group=`alkyl_substituent_family`，priority=50
- 结论：降级为派生属性
- 分析：methyl 覆盖很高，但化学解释力相对弱。
- 风险：容易把普通烷基端点、侧链、主链局部全部计入核心，稀释更有价值的结构特征。
- 处理方案：不作为核心解释片段；改为 side_group/alkyl 派生计数，或保留为低优先级辅助 feature。

### fragment_031 `diacylamine_linker`

- 当前 SMARTS：`[*:1][C:2](=[O:3])[N:4][C:5](=[O:6])[*:7]`
- 当前分类：`linker`
- 重算覆盖：period_hits=11348（period_coverage=20.61%），source_hits=1993（source_coverage=19.08%），match_total=21357，max_per_period=6
- 文件内旧 `match_count`：0
- 当前 constraints：无
- overlap：exclusive_group=`diacylamine_linker_family`，priority=50
- 结论：合并到 fragment_002
- 分析：diacylamine_linker 与 imide 命中统计完全一致，实际是 imide 的 linker 命名版本。
- 风险：作为独立核心会和 fragment_002 重复；文件内 match_count 写 0 也是旧统计口径问题。
- 处理方案：删除独立核心 ID；并入 imide。若需要主链 linker 语义，用 `backbone_role`/attachment 派生，不另写一条 SMARTS。

### fragment_032 `secondary_amine_linker`

- 当前 SMARTS：`[*:1][NH:2][*:3]`
- 当前分类：`linker`
- 重算覆盖：period_hits=20794（period_coverage=37.77%），source_hits=2560（source_coverage=24.51%），match_total=42737，max_per_period=8
- 文件内旧 `match_count`：0
- 当前 constraints：无
- overlap：exclusive_group=`secondary_amine_linker_family`，priority=50
- 结论：修正后保留
- 分析：secondary_amine_linker 覆盖较高，具备 linker 语义。
- 风险：当前 `[NH]` 会与 amide/urethane/urea 等 N-H 环境重叠；也未证明一定在主链。
- 处理方案：保留概念但收窄：排除 carbonyl-adjacent N，或让 carbonyl-N 规则优先；用 backbone_role 判断 linker。

### fragment_033 `azo_linker`

- 当前 SMARTS：`[*:1][N:2]=[N:3][*:4]`
- 当前分类：`linker`
- 重算覆盖：period_hits=1719（period_coverage=3.12%），source_hits=282（source_coverage=2.70%），match_total=2167，max_per_period=3
- 文件内旧 `match_count`：0
- 当前 constraints：无
- overlap：exclusive_group=`azo_linker_family`，priority=50
- 结论：保留
- 分析：azo linker 语义明确，覆盖充分。
- 风险：可能需要处理 E/Z 或芳香偶氮与脂肪偶氮的子类型。
- 处理方案：保留；增加 azo_subtype 或邻接环境派生属性；priority 高于 generic amine/nitrogen feature。

### fragment_034 `ester_linker`

- 当前 SMARTS：`[*:1][C:2](=[O:3])[O:4][*:5]`
- 当前分类：`linker`
- 重算覆盖：period_hits=21707（period_coverage=39.42%），source_hits=3455（source_coverage=33.08%），match_total=44034，max_per_period=8
- 文件内旧 `match_count`：0
- 当前 constraints：无
- overlap：exclusive_group=`ester_linker_family`，priority=50
- 结论：合并到 fragment_003
- 分析：ester_linker 与 ester 命中统计完全一致，是同一 SMARTS 的 linker 命名版本。
- 风险：独立保留会造成重复核心片段；文件内 match_count 为 0 是旧统计未更新。
- 处理方案：删除独立核心 ID；并入 ester。主链 linker 信息由 `backbone_role` 或 attachment path 计算。

### fragment_035 `six_membered_aromatic_heterocycle`

- 当前 SMARTS：`[C,N,O,S,c,n,o,s;R:1]1[C,N,O,S,c,n,o,s;R:2][C,N,O,S,c,n,o,s;R:3][C,N,O,S,c,n,o,s;R:4][C,N,O,S,c,n,o,s;R:5][C,N,O,S,c,n,o,s;R:6]1`
- 当前分类：`aromatic_ring`
- 重算覆盖：period_hits=42931（period_coverage=77.97%），source_hits=7936（source_coverage=75.99%），match_total=167375，max_per_period=20
- 文件内旧 `match_count`：161069
- 当前 constraints：无
- overlap：exclusive_group=`aromatic_ring_family`，priority=50
- 结论：拆分重建
- 分析：名称是六元芳香杂环，但 SMARTS 允许大写/小写 C/N/O/S，因此实际是非常宽的六元环规则。
- 风险：覆盖极高，会混入苯环、杂芳环、脂肪环以及混合情况；不能直接代表 six_membered_aromatic_heterocycle。
- 处理方案：不要按当前规则保留。拆成 `six_membered_aromatic_ring`、`six_membered_heteroaromatic_ring`、`six_membered_aliphatic_ring`，并用 substitution/attachment/hetero signature 记录派生属性。

### fragment_036 `five_membered_aromatic_heterocycle`

- 当前 SMARTS：`[C,N,O,S,c,n,o,s;R:1]1[C,N,O,S,c,n,o,s;R:2][C,N,O,S,c,n,o,s;R:3][C,N,O,S,c,n,o,s;R:4][C,N,O,S,c,n,o,s;R:5]1`
- 当前分类：`aromatic_ring`
- 重算覆盖：period_hits=19585（period_coverage=35.57%），source_hits=3857（source_coverage=36.93%），match_total=36088，max_per_period=9
- 文件内旧 `match_count`：9763
- 当前 constraints：无
- overlap：exclusive_group=`aromatic_ring_family`，priority=50
- 结论：拆分重建
- 分析：不按名称判断时，`fragment_025` 是全芳香 5 元环，SMARTS 只允许小写 `c,n,o,s`；`fragment_036` 同时允许大写 `C,N,O,S` 和小写 `c,n,o,s`，因此 036 是 025 的超集。当前统计中 025 的 6296 个 period 命中全部被 036 覆盖，025-only 为 0，036-only 为 13289 个 period。
- 风险：当前 036 把三类结构混在一起：全芳香 5 元环、全非芳香 5 元环、以及稠合体系中的 mixed aromatic/non-aromatic 5 元环。这样会与 025 完全重叠，并且让“5 元环”这个核心片段语义不稳定。
- 处理方案：036 不应继续使用 `[C,N,O,S,c,n,o,s]` 全包规则。若要和 025 不重合，建议把 036 改成严格非芳香 5 元环：`[C,N,O,S;R:1]1[C,N,O,S;R:2][C,N,O,S;R:3][C,N,O,S;R:4][C,N,O,S;R:5]1`，重算覆盖约为 period_hits=2340、source_hits=531、match_total=4359。mixed fused 5 元环如果需要保留，应另建 `five_membered_mixed_fused_ring` 或作为派生属性，由实例级过滤判定 `not_all_aromatic=true` 且 `not_all_aliphatic=true`。

## 5. 建议的落地顺序

1. 先把核心词表分成三类：生产核心、派生属性规则、废弃/failed cases。
2. 从核心 JSON 移除 `match_count`，新增独立 `base_fragment_new2_match_stats.csv/json`，记录本报告里的 period/source/match 统计。
3. 建立 constraint registry：所有 constraint key 必须注册，未知 key 构建时 fail-fast 或进入 invalid rule report。
4. 实现 match-instance 级过滤：先跑 SMARTS，再按当前 match 的 atom map、邻接环境、overlap priority 做二次过滤。
5. 对环类片段改为 ring scaffold + derived attributes，不继续用多条核心 SMARTS 枚举取代数量和取代位置。
6. 合并重复片段：`fragment_031 -> fragment_002`，`fragment_034 -> fragment_003`；`fragment_036` 按 SMARTS 拆成非芳香 5 元环和可选 mixed fused 5 元环，不再覆盖 `fragment_025` 的全芳香 5 元环。
7. 重新生成候选词表，并输出每个候选的 parent fragment、period_hits、source_hits、match_total、过滤原因和最终状态。

## 6. 下一步可直接修改的对象

- `fragments_1/base_fragment_new2.json`：只保留生产核心规则，删除或迁移重复/派生/failed 规则。
- `fragments_1/base_fragment_new2_match_stats.*`：新增统计产物，承载所有 match count。
- `fragments_1/base_fragment_new2_derived_schema.json`：新增 ring/substitution/backbone/hetero signature 等派生属性定义。
- 候选构建脚本：基于修正后的核心词表重新生成候选，而不是继续沿用当前混合核心。
