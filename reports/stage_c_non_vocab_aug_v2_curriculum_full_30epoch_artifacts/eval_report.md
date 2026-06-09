# Stage C Non-vocab BaseLite Warmup Eval Report

This checkpoint is a Stage C artifact for `L_restore + 0.2 * L_align`.

- max epochs: `30`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`

## Metrics

- `loss`: `0.27670140333041127`
- `restore_loss`: `0.15942633342001034`
- `align_loss`: `0.5863753355022698`
- `weighted_align_loss`: `0.11727506710045398`
- `align_to_restore_ratio`: `0.735606625233559`
- `token_accuracy`: `0.9683114035965453`
- `exact_string_match`: `0.5630397236614854`
- `rdkit_validity`: `0.7704663212435233`
- `two_attachment_validity`: `0.7678756476683938`
- `canonical_match`: `0.5671848013816926`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `retrieval_sample_count`: `1158`
- `text_to_graph_top1`: `0.8281520009040833`
- `text_to_graph_top5`: `0.9956822395324707`
- `graph_to_text_top1`: `0.8333333134651184`
- `graph_to_text_top5`: `0.9956822395324707`
- `mean_positive_similarity`: `0.9112046957015991`
- `mean_negative_similarity`: `0.0015036873519420624`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 446, 'exact_string_match': 0.6062176165803109, 'rdkit_validity': 0.7763385146804835, 'two_attachment_validity': 0.7754749568221071, 'canonical_match': 0.614853195164076}, 'direction_flip': {'sample_count': 1158, 'failed_count': 615, 'exact_string_match': 0.4637305699481865, 'rdkit_validity': 0.7340241796200345, 'two_attachment_validity': 0.729706390328152, 'canonical_match': 0.4689119170984456}, 'identity': {'sample_count': 1158, 'failed_count': 238, 'exact_string_match': 0.7910189982728842, 'rdkit_validity': 0.8825561312607945, 'two_attachment_validity': 0.8808290155440415, 'canonical_match': 0.7944732297063903}, 'light_denoise': {'sample_count': 1158, 'failed_count': 576, 'exact_string_match': 0.5008635578583766, 'rdkit_validity': 0.7521588946459413, 'two_attachment_validity': 0.7512953367875648, 'canonical_match': 0.5025906735751295}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 631, 'exact_string_match': 0.4533678756476684, 'rdkit_validity': 0.7072538860103627, 'two_attachment_validity': 0.7020725388601037, 'canonical_match': 0.45509499136442144}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5630397236614854, 'rdkit_validity': 0.7704663212435233, 'two_attachment_validity': 0.7678756476683939, 'canonical_match': 0.5671848013816926, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.18117075228254795`
- `train_loss_last_window`: `0.010361924001979824`
- `train_loss_decreased`: `True`
- `completed_epochs`: `30`
- `optimizer_steps`: `86850`
- `train_sample_count`: `46320`
- `train_clean_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.14656431014644267`
- `best_early_stopping_checkpoint`: `epoch_010`
- `formal_eval_full_decode`: `True`
- `formal_eval_dedup_retrieval`: `True`
- `full_final_decode`: `True`
- `dedup_final_retrieval`: `True`
- `all_view_test_loss`: `0.2848846576725309`
- `all_view_test_restore_loss`: `0.16774227954192594`
- `all_view_test_canonical_match`: `0.575993091537133`
- `train_conflict_filter_enabled`: `True`
- `train_conflict_filter_policy`: `prefer_self_label_else_drop_all`
- `train_conflict_filter_original_row_count`: `46320`
- `train_conflict_filter_clean_row_count`: `46320`
- `train_conflict_filter_removed_row_count`: `0`
- `train_conflict_filter_removed_by_strategy`: `{}`
- `train_conflict_filter_conflicting_input_view_count`: `0`
- `train_conflict_filter_rows_in_conflict_count`: `0`
- `train_conflict_filter_kept_rows_in_conflict_count`: `0`
- `train_conflict_filter_removed_rows_in_conflict_count`: `0`
- `train_conflict_filter_remaining_conflicting_input_view_count`: `0`
- `train_conflict_filter_clean_strategy_counts`: `{'attachment_rooted_smiles': 9264, 'direction_flip': 9264, 'identity': 9264, 'light_denoise': 9264, 'rdkit_random_smiles': 9264}`
