# BaseLite SMILES v1 数据集划分报告

- 生成时间 UTC: `2026-05-07T03:20:35.979943+00:00`
- 输入文件: `/home/lzq390/gith/baselite_warmup/data/processed/canonical_repeat_units.jsonl`
- 输入文件 SHA256: `3ef7257eb0b348bb5bfd05cc7429cd9474117c43c2dcec8cb67e04f9806305b0`
- 划分单元: `graph_hash`
- 划分种子: `baselite_smiles_v1_split_seed_2026_05_07`
- 字段 schema: `record_id, canonical_smiles, canonical_hash, graph_hash, split`

## 数量统计

- 总记录数: `11580`
- train: `9264`
- valid: `1158`
- test: `1158`
- 唯一 canonical_hash 数: `11580`
- 唯一 graph_hash 数: `11439`

## 泄漏检查

- canonical_hash 跨 split 成对泄漏数: `0`
- graph_hash 跨 split 成对泄漏数: `0`

## 输出文件

- `train.jsonl`
- `valid.jsonl`
- `test.jsonl`
- `dataset_manifest.json`
- `dataset_card.md`
- `split_report.md`

## 说明

- 本数据集是 SMILES-only 训练数据集。
- 不包含性质字段。
- 不包含 fragment 匹配字段。
- 上游仅用于审计的合并来源计数不进入 train/valid/test JSONL。
