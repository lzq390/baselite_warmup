from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".codex_py_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

SPLITS = ("train", "valid", "test")
OMG_V3_DATASET_NAME = "baselite_smiles_v3"
OMG_V3_RECORD_PREFIX = "omg_v3"
OMG_V3_SPLIT_SEED = "baselite_smiles_v3_split_seed_2026_06_09"
OMG_V3_SAMPLE_SEED = "baselite_smiles_v3_omg_sample_seed_2026_06_09"

NODE_CATEGORICAL_FIELDS = ("element", "hybridization", "attachment_role")
NODE_NUMERIC_FIELDS = ("atomic_num", "degree", "formal_charge")
NODE_BOOL_FIELDS = ("aromatic", "is_attachment", "ring_membership")
EDGE_CATEGORICAL_FIELDS = ("bond_type",)
EDGE_BOOL_FIELDS = ("aromatic", "is_periodic_edge", "is_repeat_connection")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash_int(*parts: object) -> int:
    return int(sha256_text(":".join(str(part) for part in parts))[:16], 16)


def require_rdkit() -> Any:
    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:
        raise RuntimeError("RDKit is required for OMG v3 generation") from exc
    RDLogger.DisableLog("rdApp.*")
    return Chem


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
    return rows


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_dataset_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_path = dataset_dir / f"{split}.jsonl"
        for line_no, row in enumerate(iter_jsonl(split_path), start=1):
            for field in ("record_id", "canonical_smiles", "canonical_hash", "graph_hash", "split"):
                if row.get(field) in (None, ""):
                    raise ValueError(f"{split_path}:{line_no}: missing {field}")
            if str(row["split"]) != split:
                raise ValueError(f"{split_path}:{line_no}: split={row['split']!r}, expected {split!r}")
            rows.append(row)
    return rows


def load_current_canonical_hashes(dataset_dir: Path) -> set[str]:
    hashes: set[str] = set()
    for split in SPLITS:
        split_path = dataset_dir / f"{split}.jsonl"
        if not split_path.exists():
            continue
        for row in iter_jsonl(split_path):
            value = row.get("canonical_hash")
            if value not in (None, ""):
                hashes.add(str(value))
    return hashes


def canonicalize_smiles(smiles: str, Chem: Any) -> str | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def validate_repeat_unit_product(product: str, Chem: Any) -> tuple[str | None, dict[str, Any]]:
    if not product:
        return None, {"valid": False, "reason": "missing_product"}
    if product.count("*") != 2:
        return None, {"valid": False, "reason": "attachment_count_not_two", "attachment_count": product.count("*")}
    if "." in product:
        return None, {"valid": False, "reason": "multi_component_product"}
    mol = Chem.MolFromSmiles(product)
    if mol is None:
        return None, {"valid": False, "reason": "rdkit_parse_failed"}
    dummy_atoms = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(dummy_atoms) != 2:
        return None, {"valid": False, "reason": "dummy_atom_count_not_two", "dummy_atom_count": len(dummy_atoms)}
    dummy_degrees = [atom.GetDegree() for atom in dummy_atoms]
    if any(degree != 1 for degree in dummy_degrees):
        return None, {"valid": False, "reason": "dummy_atom_degree_not_one", "dummy_degrees": dummy_degrees}
    canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    return canonical, {"valid": True, "dummy_degrees": dummy_degrees, "attachment_count": 2}


def attachment_role_for_atom(atom_idx: int, attachment_atom_ids: list[int]) -> str | None:
    if atom_idx not in attachment_atom_ids:
        return None
    return f"attachment_{attachment_atom_ids.index(atom_idx) + 1}"


def atom_payload(atom: Any, attachment_atom_ids: list[int]) -> dict[str, Any]:
    return {
        "aromatic": bool(atom.GetIsAromatic()),
        "atom_id": int(atom.GetIdx()),
        "atomic_num": int(atom.GetAtomicNum()),
        "attachment_role": attachment_role_for_atom(int(atom.GetIdx()), attachment_atom_ids),
        "degree": int(atom.GetDegree()),
        "element": str(atom.GetSymbol()),
        "formal_charge": int(atom.GetFormalCharge()),
        "hybridization": str(atom.GetHybridization()),
        "is_attachment": atom.GetAtomicNum() == 0,
        "ring_membership": bool(atom.IsInRing()),
    }


