# BaseLite Stage B Restore v2 五层增强模板报告

- 生成时间 UTC: `2026-06-01T06:34:42.220874+00:00`
- augmentation policy: `restore_aug_v2`
- tokenizer: `models/qwen2.5-7b-tokenizer`
- direction_flip source: `data/baselite_smiles_aug_sources/training_template_preview_direction_flip.jsonl`
- direction_flip sha256: `21d8ce48b79a5e2c5b377a609fdd987b40f082aa5cdb22a20ebe5fce0cfbe06e`

## 五层干扰强度

| level | strategy | meaning |
|---:|---|---|
| 1 | `identity` | `identity` |
| 2 | `rdkit_random_smiles` | `equivalent_random_smiles` |
| 3 | `direction_flip` | `direction_flip_equivalent` |
| 4 | `attachment_rooted_smiles` | `attachment_rooted_equivalent` |
| 5 | `light_denoise` | `light_denoise` |

## 输出文件

- `training_preview_jsonl`: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- `robustness_eval_preview_jsonl`: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- `augmentation_failures_jsonl`: `data/baselite_smiles_aug_v2/augmentation_failures.jsonl`
- `input_label_conflict_audit_jsonl`: `data/baselite_smiles_aug_v2/input_label_conflict_audit.jsonl`
- `distinct_view_audit_jsonl`: `data/baselite_smiles_aug_v2/distinct_view_audit.jsonl`
- `stats_json`: `data/baselite_smiles_aug_v2/training_template_stats.json`
- `report_md`: `data/baselite_smiles_aug_v2/training_template_report.md`

## 预览统计

### training

- total: `57900`
- train/valid/test: `46320` / `5790` / `5790`
- strategy counts: `{'attachment_rooted_smiles': 11580, 'direction_flip': 11580, 'identity': 11580, 'light_denoise': 11580, 'rdkit_random_smiles': 11580}`
- validity counts: `{'rdkit_valid': {'true': 46320, 'false': 0, 'unknown': 11580}, 'two_attachment_valid': {'true': 57900, 'false': 0, 'unknown': 0}, 'canonical_match': {'true': 46320, 'false': 0, 'unknown': 11580}}`

| split | count | identity | random | direction | attachment | denoise | view p50 | view p95 | view max | restore p50 | restore p95 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 46320 | 9264 | 9264 | 9264 | 9264 | 9264 | 46 | 98 | 241 | 32 | 82 | 221 |
| valid | 5790 | 1158 | 1158 | 1158 | 1158 | 1158 | 46 | 97 | 189 | 32 | 81 | 152 |
| test | 5790 | 1158 | 1158 | 1158 | 1158 | 1158 | 48 | 99 | 427 | 34 | 84 | 367 |

- view round-trip failures: `0`
- restore round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

### robustness_eval

- total: `9264`
- train/valid/test: `0` / `4632` / `4632`
- strategy counts: `{'attachment_rooted_smiles': 2316, 'direction_flip': 2316, 'light_denoise': 2316, 'rdkit_random_smiles': 2316}`
- validity counts: `{'rdkit_valid': {'true': 6948, 'false': 0, 'unknown': 2316}, 'two_attachment_valid': {'true': 9264, 'false': 0, 'unknown': 0}, 'canonical_match': {'true': 6948, 'false': 0, 'unknown': 2316}}`

| split | count | identity | random | direction | attachment | denoise | view p50 | view p95 | view max | restore p50 | restore p95 | restore max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| valid | 4632 | 0 | 1158 | 1158 | 1158 | 1158 | 46 | 98 | 189 | 32 | 81 | 152 |
| test | 4632 | 0 | 1158 | 1158 | 1158 | 1158 | 48 | 100 | 427 | 34 | 84 | 367 |

- view round-trip failures: `0`
- restore round-trip failures: `0`
- view length overflow: `0`
- restore label length overflow: `0`
- mask failures: `0`

## Input -> Label 冲突处理

- policy: `retry_non_self_light_denoise_until_unambiguous`
- initial conflict groups: `187`
- final conflict groups: `0`
- retried rows: `202`
- retry total attempts: `256`
- retry max attempt: `4`

## 同 Record View 去重

- policy: `retry_seed_or_root_then_bracket_attachment_surface_variant`
- duplicate record count: `0`
- unique view count distribution: `{5: 11580}`
- retry count by strategy: `{'attachment_rooted_smiles': 11465, 'rdkit_random_smiles': 133}`
- surface variant count by strategy: `{'attachment_rooted_smiles': 4, 'rdkit_random_smiles': 1}`
- duplicate pair counts: `{}`

## 增强失败记录

- count: `0`
