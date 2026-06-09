# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.34621707117747974`
- `restore_loss`: `0.20313283448683986`
- `align_loss`: `0.7154211659299688`
- `weighted_align_loss`: `0.14308423318599378`
- `align_to_restore_ratio`: `0.7043875183815427`
- `token_accuracy`: `0.9616388398414037`
- `exact_string_match`: `0.5071243523316062`
- `rdkit_validity`: `0.7424438687392055`
- `two_attachment_validity`: `0.7385578583765112`
- `canonical_match`: `0.5123056994818653`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `retrieval_sample_count`: `0`
- `text_to_graph_top1`: `0.0`
- `text_to_graph_top5`: `0.0`
- `graph_to_text_top1`: `0.0`
- `graph_to_text_top5`: `0.0`
- `mean_positive_similarity`: `0.0`
- `mean_negative_similarity`: `0.0`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 442, 'exact_string_match': 0.613126079447323, 'rdkit_validity': 0.7772020725388601, 'two_attachment_validity': 0.7728842832469776, 'canonical_match': 0.6183074265975821}, 'direction_flip': {'sample_count': 1158, 'failed_count': 619, 'exact_string_match': 0.4585492227979275, 'rdkit_validity': 0.7107081174438687, 'two_attachment_validity': 0.7081174438687392, 'canonical_match': 0.46545768566493956}, 'light_denoise': {'sample_count': 1158, 'failed_count': 568, 'exact_string_match': 0.5060449050086355, 'rdkit_validity': 0.7582037996545768, 'two_attachment_validity': 0.7564766839378239, 'canonical_match': 0.5094991364421416}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 630, 'exact_string_match': 0.45077720207253885, 'rdkit_validity': 0.7236614853195165, 'two_attachment_validity': 0.7167530224525043, 'canonical_match': 0.45595854922279794}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.5071243523316062, 'rdkit_validity': 0.7424438687392055, 'two_attachment_validity': 0.7385578583765112, 'canonical_match': 0.5123056994818653, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `retrieval_skipped_for_duplicate_graph_views`: `True`
- `formal_eval_full_decode`: `True`
