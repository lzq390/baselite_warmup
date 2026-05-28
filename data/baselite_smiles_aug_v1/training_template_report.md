# BaseLite Stage A Restore 增强模板预览报告

- 生成时间 UTC: `2026-05-28T00:51:52.205308+00:00`
- tokenizer 路径: `/home/hongchang/lzq/gith/baselite_warmup-test/models/qwen2.5-7b-tokenizer`
- tokenizer class: `Qwen2Tokenizer`
- eos token: `<|endoftext|>` / `151643`
- augmentation policy: `restore_aug_v1`

## Stage A 增强口径

- 本阶段只生成 restore-only 增强模板，不训练模型。
- target 单独 tokenize 为 `restore_labels`，不拼入 `input_text_view1`。
- 不生成 `text_view_2`，不接 fragment vocab / fragment labels。
- Stage B train 每个 record 物化四个 view；Stage C train 每个 record 只保留一个稳定 view，避免 InfoNCE false negative。
- valid/test 主模板保持 identity；鲁棒性评估单独写入 `robustness_eval_preview.jsonl`。

## 输出文件

- `training_preview_jsonl`: `data/baselite_smiles_aug_v1/training_template_preview.jsonl`
- `stage_c_training_preview_jsonl`: `data/baselite_smiles_aug_v1/stage_c_training_template_preview.jsonl`
- `robustness_eval_preview_jsonl`: `data/baselite_smiles_aug_v1/robustness_eval_preview.jsonl`
- `augmentation_failures_jsonl`: `data/baselite_smiles_aug_v1/augmentation_failures.jsonl`
- `stats_json`: `data/baselite_smiles_aug_v1/training_template_stats.json`
- `report_md`: `data/baselite_smiles_aug_v1/training_template_report.md`

## 预览集统计

### training

- total: `39372`
- train/valid/test: `37056` / `1158` / `1158`
- strategy counts: `{'attachment_rooted_smiles': 9264, 'identity': 11580, 'light_denoise': 9264, 'rdkit_random_smiles': 9264}`
- validity counts: `{'rdkit_valid': {'true': 30108, 'false': 0, 'unknown': 9264}, 'two_attachment_valid': {'true': 39372, 'false': 0, 'unknown': 0}}`

| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 37056 | 46 | 87 | 98 | 123 | 274 | 32 | 71 | 82 | 105 | 221 |
| valid | 1158 | 46 | 84 | 95 | 123 | 166 | 32 | 70 | 81 | 109 | 152 |
| test | 1158 | 48 | 85 | 98 | 120 | 381 | 34 | 71 | 84 | 106 | 367 |

- view template round-trip failures: `0`
- restore label round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

| split | RDKit valid T/F/? | two attachment T/F/? | duplicate record_id |
|---|---:|---:|---:|
| train | 27792/0/9264 | 37056/0/0 | 27792 |
| valid | 1158/0/0 | 1158/0/0 | 0 |
| test | 1158/0/0 | 1158/0/0 | 0 |

### stage_c_training

- total: `11580`
- train/valid/test: `9264` / `1158` / `1158`
- strategy counts: `{'attachment_rooted_smiles': 1824, 'identity': 5123, 'light_denoise': 1804, 'rdkit_random_smiles': 2829}`
- validity counts: `{'rdkit_valid': {'true': 9776, 'false': 0, 'unknown': 1804}, 'two_attachment_valid': {'true': 11580, 'false': 0, 'unknown': 0}}`

| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 9264 | 46 | 86 | 98 | 121 | 277 | 32 | 71 | 82 | 104 | 221 |
| valid | 1158 | 46 | 84 | 95 | 123 | 166 | 32 | 70 | 81 | 109 | 152 |
| test | 1158 | 48 | 85 | 98 | 120 | 381 | 34 | 71 | 84 | 106 | 367 |

- view template round-trip failures: `0`
- restore label round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

| split | RDKit valid T/F/? | two attachment T/F/? | duplicate record_id |
|---|---:|---:|---:|
| train | 7460/0/1804 | 9264/0/0 | 0 |
| valid | 1158/0/0 | 1158/0/0 | 0 |
| test | 1158/0/0 | 1158/0/0 | 0 |

### robustness_eval

- total: `4632`
- train/valid/test: `0` / `2316` / `2316`
- strategy counts: `{'light_denoise': 2316, 'rdkit_random_smiles': 2316}`
- validity counts: `{'rdkit_valid': {'true': 2316, 'false': 0, 'unknown': 2316}, 'two_attachment_valid': {'true': 4632, 'false': 0, 'unknown': 0}}`

| split | count | view p50 | view p90 | view p95 | view p99 | view max | restore p50 | restore p90 | restore p95 | restore p99 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| valid | 2316 | 47 | 87 | 99 | 126 | 184 | 32 | 70 | 81 | 112 | 152 |
| test | 2316 | 50 | 89 | 101 | 128 | 378 | 34 | 72 | 84 | 109 | 367 |

- view template round-trip failures: `0`
- restore label round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

| split | RDKit valid T/F/? | two attachment T/F/? | duplicate record_id |
|---|---:|---:|---:|
| train | 0/0/0 | 0/0/0 | 0 |
| valid | 1158/0/1158 | 2316/0/0 | 1158 |
| test | 1158/0/1158 | 2316/0/0 | 1158 |

## 增强失败记录

- count: `0`
