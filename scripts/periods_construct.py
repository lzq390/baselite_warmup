from rdkit import Chem
from rdkit.Chem.rdmolops import GetShortestPath, FragmentOnBonds

import pandas as pd
import random
from tqdm import tqdm
# ======================================================
# 1. 单体 → 三聚体（canonical，原子索引规则）
# ======================================================

def trimerize_canonical_index(monomer_smiles: str) -> str:
    """
    将含有两个 [*] 的单体 SMILES 规范地连接成三聚体
    规则：
      - 每次连接都使用原子索引规则
      - 左分子：使用 index 最大的 [*]
      - 右分子：使用 index 最小的 [*]
    返回 canonical SMILES
    """

    def connect(left_mol, right_mol):
        stars_l = [a for a in left_mol.GetAtoms() if a.GetSymbol() == "*"]
        stars_r = [a for a in right_mol.GetAtoms() if a.GetSymbol() == "*"]

        if len(stars_l) != 2 or len(stars_r) != 2:
            raise ValueError("每个分子必须且只能包含两个 [*]")

        star_l = max(stars_l, key=lambda a: a.GetIdx())
        star_r = min(stars_r, key=lambda a: a.GetIdx())

        nbr_l = star_l.GetNeighbors()[0]
        nbr_r = star_r.GetNeighbors()[0]

        combo = Chem.CombineMols(left_mol, right_mol)
        emol = Chem.EditableMol(combo)
        offset = left_mol.GetNumAtoms()

        emol.AddBond(
            nbr_l.GetIdx(),
            nbr_r.GetIdx() + offset,
            Chem.BondType.SINGLE,
        )

        # 删除已消耗的 *
        for idx in sorted(
            [star_l.GetIdx(), star_r.GetIdx() + offset],
            reverse=True,
        ):
            emol.RemoveAtom(idx)

        mol = emol.GetMol()
        Chem.SanitizeMol(mol)
        return mol

    mol1 = Chem.MolFromSmiles(monomer_smiles)
    mol2 = Chem.MolFromSmiles(monomer_smiles)
    mol3 = Chem.MolFromSmiles(monomer_smiles)

    if mol1 is None or mol2 is None or mol3 is None:
        raise ValueError("单体 SMILES 解析失败")

    dimer = connect(mol1, mol2)
    trimer = connect(dimer, mol3)

    return Chem.MolToSmiles(trimer, canonical=True)


# ======================================================
# 2. 主链 / backbone 工具
# ======================================================

def find_star_atoms(mol):
    stars = [a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "*"]
    if len(stars) != 2:
        raise ValueError("必须恰好两个 *")
    return stars


def get_backbone_path(mol, s1, s2):
    path = GetShortestPath(mol, s1, s2)
    return [i for i in path if mol.GetAtomWithIdx(i).GetSymbol() != "*"]


def monomer_backbone_length(smiles):
    mol = Chem.MolFromSmiles(smiles)
    s1, s2 = find_star_atoms(mol)
    return len(get_backbone_path(mol, s1, s2))


def fragment_backbone_length(frag):
    stars = [a.GetIdx() for a in frag.GetAtoms() if a.GetSymbol() == "*"]
    if len(stars) != 2:
        return None

    path = GetShortestPath(frag, stars[0], stars[1])
    return sum(
        1 for i in path if frag.GetAtomWithIdx(i).GetSymbol() != "*"
    )


# ======================================================
# 3. 强制滑动切周期（只约束主链长度）
# ======================================================

def force_build_period(trimer, backbone, start, L):
    if start <= 0 or start + L >= len(backbone):
        return None

    bond_l = trimer.GetBondBetweenAtoms(
        backbone[start - 1], backbone[start]
    )
    bond_r = trimer.GetBondBetweenAtoms(
        backbone[start + L - 1], backbone[start + L]
    )

    frag_mol = FragmentOnBonds(
        trimer,
        [bond_l.GetIdx(), bond_r.GetIdx()],
        addDummies=True,
        dummyLabels=[(0, 0), (0, 0)],
    )

    for f in Chem.GetMolFrags(
        frag_mol, asMols=True, sanitizeFrags=False
    ):
        if sum(a.GetSymbol() == "*" for a in f.GetAtoms()) != 2:
            continue

        if fragment_backbone_length(f) == L:
            Chem.SanitizeMol(f)
            return Chem.MolToSmiles(f, canonical=True)

    return None


