# Stage B Restore Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- precision: `bf16`

## Metrics

- `loss`: `0.175986562177357`
- `token_accuracy`: `0.9642379986910417`
- `exact_string_match`: `0.5416234887737479`
- `rdkit_validity`: `0.7426597582037997`
- `two_attachment_validity`: `0.7404145077720208`
- `canonical_match`: `0.5436960276338515`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 463, 'exact_string_match': 0.5984455958549223, 'rdkit_validity': 0.7607944732297064, 'two_attachment_validity': 0.7556131260794473, 'canonical_match': 0.6001727115716753}, 'direction_flip': {'sample_count': 1158, 'failed_count': 701, 'exact_string_match': 0.3903281519861831, 'rdkit_validity': 0.655440414507772, 'two_attachment_validity': 0.6528497409326425, 'canonical_match': 0.3946459412780656}, 'identity': {'sample_count': 1158, 'failed_count': 166, 'exact_string_match': 0.8566493955094991, 'rdkit_validity': 0.917098445595855, 'two_attachment_validity': 0.917098445595855, 'canonical_match': 0.8566493955094991}, 'light_denoise': {'sample_count': 1158, 'failed_count': 631, 'exact_string_match': 0.4542314335060449, 'rdkit_validity': 0.7115716753022453, 'two_attachment_validity': 0.7107081174438687, 'canonical_match': 0.45509499136442144}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 681, 'exact_string_match': 0.40846286701208984, 'rdkit_validity': 0.6683937823834197, 'two_attachment_validity': 0.6658031088082902, 'canonical_match': 0.4119170984455959}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5416234887737479, 'rdkit_validity': 0.7426597582037997, 'two_attachment_validity': 0.7404145077720207, 'canonical_match': 0.5436960276338515, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
- `full_final_decode`: `True`
