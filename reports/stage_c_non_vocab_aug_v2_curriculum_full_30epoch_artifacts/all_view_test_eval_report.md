# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.2848846576725309`
- `restore_loss`: `0.16774227954192594`
- `align_loss`: `0.5857118769114753`
- `weighted_align_loss`: `0.11714237538229506`
- `align_to_restore_ratio`: `0.698347343926587`
- `token_accuracy`: `0.9681703060710986`
- `exact_string_match`: `0.5739205526770293`
- `rdkit_validity`: `0.7654576856649395`
- `two_attachment_validity`: `0.7642487046632125`
- `canonical_match`: `0.575993091537133`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `retrieval_sample_count`: `1158`
- `text_to_graph_top1`: `0.84542316198349`
- `text_to_graph_top5`: `0.9974093437194824`
- `graph_to_text_top1`: `0.8238341808319092`
- `graph_to_text_top5`: `0.9922279715538025`
- `mean_positive_similarity`: `0.9127839207649231`
- `mean_negative_similarity`: `0.0020633649546653032`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 438, 'exact_string_match': 0.6191709844559585, 'rdkit_validity': 0.7789291882556131, 'two_attachment_validity': 0.7789291882556131, 'canonical_match': 0.6217616580310881}, 'direction_flip': {'sample_count': 1158, 'failed_count': 624, 'exact_string_match': 0.4585492227979275, 'rdkit_validity': 0.7132987910189983, 'two_attachment_validity': 0.7107081174438687, 'canonical_match': 0.46113989637305697}, 'identity': {'sample_count': 1158, 'failed_count': 226, 'exact_string_match': 0.803972366148532, 'rdkit_validity': 0.8903281519861831, 'two_attachment_validity': 0.8886010362694301, 'canonical_match': 0.8048359240069085}, 'light_denoise': {'sample_count': 1158, 'failed_count': 536, 'exact_string_match': 0.5354058721934369, 'rdkit_validity': 0.7452504317789291, 'two_attachment_validity': 0.7452504317789291, 'canonical_match': 0.5371329879101899}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 631, 'exact_string_match': 0.4525043177892919, 'rdkit_validity': 0.6994818652849741, 'two_attachment_validity': 0.697754749568221, 'canonical_match': 0.45509499136442144}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5739205526770293, 'rdkit_validity': 0.7654576856649395, 'two_attachment_validity': 0.7642487046632124, 'canonical_match': 0.575993091537133, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
- `formal_eval_dedup_retrieval`: `True`
- `full_final_decode`: `True`
- `dedup_final_retrieval`: `True`
