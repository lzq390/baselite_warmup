import pandas as pd
import re
from rdkit import Chem
from tqdm import tqdm


# ======================================================
# 1️⃣ 预过滤（字符串级）
# ======================================================

def prefilter_smiles(smi: str) -> bool:
    if not isinstance(smi, str):
        return False

    # ❌ 多 SMILES（逗号）
    if "," in smi:
        return False

    # ❌ R-group
    if re.search(r"\[R\d*\]", smi):
        return False

    # ❌ 嵌套 bracket
    if "[[" in smi or "]]" in smi:
        return False

    return True


# ======================================================
# 2️⃣ RDKit 合法性 + 结构过滤
# ======================================================

def is_valid_monomer(smi: str):
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None

    # 必须恰好两个 *
    stars = [a for a in mol.GetAtoms() if a.GetSymbol() == "*"]
    if len(stars) != 2:
        return None

    # 禁止 query atom
    for atom in mol.GetAtoms():
        if atom.HasQuery():
            return None

    # 返回 canonical SMILES（用于去重）
    return Chem.MolToSmiles(mol, canonical=True)


# ======================================================
# 3️⃣ 主函数：过滤 + 去重
# ======================================================

def clean_and_deduplicate_csv(
    input_csv,
    output_csv,
    smiles_col="smiles"
):
    df = pd.read_csv(input_csv)

    seen = set()
    cleaned_data = []

    stats = {
        "total": len(df),
        "invalid_prefilter": 0,
        "invalid_rdkit": 0,
        "duplicate": 0,
        "kept": 0,
    }

    for _, row in tqdm(df.iterrows(), total=len(df)):
        smi = row[smiles_col]

        # ---------- 1. 预过滤 ----------
        if not prefilter_smiles(smi):
            stats["invalid_prefilter"] += 1
            continue

        # ---------- 2. RDKit过滤 + canonical ----------
        canon = is_valid_monomer(smi)
        if canon is None:
            stats["invalid_rdkit"] += 1
            continue

        # ---------- 3. 去重 ----------
        if canon in seen:
            stats["duplicate"] += 1
            continue

        seen.add(canon)

        cleaned_data.append({
            "smiles": canon
        })

        stats["kept"] += 1

    # 保存
    out_df = pd.DataFrame(cleaned_data)
    out_df.to_csv(output_csv, index=False)

    # 打印统计
    print("\n===== 数据清洗统计 =====")
    for k, v in stats.items():
        print(f"{k}: {v}")

    print(f"\n✅ 输出文件: {output_csv}")
if __name__ == "__main__":
    clean_and_deduplicate_csv(
        input_csv="/home/devuser/cgy/LLM/dataset/periods.csv",
        output_csv="/home/devuser/cgy/LLM/dataset/periods2.csv",
        smiles_col="period_smiles"
    )