def edge_payload(bond: Any) -> dict[str, Any]:
    return {
        "aromatic": bool(bond.GetIsAromatic()),
        "begin_atom_id": int(bond.GetBeginAtomIdx()),
        "bond_type": str(bond.GetBondType()),
        "end_atom_id": int(bond.GetEndAtomIdx()),
        "is_periodic_edge": False,
        "is_repeat_connection": False,
    }


def graph_signature_from_mol(mol: Any, attachment_atom_ids: list[int]) -> dict[str, Any]:
    nodes = [
        {
            "atom_id": int(atom.GetIdx()),
            "atomic_num": int(atom.GetAtomicNum()),
            "charge": int(atom.GetFormalCharge()),
            "degree": int(atom.GetDegree()),
            "hybridization": str(atom.GetHybridization()),
            "aromatic": bool(atom.GetIsAromatic()),
            "ring": bool(atom.IsInRing()),
            "attachment_role": attachment_role_for_atom(int(atom.GetIdx()), attachment_atom_ids),
        }
        for atom in mol.GetAtoms()
    ]
    edges = []
    for bond in mol.GetBonds():
        left = int(bond.GetBeginAtomIdx())
        right = int(bond.GetEndAtomIdx())
        edges.append(
            {
                "atoms": sorted([left, right]),
                "bond_type": str(bond.GetBondType()),
                "aromatic": bool(bond.GetIsAromatic()),
            }
        )
    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda row: (row["atoms"], row["bond_type"], row["aromatic"])),
    }


def graph_hash_for_smiles(canonical_smiles: str, Chem: Any) -> str:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        raise ValueError(f"RDKit failed to parse canonical_smiles={canonical_smiles!r}")
    attachment_atom_ids = [int(atom.GetIdx()) for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(attachment_atom_ids) != 2:
        raise ValueError(f"expected two attachment atoms for canonical_smiles={canonical_smiles!r}")
    signature = graph_signature_from_mol(mol, attachment_atom_ids)
    return sha256_text(json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def graph_row_for_record(record: dict[str, Any], Chem: Any) -> dict[str, Any]:
    canonical_smiles = str(record["canonical_smiles"])
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        raise ValueError(f"{record.get('record_id')}: RDKit failed to parse canonical_smiles")
    attachment_atom_ids = [int(atom.GetIdx()) for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(attachment_atom_ids) != 2:
        raise ValueError(f"{record.get('record_id')}: expected two attachment atoms")
    nodes = [atom_payload(atom, attachment_atom_ids) for atom in mol.GetAtoms()]
    edges = [edge_payload(bond) for bond in mol.GetBonds()]
    graph_hash = graph_hash_for_smiles(canonical_smiles, Chem)
    if str(record.get("graph_hash")) != graph_hash:
        raise ValueError(
            f"{record.get('record_id')}: graph_hash mismatch: dataset={record.get('graph_hash')}, built={graph_hash}"
        )
    return {
        "attachment_atom_ids": attachment_atom_ids,
        "canonical_hash": str(record["canonical_hash"]),
        "canonical_smiles": canonical_smiles,
        "edges": edges,
        "graph_hash": graph_hash,
        "nodes": nodes,
        "record_id": str(record["record_id"]),
        "repeat_graph_builder": {
            "periodic_expansion": "not_materialized",
            "periodic_radius": 0,
            "type": "single_repeat_unit_graph",
            "version": "omg_v3_single_repeat_unit_graph_v1",
        },
    }


def leakage_report(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values_by_split: dict[str, set[str]] = {split: set() for split in SPLITS}
    for row in rows:
        values_by_split[str(row["split"])].add(str(row[field]))
    pairs = {
        "train_valid": values_by_split["train"] & values_by_split["valid"],
        "train_test": values_by_split["train"] & values_by_split["test"],
        "valid_test": values_by_split["valid"] & values_by_split["test"],
    }
    return {
        "field": field,
        "train_valid": len(pairs["train_valid"]),
        "train_test": len(pairs["train_test"]),
        "valid_test": len(pairs["valid_test"]),
        "total_pairwise_leakage": sum(len(values) for values in pairs.values()),
    }


def split_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["split"]) for row in rows)
    return {split: counts.get(split, 0) for split in SPLITS}
