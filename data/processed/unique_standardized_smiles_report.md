# 唯一标准化 SMILES 导出报告

- 生成时间 UTC: `2026-05-06T06:48:26.186025+00:00`
- 源文件: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\all_polymers_experiment_final.csv`
- 源文件 SHA256: `f597f846ff06a8fd43fa48480009c195c22105583a55e6d01a4611cef6235a57`
- RDKit 版本: `2026.03.1`
- 输出 CSV: `\\wsl.localhost\Ubuntu\home\lzq390\gith\baselite_warmup\data\processed\unique_standardized_smiles.csv`

## 结论

- 已导出标准化 SMILES 数量: `11580`
- 导出 CSV 中唯一 `standardized_smiles` 数量: `11580`
- 是否存在重复标准化 SMILES: `False`
- 与既有 `canonical_repeat_units.jsonl` 数量是否一致: `True`
- 与既有 `canonical_repeat_units.jsonl` SMILES 集合是否一致: `True`

## 标准化过程

1. 读取原始 CSV，并按 raw `smiles` 字符串聚合 long-format 属性记录。
2. 对 raw unique string 做 record type 分类，只保留恰好两个 attachment point 且不含多组分、共聚物拼接和未定义 R 基的主构建样本。
3. 执行 attachment 文本统一：`[[[*]]] -> *`、`[[*]] -> *`、`[*] -> *`、`[*:1] -> *`、`[*:2] -> *`，以及通用 `[*:n] -> *`。
4. 对 attachment-normalized 主构建 unique SMILES 使用 RDKit `MolFromSmiles` 解析。
5. 使用 RDKit `MolToSmiles(..., canonical=True, isomericSmiles=True)` 生成 canonical repeat-unit string。
6. 按 canonical repeat-unit string 去重，得到最终唯一标准化 SMILES。

## 数量链路

- CSV 总行数: `64071`
- raw unique polymer strings: `23956`
- 非主构建 raw unique 数量: `165`
- 两连接点 main repeat-unit raw candidates: `23791`
- attachment-normalized main unique: `12184`
- attachment normalization 合并数量: `11607`
- RDKit canonical repeat-unit unique: `11580`
- RDKit canonicalization 合并数量: `604`
- RDKit 解析失败数量: `0`

## raw `*` 数量分布

### CSV 行级分布

- `0` 个 `*`: `13646` 行
- `1` 个 `*`: `6` 行
- `2` 个 `*`: `48465` 行
- `4` 个 `*`: `1954` 行

### raw unique 分布

- `0` 个 `*`: `105` 个 raw unique
- `1` 个 `*`: `6` 个 raw unique
- `2` 个 `*`: `23798` 个 raw unique
- `4` 个 `*`: `47` 个 raw unique

## record type 统计

- `copolymer_candidate`: `47`
- `incomplete_attachment`: `6`
- `ionomer_or_multicomponent_candidate`: `5`
- `main_repeat_unit`: `23791`
- `monomer_or_descriptor_record`: `105`
- `unresolved_R_group`: `2`

## 输出 CSV 字段

- `canonical_id`: 当前导出中的稳定行 ID。
- `standardized_smiles`: RDKit canonical 后的唯一标准化 repeat-unit SMILES。
- `canonical_hash`: `standardized_smiles` 的 SHA256。
- `graph_hash`: 当前脚本生成的粗略 graph signature hash，只作参考，不等同于生产级 canonical graph hash。
- `source_level2_count`: 合并到该 canonical SMILES 的 attachment-normalized unique 数量。
- `attachment_normalized_smiles_examples`: 该 canonical SMILES 对应的 level 2 示例。
- `raw_smiles_examples`: 该 canonical SMILES 对应的原始 SMILES 示例。

## failed cases 摘要

- `phase_0_cleaning`: `13`
