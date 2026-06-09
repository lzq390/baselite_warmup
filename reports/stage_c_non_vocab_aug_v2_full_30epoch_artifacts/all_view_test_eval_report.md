# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.2953278300356064`
- `restore_loss`: `0.17856706586072554`
- `align_loss`: `0.5838038093038782`
- `weighted_align_loss`: `0.11676076186077565`
- `align_to_restore_ratio`: `0.6538762413884535`
- `token_accuracy`: `0.9662820704242726`
- `exact_string_match`: `0.5580310880829016`
- `rdkit_validity`: `0.7654576856649395`
- `two_attachment_validity`: `0.7618307426597583`
- `canonical_match`: `0.5625215889464594`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `retrieval_sample_count`: `1158`
- `text_to_graph_top1`: `0.8169257044792175`
- `text_to_graph_top5`: `0.9974093437194824`
- `graph_to_text_top1`: `0.8082901835441589`
- `graph_to_text_top5`: `0.9948186278343201`
- `mean_positive_similarity`: `0.9112328290939331`
- `mean_negative_similarity`: `-0.0042730411514639854`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 439, 'exact_string_match': 0.6157167530224525, 'rdkit_validity': 0.7772020725388601, 'two_attachment_validity': 0.7728842832469776, 'canonical_match': 0.6208981001727115}, 'direction_flip': {'sample_count': 1158, 'failed_count': 619, 'exact_string_match': 0.4585492227979275, 'rdkit_validity': 0.7089810017271158, 'two_attachment_validity': 0.7063903281519862, 'canonical_match': 0.46545768566493956}, 'identity': {'sample_count': 1158, 'failed_count': 277, 'exact_string_match': 0.7590673575129534, 'rdkit_validity': 0.8609671848013817, 'two_attachment_validity': 0.8592400690846287, 'canonical_match': 0.7607944732297064}, 'light_denoise': {'sample_count': 1158, 'failed_count': 569, 'exact_string_match': 0.5051813471502591, 'rdkit_validity': 0.7573402417962003, 'two_attachment_validity': 0.7547495682210709, 'canonical_match': 0.5086355785837651}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 629, 'exact_string_match': 0.45164075993091535, 'rdkit_validity': 0.7227979274611399, 'two_attachment_validity': 0.7158894645941278, 'canonical_match': 0.45682210708117443}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5580310880829016, 'rdkit_validity': 0.7654576856649395, 'two_attachment_validity': 0.7618307426597581, 'canonical_match': 0.5625215889464594, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
- `formal_eval_dedup_retrieval`: `True`
- `full_final_decode`: `True`
- `dedup_final_retrieval`: `True`
