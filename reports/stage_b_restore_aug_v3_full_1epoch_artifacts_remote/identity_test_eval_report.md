# Stage B Restore Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v3/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v3/training_template_preview.jsonl`
- precision: `bf16`

## Metrics

- `loss`: `0.006055140897246442`
- `token_accuracy`: `0.9979656279439926`
- `exact_string_match`: `0.90625`
- `rdkit_validity`: `0.9921875`
- `two_attachment_validity`: `0.9921875`
- `canonical_match`: `0.90625`
- `sample_count`: `500000`
- `decoded_sample_count`: `128`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 25, 'failed_count': 1, 'exact_string_match': 0.96, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.96}, 'direction_flip': {'sample_count': 26, 'failed_count': 1, 'exact_string_match': 0.9615384615384616, 'rdkit_validity': 0.9615384615384616, 'two_attachment_validity': 0.9615384615384616, 'canonical_match': 0.9615384615384616}, 'identity': {'sample_count': 26, 'failed_count': 1, 'exact_string_match': 0.9615384615384616, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9615384615384616}, 'light_denoise': {'sample_count': 25, 'failed_count': 7, 'exact_string_match': 0.72, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.72}, 'rdkit_random_smiles': {'sample_count': 26, 'failed_count': 2, 'exact_string_match': 0.9230769230769231, 'rdkit_validity': 1.0, 'two_attachment_validity': 1.0, 'canonical_match': 0.9230769230769231}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.9052307692307693, 'rdkit_validity': 0.9923076923076923, 'two_attachment_validity': 0.9923076923076923, 'canonical_match': 0.9052307692307693, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `False`
- `full_final_decode`: `False`
