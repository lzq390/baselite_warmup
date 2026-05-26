from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".codex_py_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem.rdmolops import FragmentOnBonds, GetShortestPath


RDLogger.DisableLog("rdApp.*")


INPUT_CSV = ROOT / "data" / "processed" / "unique_standardized_smiles.csv"
PERIODS_CSV = ROOT / "data" / "processed" / "periods_from_unique_standardized_smiles.csv"
PERIODS2_CSV = ROOT / "data" / "processed" / "periods2_from_unique_standardized_smiles.csv"
REPORT_MD = ROOT / "data" / "processed" / "period_pipeline_report.md"
FAILED_JSONL = ROOT / "data" / "processed" / "period_pipeline_failed_cases.jsonl"


def find_star_atoms(mol: Chem.Mol) -> list[int]:
    stars = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetSymbol() == "*"]
    if len(stars) != 2:
        raise ValueError(f"expected exactly two attachment atoms, got {len(stars)}")
    return stars


def get_single_neighbor(atom: Chem.Atom) -> Chem.Atom:
    neighbors = list(atom.GetNeighbors())
    if len(neighbors) != 1:
        raise ValueError(f"attachment atom must have one neighbor, got {len(neighbors)}")
    return neighbors[0]


def get_backbone_path(mol: Chem.Mol, star_a: int, star_b: int) -> list[int]:
    path = GetShortestPath(mol, star_a, star_b)
    return [idx for idx in path if mol.GetAtomWithIdx(idx).GetSymbol() != "*"]


def monomer_backbone_length(smiles: str) -> int:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("RDKit parse failed")
    star_a, star_b = find_star_atoms(mol)
    return len(get_backbone_path(mol, star_a, star_b))


def fragment_backbone_length(fragment: Chem.Mol) -> int | None:
    stars = [atom.GetIdx() for atom in fragment.GetAtoms() if atom.GetSymbol() == "*"]
    if len(stars) != 2:
        return None
    path = GetShortestPath(fragment, stars[0], stars[1])
    return sum(1 for idx in path if fragment.GetAtomWithIdx(idx).GetSymbol() != "*")


def connect_repeat_units(left_mol: Chem.Mol, right_mol: Chem.Mol) -> Chem.Mol:
    stars_left = [atom for atom in left_mol.GetAtoms() if atom.GetSymbol() == "*"]
    stars_right = [atom for atom in right_mol.GetAtoms() if atom.GetSymbol() == "*"]
    if len(stars_left) != 2 or len(stars_right) != 2:
        raise ValueError("each repeat unit must contain exactly two attachment atoms")

    # Historical periods_construct.py uses max index from left and min index from right.
    # This preserves that functional behavior for comparability.
    star_left = max(stars_left, key=lambda atom: atom.GetIdx())
    star_right = min(stars_right, key=lambda atom: atom.GetIdx())
    neighbor_left = get_single_neighbor(star_left)
    neighbor_right = get_single_neighbor(star_right)

    combo = Chem.CombineMols(left_mol, right_mol)
    editable = Chem.EditableMol(combo)
    offset = left_mol.GetNumAtoms()
    editable.AddBond(neighbor_left.GetIdx(), neighbor_right.GetIdx() + offset, Chem.BondType.SINGLE)
    for atom_idx in sorted([star_left.GetIdx(), star_right.GetIdx() + offset], reverse=True):
        editable.RemoveAtom(atom_idx)
    mol = editable.GetMol()
    Chem.SanitizeMol(mol)
    return mol


def trimerize_canonical_index(smiles: str) -> str:
    mols = [Chem.MolFromSmiles(smiles) for _ in range(3)]
    if any(mol is None for mol in mols):
        raise ValueError("RDKit parse failed")
    dimer = connect_repeat_units(mols[0], mols[1])
    trimer = connect_repeat_units(dimer, mols[2])
    return Chem.MolToSmiles(trimer, canonical=True, isomericSmiles=True)


def force_build_period(trimer: Chem.Mol, backbone: list[int], start: int, length: int) -> str | None:
    if start <= 0 or start + length >= len(backbone):
        return None
    bond_left = trimer.GetBondBetweenAtoms(backbone[start - 1], backbone[start])
    bond_right = trimer.GetBondBetweenAtoms(backbone[start + length - 1], backbone[start + length])
    if bond_left is None or bond_right is None:
        return None

    fragmented = FragmentOnBonds(
        trimer,
        [bond_left.GetIdx(), bond_right.GetIdx()],
        addDummies=True,
        dummyLabels=[(0, 0), (0, 0)],
    )
    for fragment in Chem.GetMolFrags(fragmented, asMols=True, sanitizeFrags=False):
        if sum(atom.GetSymbol() == "*" for atom in fragment.GetAtoms()) != 2:
            continue
        if fragment_backbone_length(fragment) != length:
            continue
        Chem.SanitizeMol(fragment)
        return Chem.MolToSmiles(fragment, canonical=True, isomericSmiles=True)
    return None


