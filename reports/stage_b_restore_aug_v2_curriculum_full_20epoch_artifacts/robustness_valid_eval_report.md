# Stage B Restore Curriculum Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `valid`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- decoded sample count: `4632`
- sample count: `4632`

## Row-Level Overall

| metric | value |
|---|---:|
| `canonical_match` | `0.47085492227979275` |
| `rdkit_validity` | `0.7122193436960277` |
| `two_attachment_validity` | `0.7074697754749568` |
| `exact_string_match` | `0.46718480138169255` |
| `loss` | `0.20451573082665372` |
| `token_accuracy` | `0.9579246722431998` |

## Strategy-Level Robustness

| strategy | sample_count | canonical_match | rdkit_validity | two_attachment_validity | exact_string_match | failed_count |
|---|---:|---:|---:|---:|---:|---:|
| `attachment_rooted_smiles` | `1158` | `0.6113989637305699` | `0.768566493955095` | `0.7633851468048359` | `0.6053540587219344` | `450` |
| `direction_flip` | `1158` | `0.4265975820379965` | `0.689119170984456` | `0.6848013816925734` | `0.4231433506044905` | `664` |
| `light_denoise` | `1158` | `0.4430051813471503` | `0.7150259067357513` | `0.7115716753022453` | `0.4430051813471503` | `645` |
| `rdkit_random_smiles` | `1158` | `0.40241796200345425` | `0.6761658031088082` | `0.6701208981001727` | `0.39723661485319517` | `692` |

## Aggregates

| aggregate | value |
|---|---:|
| `strategy_macro_avg.canonical_match` | `0.47085492227979275` |
| `strategy_macro_avg.rdkit_validity` | `0.7122193436960276` |
| `strategy_macro_avg.two_attachment_validity` | `0.7074697754749568` |
| `strategy_macro_avg.exact_string_match` | `0.4671848013816926` |
| `record_all_views_success` | `219/1158 = 0.18911917098445596` |
| `record_any_view_success` | `860/1158 = 0.7426597582037997` |
| `record_partial_success` | `641/1158 = 0.5535405872193437` |
