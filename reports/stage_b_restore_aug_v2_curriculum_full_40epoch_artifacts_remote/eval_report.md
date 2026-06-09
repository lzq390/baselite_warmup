# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `40`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`

## Metrics

- `loss`: `0.18062822404459009`
- `token_accuracy`: `0.9668522579579362`
- `exact_string_match`: `0.5656303972366149`
- `rdkit_validity`: `0.7898100172711572`
- `two_attachment_validity`: `0.785146804835924`
- `canonical_match`: `0.5689119170984456`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 417, 'exact_string_match': 0.6355785837651122, 'rdkit_validity': 0.8151986183074266, 'two_attachment_validity': 0.8134715025906736, 'canonical_match': 0.6398963730569949}, 'direction_flip': {'sample_count': 1158, 'failed_count': 614, 'exact_string_match': 0.46286701208981, 'rdkit_validity': 0.731433506044905, 'two_attachment_validity': 0.7262521588946459, 'canonical_match': 0.4697754749568221}, 'identity': {'sample_count': 1158, 'failed_count': 239, 'exact_string_match': 0.7918825561312608, 'rdkit_validity': 0.8946459412780656, 'two_attachment_validity': 0.8903281519861831, 'canonical_match': 0.7936096718480138}, 'light_denoise': {'sample_count': 1158, 'failed_count': 591, 'exact_string_match': 0.48877374784110533, 'rdkit_validity': 0.7780656303972366, 'two_attachment_validity': 0.770293609671848, 'canonical_match': 0.4896373056994819}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 635, 'exact_string_match': 0.44905008635578586, 'rdkit_validity': 0.729706390328152, 'two_attachment_validity': 0.7253886010362695, 'canonical_match': 0.45164075993091535}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5656303972366149, 'rdkit_validity': 0.7898100172711572, 'two_attachment_validity': 0.785146804835924, 'canonical_match': 0.5689119170984456, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.15705705128665756`
- `train_loss_last_window`: `0.008731126381059457`
- `train_loss_decreased`: `True`
- `completed_epochs`: `40`
- `optimizer_steps`: `115800`
- `train_sample_count`: `46320`
- `train_clean_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.5683937823834196`
- `best_early_stopping_checkpoint`: `epoch_038`
- `formal_eval_full_decode`: `True`
- `all_view_test_loss`: `0.18975947787271738`
- `all_view_test_canonical_match`: `0.56286701208981`
- `identity_test_loss`: `0.18975947787271738`
- `identity_test_canonical_match`: `0.56286701208981`
- `full_final_decode`: `True`
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
