# Stage B Restore Full Eval Report

This checkpoint is a Stage B text-only restore training artifact.

- max epochs: `20`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`

## Metrics

- `loss`: `0.17134120255689417`
- `token_accuracy`: `0.9646398622549054`
- `exact_string_match`: `0.5431778929188256`
- `rdkit_validity`: `0.7526770293609671`
- `two_attachment_validity`: `0.7483592400690846`
- `canonical_match`: `0.5464594127806564`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 450, 'exact_string_match': 0.6053540587219344, 'rdkit_validity': 0.768566493955095, 'two_attachment_validity': 0.7633851468048359, 'canonical_match': 0.6113989637305699}, 'direction_flip': {'sample_count': 1158, 'failed_count': 664, 'exact_string_match': 0.4231433506044905, 'rdkit_validity': 0.689119170984456, 'two_attachment_validity': 0.6848013816925734, 'canonical_match': 0.4265975820379965}, 'identity': {'sample_count': 1158, 'failed_count': 175, 'exact_string_match': 0.8471502590673575, 'rdkit_validity': 0.9145077720207254, 'two_attachment_validity': 0.9119170984455959, 'canonical_match': 0.8488773747841105}, 'light_denoise': {'sample_count': 1158, 'failed_count': 645, 'exact_string_match': 0.4430051813471503, 'rdkit_validity': 0.7150259067357513, 'two_attachment_validity': 0.7115716753022453, 'canonical_match': 0.4430051813471503}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 692, 'exact_string_match': 0.39723661485319517, 'rdkit_validity': 0.6761658031088082, 'two_attachment_validity': 0.6701208981001727, 'canonical_match': 0.40241796200345425}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5431778929188256, 'rdkit_validity': 0.7526770293609671, 'two_attachment_validity': 0.7483592400690846, 'canonical_match': 0.5464594127806562, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.21037459770273284`
- `train_loss_last_window`: `0.017897665382340423`
- `train_loss_decreased`: `True`
- `completed_epochs`: `20`
- `optimizer_steps`: `57900`
- `train_sample_count`: `46320`
- `train_clean_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.15857321641642644`
- `best_early_stopping_checkpoint`: `epoch_012`
- `formal_eval_full_decode`: `True`
- `all_view_test_loss`: `0.175986562177357`
- `all_view_test_canonical_match`: `0.5436960276338515`
- `identity_test_loss`: `0.175986562177357`
- `identity_test_canonical_match`: `0.5436960276338515`
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
