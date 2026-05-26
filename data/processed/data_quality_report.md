# fragment_vocab_v1 数据质量报告

- 生成时间 UTC: `2026-05-26T01:03:13.461161+00:00`
- 源数据: `/home/lzq390/gith/baselite_warmup/data/all_polymers_experiment_final.csv`
- 源数据 SHA256: `f597f846ff06a8fd43fa48480009c195c22105583a55e6d01a4611cef6235a57`
- CSV 行数: `64071`
- RDKit 版本: `2026.03.1`

## 去重层级统计

- level 1 raw unique: `23956`
- level 1 文本排除后的两连接点主候选 raw unique: `23791`
- level 2 attachment 统一后的主构建 unique: `12184`
- level 3 canonical repeat-unit unique: `11580`
- level 4 repeat-unit graph hash unique: `11439`
- level 5 primitive periodic graph hash unique: `未实现`

## 记录类型统计

- copolymer_candidate: `47`（共聚物或多 repeat-unit 候选）
- incomplete_attachment: `6`（连接点不完整样本）
- ionomer_or_multicomponent_candidate: `5`（离子/盐/多组分候选）
- main_repeat_unit: `23791`（主构建 repeat-unit 样本）
- monomer_or_descriptor_record: `105`（小分子/单体/描述符记录，不进入主词表）
- unresolved_R_group: `2`（未定义 R 基样本）
