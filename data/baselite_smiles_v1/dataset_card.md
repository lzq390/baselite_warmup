# BaseLite SMILES v1 数据集卡

本数据集包用于 BaseLite SMILES-only 恢复训练 / warmup 训练。

## 预期用途

- 从 canonical repeat-unit SMILES 生成输入视图。
- 训练模型从扰动视图恢复 canonical SMILES。
- 支持 tokenizer 构建和序列长度分析。

## 不包含内容

- 性质标签。
- fragment instances。
- fragment presence labels。

## 字段说明

| 字段 | 含义 |
|---|---|
| `record_id` | 稳定的 repeat-unit 记录 ID。 |
| `canonical_smiles` | RDKit canonical 后的 repeat-unit SMILES。 |
| `canonical_hash` | canonical SMILES 的稳定哈希，用于追溯和去重检查。 |
| `graph_hash` | 当前 graph signature hash，用于 split 分组和防泄漏检查。 |
| `split` | 数据划分，取值为 train、valid 或 test。 |

## 数量统计

- 总记录数: `11580`
- train: `9264`
- valid: `1158`
- test: `1158`
- 划分单元: `graph_hash`
