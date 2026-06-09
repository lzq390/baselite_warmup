# Stage C Non-vocab BaseLite Warmup Eval Report

This checkpoint is a Stage C artifact for `L_restore + 0.2 * L_align`.

- max epochs: `30`
- precision: `bf16`
- preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- graph path: `data/processed/repeat_unit_graphs.jsonl`

## Metrics

- `loss`: `0.2912360652949364`
- `restore_loss`: `0.17414091683302638`
- `align_loss`: `0.5854757318694488`
- `weighted_align_loss`: `0.11709514637388976`
- `align_to_restore_ratio`: `0.6724160438764974`
- `token_accuracy`: `0.96722225850522`
- `exact_string_match`: `0.5573402417962003`
- `rdkit_validity`: `0.7730569948186529`
- `two_attachment_validity`: `0.7709844559585493`
- `canonical_match`: `0.5585492227979275`
- `sample_count`: `5790`
- `decoded_sample_count`: `5790`
- `retrieval_sample_count`: `1158`
- `text_to_graph_top1`: `0.8108808398246765`
- `text_to_graph_top5`: `0.9939550757408142`
- `graph_to_text_top1`: `0.8255612850189209`
- `graph_to_text_top5`: `0.9948186278343201`
- `mean_positive_similarity`: `0.9097159504890442`
- `mean_negative_similarity`: `-0.007496550679206848`
- `all_view_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 439, 'exact_string_match': 0.6183074265975821, 'rdkit_validity': 0.7953367875647669, 'two_attachment_validity': 0.7927461139896373, 'canonical_match': 0.6208981001727115}, 'direction_flip': {'sample_count': 1158, 'failed_count': 614, 'exact_string_match': 0.4689119170984456, 'rdkit_validity': 0.7417962003454232, 'two_attachment_validity': 0.7400690846286702, 'canonical_match': 0.4697754749568221}, 'identity': {'sample_count': 1158, 'failed_count': 295, 'exact_string_match': 0.7443868739205527, 'rdkit_validity': 0.8480138169257341, 'two_attachment_validity': 0.8471502590673575, 'canonical_match': 0.7452504317789291}, 'light_denoise': {'sample_count': 1158, 'failed_count': 578, 'exact_string_match': 0.5, 'rdkit_validity': 0.7538860103626943, 'two_attachment_validity': 0.7530224525043178, 'canonical_match': 0.5008635578583766}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 630, 'exact_string_match': 0.45509499136442144, 'rdkit_validity': 0.7262521588946459, 'two_attachment_validity': 0.7219343696027634, 'canonical_match': 0.45595854922279794}}`
- `all_view_strategy_macro_avg`: `{'exact_string_match': 0.5573402417962003, 'rdkit_validity': 0.7730569948186529, 'two_attachment_validity': 0.7709844559585493, 'canonical_match': 0.5585492227979275, 'strategy_count': 5, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'identity', 'light_denoise', 'rdkit_random_smiles']}`
- `train_loss_first_window`: `0.3139240221562439`
- `train_loss_last_window`: `0.01135130126338493`
- `train_loss_decreased`: `True`
- `completed_epochs`: `30`
- `optimizer_steps`: `86850`
- `train_sample_count`: `46320`
- `valid_sample_count`: `5790`
- `test_sample_count`: `5790`
- `early_stopped`: `False`
- `early_stop_reason`: `None`
- `early_stopping_monitor_only`: `True`
- `best_early_stopping_metric`: `0.17253741549461124`
- `best_early_stopping_checkpoint`: `epoch_009`
- `formal_eval_full_decode`: `True`
- `formal_eval_dedup_retrieval`: `True`
- `full_final_decode`: `True`
- `dedup_final_retrieval`: `True`
- `all_view_test_loss`: `0.2953278300356064`
- `all_view_test_restore_loss`: `0.17856706586072554`
- `all_view_test_canonical_match`: `0.5625215889464594`
