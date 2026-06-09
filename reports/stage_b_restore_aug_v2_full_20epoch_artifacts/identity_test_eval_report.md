# Stage B Restore Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- precision: `bf16`

## Metrics

- `loss`: `0.19364622525406813`
- `token_accuracy`: `0.9614744796962935`
- `exact_string_match`: `0.5160621761658031`
- `rdkit_validity`: `0.7398963730569948`
- `two_attachment_validity`: `0.7376511226252159`
- `canonical_match`: `0.5188255613126079`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 464, 'exact_string_match': 0.5967184801381693, 'rdkit_validity': 0.7607944732297064, 'two_attachment_validity': 0.7607944732297064, 'canonical_match': 0.5993091537132987}, 'direction_flip': {'sample_count': 1158, 'failed_count': 707, 'exact_string_match': 0.38773747841105355, 'rdkit_validity': 0.6735751295336787, 'two_attachment_validity': 0.6709844559585493, 'canonical_match': 0.38946459412780654}, 'identity': {'sample_count': 1158, 'failed_count': 283, 'exact_string_match': 0.7530224525043178, 'rdkit_validity': 0.8540587219343696, 'two_attachment_validity': 0.8514680483592401, 'canonical_match': 0.7556131260794473}, 'light_denoise': {'sample_count': 1158, 'failed_count': 636, 'exact_string_match': 0.44991364421416236, 'rdkit_validity': 0.7443868739205527, 'two_attachment_validity': 0.7409326424870466, 'canonical_match': 0.45077720207253885}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 696, 'exact_string_match': 0.39291882556131263, 'rdkit_validity': 0.6666666666666666, 'two_attachment_validity': 0.6640759930915371, 'canonical_match': 0.39896373056994816}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5160621761658032, 'rdkit_validity': 0.7398963730569947, 'two_attachment_validity': 0.7376511226252159, 'canonical_match': 0.5188255613126079, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
- `full_final_decode`: `True`
