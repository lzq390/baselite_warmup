# fragment_vocab_v1.0 验证报告

- 生成时间 UTC: `2026-05-27T07:07:19.985118+00:00`
- 源数据 SHA256: `f597f846ff06a8fd43fa48480009c195c22105583a55e6d01a4611cef6235a57`
- RDKit 版本: `2026.03.2`
- 覆盖率分母层级: `level_3_canonical_repeat_unit_unique`
- 覆盖率分母数量: `11580`

## 规则可执行性

- seed 规则数: `70`
- 有效 seed 规则数: `70`
- 无效规则数: `0`
- 规则编译成功率: `1.0000`
- 最终核心规则数: `59`
- 因低频未进入核心的规则数: `11`

## 覆盖率

- 至少匹配 1 个 fragment 的 polymer 数: `11577`
- 至少匹配 1 个 fragment 的比例: `0.9997`
- 每个 polymer 平均 fragment 类型数: `9.1103`
- 每个 polymer 的 fragment 类型数中位数: `8.0`
- 至少有一次命中的规则数: `59`

## Motif 挖掘

- 写出的 mined candidate 数: `300`
- mined candidate 只作为人工审核候选保留；只有补齐稳定 anchor SMARTS 规则后才会提升到核心词表。

## 稳定性

- cut-shift 稳定性: `未评估`
- 边界归属准确率: `未评估`
- 原因：当前仓库此前没有物化的 periodic repeat-unit graph builder 和 cut-shift scanner。本次生成的核心词表已经保留匹配器所需的 schema 字段。

## 重叠与冲突

- 高重叠规则对数量: `116`
- 同 exclusive group 内冲突数量: `62`

## 覆盖率最高的核心 fragments

- RING_AROMATIC_6: `8193` (0.7075)
- LINK_ALKYL: `8029` (0.6934)
- FG_CARBONYL: `8001` (0.6909)
- LINK_METHYLENE: `7487` (0.6465)
- FG_ETHER: `6836` (0.5903)
- LINK_PHENYLENE_PARA: `6172` (0.5330)
- SUB_ALKOXY: `4375` (0.3778)
- FG_AMIDE: `4366` (0.3770)
- SUB_METHYL: `4104` (0.3544)
- FG_ESTER: `3924` (0.3389)
- RING_FUSED_AROMATIC_ATOM: `3536` (0.3054)
- COMP_AROMATIC_AMIDE_N: `2815` (0.2431)
- COMP_AROMATIC_AMIDE_C: `2753` (0.2377)
- FG_TERTIARY_AMINE: `2556` (0.2207)
- FG_SECONDARY_AMINE: `2480` (0.2142)
- FG_IMIDE: `2220` (0.1917)
- RING_LACTAM: `2218` (0.1915)
- COMP_CONJUGATED_AROMATIC_PAIR: `2204` (0.1903)
- RING_IMIDE: `2186` (0.1888)
- FG_AROMATIC_ETHER: `2185` (0.1887)
- COMP_AROMATIC_IMIDE: `1887` (0.1630)
- SUB_HALOGEN: `1762` (0.1522)
- RING_HETEROAROMATIC_5: `1521` (0.1313)
- SUB_FLUORO: `1304` (0.1126)
- SUB_ETHYL: `1168` (0.1009)
