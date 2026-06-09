# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `valid`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.3303106460327826`
- `restore_loss`: `0.18715092206113917`
- `align_loss`: `0.7157986034126068`
- `weighted_align_loss`: `0.14315972068252136`
- `align_to_restore_ratio`: `0.7649426415102214`
- `token_accuracy`: `0.9629653710518065`
- `exact_string_match`: `0.5062607944732297`
- `rdkit_validity`: `0.7435233160621761`
- `two_attachment_validity`: `0.7407167530224525`
- `canonical_match`: `0.5105785837651122`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `retrieval_sample_count`: `0`
- `text_to_graph_top1`: `0.0`
- `text_to_graph_top5`: `0.0`
- `graph_to_text_top1`: `0.0`
- `graph_to_text_top5`: `0.0`
- `mean_positive_similarity`: `0.0`
- `mean_negative_similarity`: `0.0`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 446, 'exact_string_match': 0.6062176165803109, 'rdkit_validity': 0.7772020725388601, 'two_attachment_validity': 0.7763385146804835, 'canonical_match': 0.614853195164076}, 'direction_flip': {'sample_count': 1158, 'failed_count': 618, 'exact_string_match': 0.46113989637305697, 'rdkit_validity': 0.7322970639032815, 'two_attachment_validity': 0.727979274611399, 'canonical_match': 0.46632124352331605}, 'light_denoise': {'sample_count': 1158, 'failed_count': 573, 'exact_string_match': 0.5034542314335061, 'rdkit_validity': 0.7538860103626943, 'two_attachment_validity': 0.7530224525043178, 'canonical_match': 0.5051813471502591}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 630, 'exact_string_match': 0.4542314335060449, 'rdkit_validity': 0.7107081174438687, 'two_attachment_validity': 0.7055267702936097, 'canonical_match': 0.45595854922279794}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.5062607944732297, 'rdkit_validity': 0.7435233160621761, 'two_attachment_validity': 0.7407167530224525, 'canonical_match': 0.5105785837651122, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `retrieval_skipped_for_duplicate_graph_views`: `True`
- `formal_eval_full_decode`: `True`
