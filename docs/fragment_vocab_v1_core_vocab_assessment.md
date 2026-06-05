# fragment_vocab_v1.0 核心片段评估报告

生成时间：2026-05-27

## 结论摘要

当前 `fragments/vocab/fragment_vocab_v1.0.jsonl` 包含 59 条核心词表规则。上一版中 `COMP_AROMATIC_ETHER` 与 `FG_AROMATIC_ETHER` 使用完全相同的 SMARTS，本轮已移除重复的 `COMP_AROMATIC_ETHER`，保留 `FG_AROMATIC_ETHER` 作为唯一 aromatic ether 核心规则。

当前 v1.0 仍应被理解为高覆盖、层级化的 fragment feature vocabulary，而不是 59 个互斥片段。验证报告显示仍有 116 对高重叠规则，其中 62 对位于同一 exclusive group 内，后续使用仍必须依赖 hierarchy / priority / overlap resolver。

## 当前统计

- 核心规则数：59
- seed 规则数：70
- 有效 seed 规则数：70
- 覆盖率分母：11580 个 level_3 canonical repeat-unit
- 至少命中一个 fragment 的 polymer 数：11577
- 至少命中一个 fragment 的比例：0.9997
- 每个 polymer 平均 fragment 类型数：9.1103
- 每个 polymer fragment 类型数中位数：8.0
- 有命中的核心规则数：59
- 高重叠规则对数量：116
- 同 exclusive group 内冲突数量：62

## 已修复项

- 移除 `COMP_AROMATIC_ETHER`，解决它与 `FG_AROMATIC_ETHER` 的完全重复 SMARTS 问题。
- 同步更新 `fragments/vocab/fragment_vocab_v1.0.json`、`.jsonl`、`.stats.json`、examples、coverage、overlap、review 和 validation 报告。
- `fragments/validation/overlap_report.json` 中已无任何包含 `COMP_AROMATIC_ETHER` 的 overlap pair。

## 仍需 Resolver 处理的问题

- `FG_CARBONYL` 与 `FG_ESTER`、`FG_AMIDE`、`FG_IMIDE`、`FG_URETHANE`、`FG_UREA` 等存在父子重叠。
- `FG_IMIDE`、`RING_IMIDE`、`RING_LACTAM` 仍高度重叠，需要按具体度和 ring role 裁决。
- `SUB_HALOGEN`、`SUB_FLUORO`、`SUB_CHLORO`、`SUB_BROMO`、`SUB_TRIFLUOROMETHYL`、`COMP_PERFLUOROALKYL` 属于 halogen family 层级关系，不能平铺解释。
- `LINK_ALKYL`、`LINK_METHYLENE`、`SUB_METHYL`、`SUB_ETHYL` 等 alkyl 规则更多是辅助统计/roll-up feature，不适合作为最终解释里的最具体片段。
- `RING_AROMATIC_6`、`LINK_PHENYLENE_PARA`、`RING_FUSED_AROMATIC_ATOM` 仍需要 ring-level matcher 或 attachment-aware 过滤。

## 使用建议

1. 输出解释性片段时，先按 exclusive group 和 priority 保留更具体规则，再把父级规则作为 roll-up tag。
2. 对 carbonyl、halogen、ring、alkyl/linker family 建立实例级 suppression，而不是仅看 molecule-level coverage。
3. `fragment_vocab_v1.0` 可作为高覆盖特征词表继续使用；如果目标是少量互斥核心片段，应在 59 条上再筛出 active core 子集。
