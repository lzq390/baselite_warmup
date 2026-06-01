# BaseLite SMILES Aug v2

Stage B restore v2 uses five views per record:

1. `identity`
2. `rdkit_random_smiles`
3. `direction_flip`
4. `attachment_rooted_smiles`
5. `light_denoise`

The large JSONL files in this directory are committed with Git LFS.

After checkout on a new machine, fetch LFS objects before training:

```bash
git lfs pull
```
