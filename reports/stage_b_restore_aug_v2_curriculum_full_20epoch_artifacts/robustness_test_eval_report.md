# Stage B Restore Curriculum Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- decoded sample count: `4632`
- sample count: `4632`

## Row-Level Overall

| metric | value |
|---|---:|
| `canonical_match` | `0.46545768566493956` |
| `rdkit_validity` | `0.6990500863557858` |
| `two_attachment_validity` | `0.6962435233160622` |
| `exact_string_match` | `0.46286701208981` |
| `loss` | `0.2104808139452077` |
| `token_accuracy` | `0.957252145148106` |

## Strategy-Level Robustness

| strategy | sample_count | canonical_match | rdkit_validity | two_attachment_validity | exact_string_match | failed_count |
|---|---:|---:|---:|---:|---:|---:|
| `attachment_rooted_smiles` | `1158` | `0.6001727115716753` | `0.7607944732297064` | `0.7556131260794473` | `0.5984455958549223` | `463` |
| `direction_flip` | `1158` | `0.3946459412780656` | `0.655440414507772` | `0.6528497409326425` | `0.3903281519861831` | `701` |
| `light_denoise` | `1158` | `0.45509499136442144` | `0.7115716753022453` | `0.7107081174438687` | `0.4542314335060449` | `631` |
| `rdkit_random_smiles` | `1158` | `0.4119170984455959` | `0.6683937823834197` | `0.6658031088082902` | `0.40846286701208984` | `681` |

## Aggregates

| aggregate | value |
|---|---:|
| `strategy_macro_avg.canonical_match` | `0.46545768566493956` |
| `strategy_macro_avg.rdkit_validity` | `0.6990500863557858` |
| `strategy_macro_avg.two_attachment_validity` | `0.6962435233160622` |
| `strategy_macro_avg.exact_string_match` | `0.46286701208981` |
| `record_all_views_success` | `219/1158 = 0.18911917098445596` |
| `record_any_view_success` | `844/1158 = 0.7288428324697754` |
| `record_partial_success` | `625/1158 = 0.5397236614853195` |