# ======================================================
# 4. 单体 → 三聚体 → 全滑动周期（总接口）
# ======================================================

def sliding_periods_from_monomer(monomer_smiles: str):
    """
    输入：单体 SMILES
    输出：
      - trimer_smiles
      - 所有滑动位置的周期
      - canonical 去重后的不同周期
    """
    trimer_smiles = trimerize_canonical_index(monomer_smiles)
    trimer = Chem.MolFromSmiles(trimer_smiles)

    s1, s2 = find_star_atoms(trimer)
    backbone = get_backbone_path(trimer, s1, s2)

    L = monomer_backbone_length(monomer_smiles)

    results = []
    unique_periods = set()

    for start in range(1, len(backbone) - L):
        p = force_build_period(trimer, backbone, start, L)
        results.append((start, p))
        if p is not None:
            unique_periods.add(p)

    return trimer_smiles, results, unique_periods
import re

def prefilter_smiles(smiles: str) -> bool:
    """
    在 RDKit 之前过滤：
    - R-group（R1, R2, R...）
    - 非法 bracket token
    """

    if not isinstance(smiles, str):
        return False

    # ❌ R1, R2, R12 ...
    if re.search(r"\[R\d*\]", smiles):
        return False

    # ❌ 单独 R（极少见但保险）
    if re.search(r"\bR\d*\b", smiles):
        return False

    return True

def is_valid_monomer(smiles: str) -> bool:
    """
    过滤规则：
    1. RDKit 可解析 + sanitize 成功
    2. 恰好两个 '*'
    3. 不含 R 基 / query atom
    """

    if not isinstance(smiles, str):
        return False

    # ---------- 1. 解析 ----------
    mol = Chem.MolFromSmiles(smiles, sanitize=False)
    if mol is None:
        return False

    # ---------- 2. sanitize ----------
    try:
        Chem.SanitizeMol(mol)
    except:
        return False

    # ---------- 3. 必须恰好两个 '*' ----------
    stars = [a for a in mol.GetAtoms() if a.GetSymbol() == "*"]
    if len(stars) != 2:
        return False

    # ---------- 4. 禁止 R-group ----------
    for atom in mol.GetAtoms():

        # (1) RDKit 的 query atom（SMARTS）
        if atom.HasQuery():
            return False

        # (2) 原子符号异常（如 R）
        sym = atom.GetSymbol()
        if sym.startswith("R"):   # R, R1, R2 ...
            return False

    return True
# ======================================================
# 5. 示例
# ======================================================
def split_multi_smiles(smi: str):
    if "," in smi:
        return [s.strip() for s in smi.split(",")]
    return [smi]

def build_period_dataset(
    input_csv,
    output_csv,
    smiles_col="smiles",
    keep_source=False,   # 是否保留原始 SMILES
):
    df = pd.read_csv(input_csv)

    all_periods = []

    for i, row in tqdm(df.iterrows(), total=len(df)):
        raw_smi = row[smiles_col]

        if pd.isna(raw_smi):
            continue
        smis = split_multi_smiles(raw_smi)

        # ✅ 第一道防线（字符串级）
        for smi in smis:

            if not prefilter_smiles(smi):
                continue

            if not is_valid_monomer(smi):
                continue

            try:
                trimer_smiles, sliding_results, unique_periods = (
                    sliding_periods_from_monomer(smi)
                )
                for p in unique_periods:
                    if p is None:
                        continue

                    item = {
                        "period_smiles": p,
                    }

                    if keep_source:
                        item["source_smiles"] = smi

                    all_periods.append(item)

            except Exception as e:
                # 避免一个坏 SMILES 影响整体
                continue

        # ======================================================
        # 打乱顺序
        # ======================================================
    random.shuffle(all_periods)

    out_df = pd.DataFrame(all_periods)

    out_df.to_csv(output_csv, index=False)

    print(f"✅ 输入分子数: {len(df)}")
    print(f"✅ 生成周期数: {len(out_df)}")
    print(f"✅ 已保存到: {output_csv}")




# ======================================================
# 使用示例
# ======================================================

if __name__ == "__main__":
    build_period_dataset(
        input_csv="/home/devuser/cgy/LLM/dataset/source_data.csv",
        output_csv="/home/devuser/cgy/LLM/dataset/periods.csv",
        smiles_col="smiles",   # 根据你的列名改
        keep_source=True       # 可选
    )