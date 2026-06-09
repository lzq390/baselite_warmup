# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `valid`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.34174741717740664`
- `restore_loss`: `0.19855484204256285`
- `align_loss`: `0.7159628586808223`
- `weighted_align_loss`: `0.14319257173616448`
- `align_to_restore_ratio`: `0.7211739097526982`
- `token_accuracy`: `0.9628731987482525`
- `exact_string_match`: `0.5105785837651122`
- `rdkit_validity`: `0.7543177892918825`
- `two_attachment_validity`: `0.7519430051813472`
- `canonical_match`: `0.511873920552677`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `retrieval_sample_count`: `0`
- `text_to_graph_top1`: `0.0`
- `text_to_graph_top5`: `0.0`
- `graph_to_text_top1`: `0.0`
- `graph_to_text_top5`: `0.0`
- `mean_positive_similarity`: `0.0`
- `mean_negative_similarity`: `0.0`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 439, 'exact_string_match': 0.6183074265975821, 'rdkit_validity': 0.7936096718480138, 'two_attachment_validity': 0.7910189982728842, 'canonical_match': 0.6208981001727115}, 'direction_flip': {'sample_count': 1158, 'failed_count': 614, 'exact_string_match': 0.4689119170984456, 'rdkit_validity': 0.7435233160621761, 'two_attachment_validity': 0.7417962003454232, 'canonical_match': 0.4697754749568221}, 'light_denoise': {'sample_count': 1158, 'failed_count': 578, 'exact_string_match': 0.5, 'rdkit_validity': 0.7538860103626943, 'two_attachment_validity': 0.7530224525043178, 'canonical_match': 0.5008635578583766}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 630, 'exact_string_match': 0.45509499136442144, 'rdkit_validity': 0.7262521588946459, 'two_attachment_validity': 0.7219343696027634, 'canonical_match': 0.45595854922279794}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.5105785837651122, 'rdkit_validity': 0.7543177892918825, 'two_attachment_validity': 0.7519430051813472, 'canonical_match': 0.511873920552677, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `retrieval_skipped_for_duplicate_graph_views`: `True`
- `formal_eval_full_decode`: `True`
