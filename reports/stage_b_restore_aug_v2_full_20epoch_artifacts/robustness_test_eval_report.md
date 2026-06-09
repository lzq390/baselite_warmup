# Stage B Restore Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- precision: `bf16`

## Metrics

- `loss`: `0.22145385389412023`
- `token_accuracy`: `0.9558558974267082`
- `exact_string_match`: `0.45682210708117443`
- `rdkit_validity`: `0.7113557858376511`
- `two_attachment_validity`: `0.7091968911917098`
- `canonical_match`: `0.4596286701208981`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 464, 'exact_string_match': 0.5967184801381693, 'rdkit_validity': 0.7607944732297064, 'two_attachment_validity': 0.7607944732297064, 'canonical_match': 0.5993091537132987}, 'direction_flip': {'sample_count': 1158, 'failed_count': 707, 'exact_string_match': 0.38773747841105355, 'rdkit_validity': 0.6735751295336787, 'two_attachment_validity': 0.6709844559585493, 'canonical_match': 0.38946459412780654}, 'light_denoise': {'sample_count': 1158, 'failed_count': 636, 'exact_string_match': 0.44991364421416236, 'rdkit_validity': 0.7443868739205527, 'two_attachment_validity': 0.7409326424870466, 'canonical_match': 0.45077720207253885}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 696, 'exact_string_match': 0.39291882556131263, 'rdkit_validity': 0.6666666666666666, 'two_attachment_validity': 0.6640759930915371, 'canonical_match': 0.39896373056994816}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.45682210708117443, 'rdkit_validity': 0.7113557858376511, 'two_attachment_validity': 0.7091968911917098, 'canonical_match': 0.4596286701208981, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
