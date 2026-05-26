from rdkit import Chem
import json
import csv
import re
import copy
from pathlib import Path


CSV_FILE = "/home/devuser/cgy/LLM/dataset/periods2.csv"
JSON_FILE = "/home/devuser/cgy/LLM/dataset/base_fragments.json"
OUTPUT_JSON = "/home/devuser/cgy/LLM/dataset/extracted_fragments1.json"

# CSV 中 SMILES 所在列名
SMILES_COLUMN = "smiles"

# 是否保留边界 [*]
KEEP_BOUNDARY = True

# 是否给新 fragment 重新编号
# 如果严格按照“其余均不变”，这里保持 False
# 如果你不想新文件里 fragment_id 重复，可以改成 True
RENUMBER_NEW_FRAGMENT_ID = False


def load_json_flexible(json_path):
    """
    支持两种 JSON 格式：
    1. 标准 JSON 数组：
       [{...}, {...}]

    2. 多个 JSON object 直接逗号分隔：
       {...},
       {...}
    """
    text = Path(json_path).read_text(encoding="utf-8").strip()
    text = text.rstrip(",")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(f"[{text}]")

    if isinstance(data, dict):
        data = [data]

    return data


def atom_to_simple_smarts(atom):
    """把 RDKit atom 转成简单 SMARTS 原子表达"""
    if atom.GetAtomicNum() == 0:
        return "[*]"

    symbol = atom.GetSymbol()

    if atom.GetIsAromatic():
        symbol = symbol.lower()

    charge = atom.GetFormalCharge()
    charge_text = ""

    if charge == 1:
        charge_text = "+"
    elif charge > 1:
        charge_text = f"+{charge}"
    elif charge == -1:
        charge_text = "-"
    elif charge < -1:
        charge_text = f"{charge}"

    return f"[{symbol}{charge_text}]"


def make_boundary_replacement(query, qidx, real_atom_smarts, keep_boundary=True):
    """
    根据 wildcard [*] 在 SMARTS 中的位置决定替换方向。
    如果真实匹配到的原子本身就是 [*]，则不再额外添加边界 [*]。
    """
    if not keep_boundary:
        return real_atom_smarts

    # 关键修改：如果 SMILES 里匹配到的就是 dummy atom '*'
    # 不要生成 [*][*] 或 [*][*]
    if real_atom_smarts == "[*]":
        return "[*]"

    qatom = query.GetAtomWithIdx(qidx)
    neighbors = list(qatom.GetNeighbors())

    if len(neighbors) != 1:
        return real_atom_smarts

    neighbor_idx = neighbors[0].GetIdx()

    if qidx < neighbor_idx:
        return "[*]" + real_atom_smarts
    else:
        return real_atom_smarts + "[*]"


def update_pattern_from_match(mol, query, pattern, match, keep_boundary=True):
    """
    基于一次 substructure match，把 pattern 中的 [*]
    更新为 SMILES 中真实匹配到的原子形式。
    """
    wildcard_query_atom_indices = [
        atom.GetIdx()
        for atom in query.GetAtoms()
        if atom.GetAtomicNum() == 0
    ]

    replacements = []

    for qidx in wildcard_query_atom_indices:
        mol_atom_idx = match[qidx]
        mol_atom = mol.GetAtomWithIdx(mol_atom_idx)

        real_atom_smarts = atom_to_simple_smarts(mol_atom)

        replacement = make_boundary_replacement(
            query=query,
            qidx=qidx,
            real_atom_smarts=real_atom_smarts,
            keep_boundary=keep_boundary
        )

        replacements.append(replacement)

    replacement_iter = iter(replacements)

    updated_pattern = re.sub(
        r"\[\*\]",
        lambda _: next(replacement_iter),
        pattern,
        count=len(replacements)
    )

    return updated_pattern


def pass_constraints(mol, fragment):
    """
    简单处理 match_rule.constraints.not_smarts。
    如果分子中含有 not_smarts 片段，则跳过。
    """
    constraints = fragment.get("match_rule", {}).get("constraints", {})
    not_smarts_list = constraints.get("not_smarts", [])

    for not_smarts in not_smarts_list:
        q = Chem.MolFromSmarts(not_smarts)

        if q is None:
            print(f"Warning: invalid not_smarts skipped: {not_smarts}")
            continue

        if mol.HasSubstructMatch(q):
            return False

    return True


