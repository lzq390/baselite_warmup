# Stage C Non-vocab Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `test`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`
- retrieval metrics are skipped for robustness eval files that may contain duplicate graph identities.

## Metrics

- `loss`: `0.3372510444688159`
- `restore_loss`: `0.19424171725478273`
- `align_loss`: `0.7150466200704195`
- `weighted_align_loss`: `0.14300932401408392`
- `align_to_restore_ratio`: `0.7362441294034774`
- `token_accuracy`: `0.9633392406843075`
- `exact_string_match`: `0.5164075993091537`
- `rdkit_validity`: `0.7338082901554405`
- `two_attachment_validity`: `0.7325129533678757`
- `canonical_match`: `0.518566493955095`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `retrieval_sample_count`: `0`
- `text_to_graph_top1`: `0.0`
- `text_to_graph_top5`: `0.0`
- `graph_to_text_top1`: `0.0`
- `graph_to_text_top5`: `0.0`
- `mean_positive_similarity`: `0.0`
- `mean_negative_similarity`: `0.0`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 439, 'exact_string_match': 0.6183074265975821, 'rdkit_validity': 0.7772020725388601, 'two_attachment_validity': 0.7772020725388601, 'canonical_match': 0.6208981001727115}, 'direction_flip': {'sample_count': 1158, 'failed_count': 623, 'exact_string_match': 0.459412780656304, 'rdkit_validity': 0.7132987910189983, 'two_attachment_validity': 0.7098445595854922, 'canonical_match': 0.4620034542314335}, 'light_denoise': {'sample_count': 1158, 'failed_count': 537, 'exact_string_match': 0.5354058721934369, 'rdkit_validity': 0.7452504317789291, 'two_attachment_validity': 0.7452504317789291, 'canonical_match': 0.5362694300518135}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 631, 'exact_string_match': 0.4525043177892919, 'rdkit_validity': 0.6994818652849741, 'two_attachment_validity': 0.697754749568221, 'canonical_match': 0.45509499136442144}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.5164075993091537, 'rdkit_validity': 0.7338082901554404, 'two_attachment_validity': 0.7325129533678756, 'canonical_match': 0.518566493955095, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `retrieval_skipped_for_duplicate_graph_views`: `True`
- `formal_eval_full_decode`: `True`