def sliding_periods_from_repeat_unit(smiles: str) -> tuple[str, list[tuple[int, str | None]], set[str]]:
    trimer_smiles = trimerize_canonical_index(smiles)
    trimer = Chem.MolFromSmiles(trimer_smiles)
    if trimer is None:
        raise ValueError("trimer parse failed")
    star_a, star_b = find_star_atoms(trimer)
    backbone = get_backbone_path(trimer, star_a, star_b)
    length = monomer_backbone_length(smiles)

    results: list[tuple[int, str | None]] = []
    unique_periods: set[str] = set()
    for start in range(1, len(backbone) - length):
        period = force_build_period(trimer, backbone, start, length)
        results.append((start, period))
        if period is not None:
            unique_periods.add(period)
    return trimer_smiles, results, unique_periods


def period_prefilter(smiles: str) -> bool:
    if not isinstance(smiles, str) or not smiles:
        return False
    if "," in smiles:
        return False
    if re.search(r"\[R\d*\]", smiles):
        return False
    if "[[" in smiles or "]]" in smiles:
        return False
    return True


def canonical_valid_period(smiles: str) -> str | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    stars = [atom for atom in mol.GetAtoms() if atom.GetSymbol() == "*"]
    if len(stars) != 2:
        return None
    for atom in mol.GetAtoms():
        if atom.HasQuery():
            return None
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def read_input_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_report(stats: dict[str, Any], generation_failures: list[dict[str, Any]], filter_failures: list[dict[str, Any]]) -> str:
    lines = [
        "# sliding period 生成与过滤报告",
        "",
        f"- 生成时间 UTC: `{datetime.now(timezone.utc).isoformat()}`",
        f"- 输入文件: `{INPUT_CSV}`",
        f"- period 候选输出: `{PERIODS_CSV}`",
        f"- 过滤去重输出: `{PERIODS2_CSV}`",
        f"- failed cases: `{FAILED_JSONL}`",
        f"- RDKit 版本: `{rdBase.rdkitVersion}`",
        "",
        "## 功能说明",
        "",
        "本流程按 `periods_construct.py -> dataset_filter.py` 的功能处理 `unique_standardized_smiles.csv`：",
        "",
        "1. 对每个两连接点标准化 SMILES 构造三聚体。",
        "2. 沿两个 `*` 之间的 shortest backbone path 滑动切分，生成 period candidates。",
        "3. 对 period candidates 做 RDKit 解析、恰好两个 `*`、query atom 过滤和 canonical 去重。",
        "",
        "## 关键风险",
        "",
        "- attachment 左右角色仍沿用历史脚本的 RDKit atom index 规则，不等同于严格 canonical orientation。",
        "- 三聚体连接仍按 single bond 构造，未推断真实 periodic bond order。",
        "- backbone 使用两个 `*` 之间 shortest path，复杂环/支化结构可能不稳定。",
        "- 本流程只适合作为词表构建阶段的 sliding period candidate 生成，不作为当前 BaseLite 训练样本构建流程，也不等同于严格 periodic graph matcher。",
        "",
        "## 统计",
        "",
        f"- 输入唯一标准化 SMILES 数: `{stats['input_count']}`",
        f"- generation 通过数: `{stats['generation_success']}`",
        f"- generation 失败数: `{stats['generation_failed']}`",
        f"- period candidate 总行数: `{stats['period_candidate_rows']}`",
        f"- 含 source 去重前 unique period_smiles 数: `{stats['period_candidate_unique']}`",
        f"- filter prefilter 失败数: `{stats['filter_invalid_prefilter']}`",
        f"- filter RDKit/结构失败数: `{stats['filter_invalid_rdkit']}`",
        f"- filter 重复数: `{stats['filter_duplicate']}`",
        f"- periods2 保留数: `{stats['filter_kept']}`",
        "",
        "## 每个输入生成 period 数分布",
        "",
    ]
    for count, n_inputs in sorted(stats["periods_per_input_dist"].items()):
        lines.append(f"- `{count}` 个 period: `{n_inputs}` 个输入")
    lines.extend(["", "## generation 失败原因", ""])
    for reason, count in sorted(stats["generation_failure_reasons"].items()):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## filter 失败原因", ""])
    for reason, count in sorted(stats["filter_failure_reasons"].items()):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## 失败样本示例", ""])
    for row in (generation_failures + filter_failures)[:20]:
        lines.append(f"- `{row.get('stage')}` `{row.get('reason')}`: `{row.get('smiles') or row.get('period_smiles')}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    input_rows = read_input_rows()
    period_rows: list[dict[str, Any]] = []
    generation_failures: list[dict[str, Any]] = []
    periods_per_input: Counter[int] = Counter()
    generation_failure_reasons: Counter[str] = Counter()

    for idx, row in enumerate(input_rows, start=1):
        source_id = row["canonical_id"]
        smiles = row["standardized_smiles"]
        try:
            trimer_smiles, sliding_results, unique_periods = sliding_periods_from_repeat_unit(smiles)
            sorted_periods = sorted(unique_periods)
            periods_per_input[len(sorted_periods)] += 1
            for period in sorted_periods:
                period_rows.append(
                    {
                        "period_smiles": period,
                        "source_canonical_id": source_id,
                        "source_standardized_smiles": smiles,
                        "trimer_smiles": trimer_smiles,
                        "sliding_positions_total": len(sliding_results),
                        "unique_periods_for_source": len(sorted_periods),
                    }
                )
        except Exception as exc:
            reason = type(exc).__name__
            generation_failure_reasons[reason] += 1
            periods_per_input[0] += 1
            generation_failures.append(
                {
                    "stage": "period_generation",
                    "canonical_id": source_id,
                    "smiles": smiles,
                    "reason": reason,
                    "message": str(exc),
                }
            )
        if idx % 1000 == 0:
            print(f"processed {idx}/{len(input_rows)} inputs; period candidates={len(period_rows)}")

    write_csv(
        PERIODS_CSV,
        period_rows,
        [
            "period_smiles",
            "source_canonical_id",
            "source_standardized_smiles",
            "trimer_smiles",
            "sliding_positions_total",
            "unique_periods_for_source",
        ],
    )

    seen: set[str] = set()
    periods2_rows: list[dict[str, Any]] = []
    filter_failures: list[dict[str, Any]] = []
    filter_failure_reasons: Counter[str] = Counter()
    filter_stats = {
        "invalid_prefilter": 0,
        "invalid_rdkit": 0,
        "duplicate": 0,
        "kept": 0,
    }
    first_source_by_period: dict[str, dict[str, Any]] = {}

    for row in period_rows:
        period = row["period_smiles"]
        if not period_prefilter(period):
            filter_stats["invalid_prefilter"] += 1
            filter_failure_reasons["prefilter_failed"] += 1
            filter_failures.append({"stage": "period_filter", "period_smiles": period, "reason": "prefilter_failed"})
            continue
        canon = canonical_valid_period(period)
        if canon is None:
            filter_stats["invalid_rdkit"] += 1
            filter_failure_reasons["rdkit_or_structure_failed"] += 1
            filter_failures.append({"stage": "period_filter", "period_smiles": period, "reason": "rdkit_or_structure_failed"})
            continue
        if canon in seen:
            filter_stats["duplicate"] += 1
            filter_failure_reasons["duplicate"] += 1
            continue
        seen.add(canon)
        first_source_by_period[canon] = row
        periods2_rows.append(
            {
                "smiles": canon,
                "source_canonical_id": row["source_canonical_id"],
                "source_standardized_smiles": row["source_standardized_smiles"],
            }
        )
        filter_stats["kept"] += 1

    periods2_rows.sort(key=lambda item: item["smiles"])
    write_csv(PERIODS2_CSV, periods2_rows, ["smiles", "source_canonical_id", "source_standardized_smiles"])

    all_failures = generation_failures + filter_failures
    write_jsonl(FAILED_JSONL, all_failures)

    stats = {
        "input_count": len(input_rows),
        "generation_success": len(input_rows) - len(generation_failures),
        "generation_failed": len(generation_failures),
        "period_candidate_rows": len(period_rows),
        "period_candidate_unique": len({row["period_smiles"] for row in period_rows}),
        "filter_invalid_prefilter": filter_stats["invalid_prefilter"],
        "filter_invalid_rdkit": filter_stats["invalid_rdkit"],
        "filter_duplicate": filter_stats["duplicate"],
        "filter_kept": filter_stats["kept"],
        "periods_per_input_dist": dict(periods_per_input),
        "generation_failure_reasons": dict(generation_failure_reasons),
        "filter_failure_reasons": dict(filter_failure_reasons),
    }
    REPORT_MD.write_text(build_report(stats, generation_failures, filter_failures), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"wrote {PERIODS_CSV}")
    print(f"wrote {PERIODS2_CSV}")
    print(f"wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