def read_smiles_from_csv(csv_file, smiles_column):
    smiles_list = []

    with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if smiles_column not in reader.fieldnames:
            raise ValueError(
                f"CSV 中找不到列 '{smiles_column}'，当前列名为: {reader.fieldnames}"
            )

        for row in reader:
            smi = row.get(smiles_column, "").strip()
            if smi:
                smiles_list.append(smi)

    return smiles_list


def generate_updated_fragments(csv_file, json_file, output_json):
    fragments = load_json_flexible(json_file)
    smiles_list = read_smiles_from_csv(csv_file, SMILES_COLUMN)

    new_fragments = []

    # 原来是 seen = set()
    # 现在改成 dict:
    # key: (source_fragment_id, updated_pattern)
    # value: new_fragments 中对应 fragment 的下标
    seen = {}

    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)

        if mol is None:
            print(f"Warning: invalid SMILES skipped: {smi}")
            continue

        for fragment in fragments:
            fragment_id = fragment.get("fragment_id")
            pattern = fragment.get("match_rule", {}).get("pattern")

            if not pattern:
                continue

            query = Chem.MolFromSmarts(pattern)

            if query is None:
                print(f"Warning: invalid SMARTS skipped: {fragment_id}, {pattern}")
                continue

            if not pass_constraints(mol, fragment):
                continue

            matches = mol.GetSubstructMatches(query)

            if not matches:
                continue

            for match in matches:
                updated_pattern = update_pattern_from_match(
                    mol=mol,
                    query=query,
                    pattern=pattern,
                    match=match,
                    keep_boundary=KEEP_BOUNDARY
                )

                # 去重 key：同一个来源 fragment + 同一个 updated_pattern
                dedup_key = (fragment_id, updated_pattern)

                # 如果之前已经生成过这个新片段，不再新增，而是计数 +1
                if dedup_key in seen:
                    existing_index = seen[dedup_key]
                    new_fragments[existing_index]["match_count"] += 1

                    print(
                        f"Count +1: SMILES={smi}, source={fragment_id}, "
                        f"pattern={updated_pattern}, "
                        f"match_count={new_fragments[existing_index]['match_count']}"
                    )

                    continue

                # 第一次检测到这个 updated_pattern，创建新的 fragment
                new_fragment = copy.deepcopy(fragment)

                # source 改为匹配成功的原 fragment_id
                new_fragment["source"] = fragment_id

                # pattern 改为 updated_pattern
                new_fragment["match_rule"]["pattern"] = updated_pattern

                # 新增计数字段，第一次检测到为 1
                new_fragment["match_count"] = 1

                # priority + 10
                if "overlap_policy" not in new_fragment:
                    new_fragment["overlap_policy"] = {}

                old_priority = new_fragment["overlap_policy"].get("priority", 0)
                new_fragment["overlap_policy"]["priority"] = old_priority + 10

                # 可选：重新生成新 fragment_id
                if RENUMBER_NEW_FRAGMENT_ID:
                    new_fragment["fragment_id"] = f"fragment_new_{len(new_fragments) + 1:03d}"

                # 记录这个新 fragment 在 new_fragments 中的位置
                seen[dedup_key] = len(new_fragments)

                new_fragments.append(new_fragment)

                print(
                    f"Matched new: SMILES={smi}, source={fragment_id}, "
                    f"old_pattern={pattern}, new_pattern={updated_pattern}, "
                    f"match_count=1"
                )

    Path(output_json).write_text(
        json.dumps(new_fragments, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n完成，共生成 {len(new_fragments)} 个去重后的新 fragment")
    print(f"结果已保存到: {output_json}")


if __name__ == "__main__":
    generate_updated_fragments(
        csv_file=CSV_FILE,
        json_file=JSON_FILE,
        output_json=OUTPUT_JSON
    )