# Stage B Restore Extra Eval Report

This report is an eval-only pass against an alternate preview file.

- split: `valid`
- train preview path: `data/baselite_smiles_aug_v2/training_template_preview.jsonl`
- eval preview path: `data/baselite_smiles_aug_v2/robustness_eval_preview.jsonl`
- precision: `bf16`

## Metrics

- `loss`: `0.22787202034881515`
- `token_accuracy`: `0.9556211047228393`
- `exact_string_match`: `0.4494818652849741`
- `rdkit_validity`: `0.7167530224525043`
- `two_attachment_validity`: `0.7130829015544041`
- `canonical_match`: `0.4531519861830743`
- `sample_count`: `4632`
- `decoded_sample_count`: `4632`
- `robustness_by_strategy`: `{'attachment_rooted_smiles': {'sample_count': 1158, 'failed_count': 482, 'exact_string_match': 0.5794473229706391, 'rdkit_validity': 0.7668393782383419, 'two_attachment_validity': 0.7651122625215889, 'canonical_match': 0.5837651122625216}, 'direction_flip': {'sample_count': 1158, 'failed_count': 691, 'exact_string_match': 0.3998272884283247, 'rdkit_validity': 0.7063903281519862, 'two_attachment_validity': 0.6994818652849741, 'canonical_match': 0.40328151986183075}, 'light_denoise': {'sample_count': 1158, 'failed_count': 663, 'exact_string_match': 0.42487046632124353, 'rdkit_validity': 0.7132987910189983, 'two_attachment_validity': 0.7098445595854922, 'canonical_match': 0.4274611398963731}, 'rdkit_random_smiles': {'sample_count': 1158, 'failed_count': 697, 'exact_string_match': 0.39378238341968913, 'rdkit_validity': 0.6804835924006909, 'two_attachment_validity': 0.6778929188255614, 'canonical_match': 0.39810017271157166}}`
- `robustness_strategy_macro_avg`: `{'exact_string_match': 0.44948186528497414, 'rdkit_validity': 0.7167530224525043, 'two_attachment_validity': 0.7130829015544041, 'canonical_match': 0.4531519861830743, 'strategy_count': 4, 'strategies': ['attachment_rooted_smiles', 'direction_flip', 'light_denoise', 'rdkit_random_smiles']}`
- `formal_eval_full_decode`: `True`
