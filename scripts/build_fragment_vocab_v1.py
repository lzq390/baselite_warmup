from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".codex_py_deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

try:
    from rdkit import Chem, RDLogger, rdBase
    from rdkit.Chem import AllChem
except Exception as exc:  # pragma: no cover - gives a clear CLI failure.
    raise SystemExit(
        "RDKit is required. Install it into .codex_py_deps or run with the bundled Python used for this workspace."
    ) from exc


RDLogger.DisableLog("rdApp.*")


DATA_FILE = ROOT / "data" / "all_polymers_experiment_final.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
FRAGMENT_DIR = ROOT / "fragments"
SEED_DIR = FRAGMENT_DIR / "seeds"
MINING_DIR = FRAGMENT_DIR / "mining"
VOCAB_DIR = FRAGMENT_DIR / "vocab"
VALIDATION_DIR = FRAGMENT_DIR / "validation"

VERSION = "v1.0"
VOCAB_JSONL = VOCAB_DIR / "fragment_vocab_v1.0.jsonl"
VOCAB_JSON = VOCAB_DIR / "fragment_vocab_v1.0.json"
STATS_JSON = VOCAB_DIR / "fragment_vocab_v1.0.stats.json"
EXAMPLES_JSONL = VOCAB_DIR / "fragment_vocab_v1.0.examples.jsonl"
FAILED_JSONL = VALIDATION_DIR / "fragment_vocab_v1.0.failed_cases.jsonl"
VALIDATION_REPORT = VALIDATION_DIR / "fragment_vocab_v1.0.validation_report.md"


ATTACHMENT_REPLACEMENTS = (
    ("[[[*]]]", "*"),
    ("[[*]]", "*"),
    ("[*:1]", "*"),
    ("[*:2]", "*"),
    ("[*]", "*"),
)
ATTACHMENT_MAP_RE = re.compile(r"\[\*:\d+\]")
R_GROUP_RE = re.compile(r"\[R\d*\]")
INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

DEFAULT_DEDUP_FIELDS = [
    "fragment_id",
    "anchor_type",
    "anchor_role",
    "anchor_canonical_id_in_RU0",
    "atom_role_pattern",
    "boundary_pattern",
]


@dataclass(frozen=True)
class CanonicalRecord:
    record_id: str
    canonical_smiles: str
    canonical_hash: str
    graph_hash: str
    normalized_smiles_examples: tuple[str, ...]
    raw_smiles_examples: tuple[str, ...]
    source_count: int
    mol: Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_dirs() -> None:
    for directory in (PROCESSED_DIR, SEED_DIR, MINING_DIR, VOCAB_DIR, VALIDATION_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_attachment_text(value: str) -> str:
    text = INVISIBLE_RE.sub("", value or "").strip()
    for src, dst in ATTACHMENT_REPLACEMENTS:
        text = text.replace(src, dst)
    text = ATTACHMENT_MAP_RE.sub("*", text)
    return text


def classify_record(raw_smiles: str) -> tuple[str, str]:
    normalized = normalize_attachment_text(raw_smiles)
    if not normalized:
        return "parser_failed", normalized
    if R_GROUP_RE.search(normalized):
        return "unresolved_R_group", normalized
    if "." in normalized:
        return "ionomer_or_multicomponent_candidate", normalized
    if "," in normalized:
        return "copolymer_candidate", normalized
    star_count = normalized.count("*")
    if star_count == 2:
        return "main_repeat_unit", normalized
    if star_count == 0:
        return "monomer_or_descriptor_record", normalized
    if star_count == 1:
        return "incomplete_attachment", normalized
    return "copolymer_candidate", normalized


def read_property_records(data_file: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    rows: list[dict[str, str]] = []
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with data_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            smiles = (row.get("smiles") or "").strip()
            normalized_row = {k: (v or "").strip() for k, v in row.items()}
            rows.append(normalized_row)
            grouped[smiles].append(
                {
                    "property_category": normalized_row.get("性质分类", ""),
                    "property_name": normalized_row.get("性质名", ""),
                    "value": normalized_row.get("值", ""),
                    "unit": normalized_row.get("单位", ""),
                }
            )
    return rows, dict(grouped)


def atom_payload(atom: Any, attachment_role: str | None) -> dict[str, Any]:
    return {
        "atom_id": atom.GetIdx(),
        "element": atom.GetSymbol(),
        "atomic_num": atom.GetAtomicNum(),
        "aromatic": atom.GetIsAromatic(),
        "formal_charge": atom.GetFormalCharge(),
        "hybridization": str(atom.GetHybridization()),
        "degree": atom.GetDegree(),
        "ring_membership": atom.IsInRing(),
        "is_attachment": atom.GetAtomicNum() == 0,
        "attachment_role": attachment_role,
    }


def bond_payload(bond: Any) -> dict[str, Any]:
    return {
        "begin_atom_id": bond.GetBeginAtomIdx(),
        "end_atom_id": bond.GetEndAtomIdx(),
        "bond_type": str(bond.GetBondType()),
        "aromatic": bond.GetIsAromatic(),
        "is_repeat_connection": False,
        "is_periodic_edge": False,
    }


def graph_signature(mol: Any) -> str:
    atom_bits = []
    for atom in mol.GetAtoms():
        atom_bits.append(
            "|".join(
                [
                    atom.GetSymbol(),
                    str(atom.GetAtomicNum()),
                    str(int(atom.GetIsAromatic())),
                    str(atom.GetFormalCharge()),
                    str(atom.GetDegree()),
                    str(int(atom.IsInRing())),
                ]
            )
        )
    bond_bits = []
    for bond in mol.GetBonds():
        a, b = sorted([bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()])
        bond_bits.append(f"{a}-{b}:{bond.GetBondType()}:{int(bond.GetIsAromatic())}")
    return stable_hash(";".join(sorted(atom_bits)) + "::" + ";".join(sorted(bond_bits)))


def canonicalize_main_records(
    grouped_records: dict[str, list[dict[str, str]]]
) -> tuple[list[dict[str, Any]], list[CanonicalRecord], list[dict[str, Any]], dict[str, Any]]:
    record_type_counter: Counter[str] = Counter()
    normalized_main: dict[str, dict[str, Any]] = {}
    property_records_rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []

    for raw_smiles in sorted(grouped_records):
        record_type, normalized = classify_record(raw_smiles)
        record_type_counter[record_type] += 1
        property_records_rows.append(
            {
                "raw_smiles": raw_smiles,
                "attachment_normalized_smiles": normalized,
                "record_type": record_type,
                "property_record_count": len(grouped_records[raw_smiles]),
                "properties": grouped_records[raw_smiles],
            }
        )

        if record_type != "main_repeat_unit":
            if record_type not in {"monomer_or_descriptor_record", "copolymer_candidate"}:
                failed_cases.append(
                    {
                        "stage": "phase_0_cleaning",
                        "record_type": record_type,
                        "raw_smiles": raw_smiles,
                        "attachment_normalized_smiles": normalized,
                        "reason": record_type,
                    }
                )
            continue

        bucket = normalized_main.setdefault(
            normalized,
            {
                "attachment_normalized_smiles": normalized,
                "raw_smiles_examples": [],
                "raw_unique_count": 0,
                "property_record_count": 0,
            },
        )
        bucket["raw_unique_count"] += 1
        bucket["property_record_count"] += len(grouped_records[raw_smiles])
        if len(bucket["raw_smiles_examples"]) < 5:
            bucket["raw_smiles_examples"].append(raw_smiles)

    clean_rows: list[dict[str, Any]] = []
    canonical_buckets: dict[str, dict[str, Any]] = {}

    for idx, normalized in enumerate(sorted(normalized_main), start=1):
        bucket = normalized_main[normalized]
        mol = Chem.MolFromSmiles(normalized)
        if mol is None:
            failed_cases.append(
                {
                    "stage": "phase_1_canonicalization",
                    "record_type": "parser_failed",
                    "raw_smiles_examples": bucket["raw_smiles_examples"],
                    "attachment_normalized_smiles": normalized,
                    "reason": "rdkit_mol_from_smiles_failed",
                }
            )
            continue

        canonical_smiles = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        canonical_hash = stable_hash(canonical_smiles)
        graph_hash = graph_signature(mol)
        clean_rows.append(
            {
                "clean_id": f"clean_{idx:06d}",
                "attachment_normalized_smiles": normalized,
                "raw_smiles_examples": bucket["raw_smiles_examples"],
                "raw_unique_count": bucket["raw_unique_count"],
                "property_record_count": bucket["property_record_count"],
            }
        )

        canonical_bucket = canonical_buckets.setdefault(
            canonical_smiles,
            {
                "canonical_smiles": canonical_smiles,
                "canonical_hash": canonical_hash,
                "graph_hash": graph_hash,
                "normalized_smiles_examples": [],
                "raw_smiles_examples": [],
                "source_count": 0,
                "mol": mol,
            },
        )
        canonical_bucket["source_count"] += 1
        if len(canonical_bucket["normalized_smiles_examples"]) < 5:
            canonical_bucket["normalized_smiles_examples"].append(normalized)
        for raw_example in bucket["raw_smiles_examples"]:
            if len(canonical_bucket["raw_smiles_examples"]) >= 5:
                break
            canonical_bucket["raw_smiles_examples"].append(raw_example)

    canonical_records: list[CanonicalRecord] = []
    for idx, canonical_smiles in enumerate(sorted(canonical_buckets), start=1):
        bucket = canonical_buckets[canonical_smiles]
        canonical_records.append(
            CanonicalRecord(
                record_id=f"ru_{idx:06d}",
                canonical_smiles=bucket["canonical_smiles"],
                canonical_hash=bucket["canonical_hash"],
                graph_hash=bucket["graph_hash"],
                normalized_smiles_examples=tuple(bucket["normalized_smiles_examples"]),
                raw_smiles_examples=tuple(bucket["raw_smiles_examples"]),
                source_count=bucket["source_count"],
                mol=bucket["mol"],
            )
        )

    audit = {
        "record_type_counts_raw_unique": dict(sorted(record_type_counter.items())),
        "level_1_raw_unique": len(grouped_records),
        "level_1_raw_two_attachment_main_after_text_exclusions": record_type_counter["main_repeat_unit"],
        "level_2_attachment_normalized_main_unique": len(normalized_main),
        "level_3_canonical_repeat_unit_unique": len(canonical_records),
        "level_4_repeat_unit_graph_hash_unique": len({r.graph_hash for r in canonical_records}),
        "level_5_primitive_periodic_graph_hash_unique": None,
        "parser_failed_count": sum(1 for row in failed_cases if row["stage"] == "phase_1_canonicalization"),
    }
    return clean_rows, canonical_records, failed_cases, audit | {"property_records_rows": property_records_rows}


def repeat_unit_graph_rows(canonical_records: list[CanonicalRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in canonical_records:
        attachment_ids = [atom.GetIdx() for atom in rec.mol.GetAtoms() if atom.GetAtomicNum() == 0]
        role_by_atom_id = {
            atom_id: f"attachment_{idx + 1}"
            for idx, atom_id in enumerate(sorted(attachment_ids))
        }
        rows.append(
            {
                "record_id": rec.record_id,
                "canonical_smiles": rec.canonical_smiles,
                "canonical_hash": rec.canonical_hash,
                "graph_hash": rec.graph_hash,
                "attachment_atom_ids": sorted(attachment_ids),
                "nodes": [atom_payload(atom, role_by_atom_id.get(atom.GetIdx())) for atom in rec.mol.GetAtoms()],
                "edges": [bond_payload(bond) for bond in rec.mol.GetBonds()],
                "repeat_graph_builder": {
                    "type": "single_repeat_unit_graph",
                    "periodic_expansion": "not_materialized",
                    "periodic_radius": 0,
                },
            }
        )
    return rows


def make_rule(
    fragment_id: str,
    fragment_name: str,
    category: str,
    pattern: str,
    atom_roles: dict[str, str],
    anchor_role: str,
    semantic_tags: list[str],
    *,
    parent_fragment_id: str | None = None,
    exclusive_group: str | None = None,
    priority: int = 50,
    allow_child_fragments: bool = True,
    allow_boundary_crossing: bool = True,
    enable_cut_shift_scan: bool = True,
    constraints: dict[str, Any] | None = None,
    ownership_rule: str = "anchor_in_RU0",
    periodic_radius: int = 1,
    max_cut_shift: int = 1,
) -> dict[str, Any]:
    return {
        "fragment_id": fragment_id,
        "fragment_name": fragment_name,
        "version": VERSION,
        "category": category,
        "parent_fragment_id": parent_fragment_id,
        "semantic_tags": semantic_tags,
        "match_rule": {
            "type": "smarts",
            "pattern": pattern,
            "constraints": constraints or {},
        },
        "atom_roles": atom_roles,
        "anchor_rule": {
            "anchor_type": "atom",
            "anchor_role": anchor_role,
        },
        "ownership_rule": ownership_rule,
        "periodic_radius": periodic_radius,
        "allow_boundary_crossing": allow_boundary_crossing,
        "enable_cut_shift_scan": enable_cut_shift_scan,
        "max_cut_shift": max_cut_shift,
        "dedup_key_fields": DEFAULT_DEDUP_FIELDS,
        "overlap_policy": {
            "exclusive_group": exclusive_group,
            "priority": priority,
            "allow_child_fragments": allow_child_fragments,
        },
    }


def seed_rules() -> list[dict[str, Any]]:
    r = make_rule
    return [
        r("FG_CARBONYL", "carbonyl", "functional_group", "[CX3:1]=[OX1:2]", {"1": "carbonyl_carbon", "2": "carbonyl_oxygen"}, "carbonyl_carbon", ["polar", "pi_acceptor"], exclusive_group="carbonyl_family", priority=40),
        r("FG_AMIDE", "amide", "functional_group", "[NX3:1][CX3:2](=[OX1:3])", {"1": "amide_nitrogen", "2": "carbonyl_carbon", "3": "carbonyl_oxygen"}, "carbonyl_carbon", ["polar", "hydrogen_bonding", "backbone_possible"], parent_fragment_id="FG_CARBONYL", exclusive_group="carbonyl_family", priority=80),
        r("FG_IMIDE", "imide", "functional_group", "[NX3:1]([CX3:2](=[OX1:3]))[CX3:4](=[OX1:5])", {"1": "imide_nitrogen", "2": "carbonyl_carbon_a", "3": "carbonyl_oxygen_a", "4": "carbonyl_carbon_b", "5": "carbonyl_oxygen_b"}, "imide_nitrogen", ["polar", "rigidifying", "high_tg"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=95),
        r("FG_ESTER", "ester", "functional_group", "[CX3:1](=[OX1:2])[OX2:3]", {"1": "carbonyl_carbon", "2": "carbonyl_oxygen", "3": "ester_oxygen"}, "carbonyl_carbon", ["polar", "backbone_possible"], parent_fragment_id="FG_CARBONYL", exclusive_group="carbonyl_family", priority=75),
        r("FG_CARBONATE", "carbonate", "functional_group", "[OX2:1][CX3:2](=[OX1:3])[OX2:4]", {"1": "alkoxy_oxygen_a", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "alkoxy_oxygen_b"}, "carbonyl_carbon", ["polar", "backbone_possible"], parent_fragment_id="FG_ESTER", exclusive_group="carbonyl_family", priority=90),
        r("FG_URETHANE", "urethane", "functional_group", "[NX3:1][CX3:2](=[OX1:3])[OX2:4]", {"1": "urethane_nitrogen", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "alkoxy_oxygen"}, "carbonyl_carbon", ["polar", "hydrogen_bonding"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=90),
        r("FG_UREA", "urea", "functional_group", "[NX3:1][CX3:2](=[OX1:3])[NX3:4]", {"1": "urea_nitrogen_a", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "urea_nitrogen_b"}, "carbonyl_carbon", ["polar", "hydrogen_bonding"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=90),
        r("FG_KETONE", "ketone", "functional_group", "[#6:1][CX3:2](=[OX1:3])[#6:4]", {"1": "carbon_substituent_a", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "carbon_substituent_b"}, "carbonyl_carbon", ["polar"], parent_fragment_id="FG_CARBONYL", exclusive_group="carbonyl_family", priority=70),
        r("FG_ALDEHYDE", "aldehyde", "functional_group", "[CX3H1:1](=[OX1:2])[#6:3]", {"1": "aldehyde_carbon", "2": "carbonyl_oxygen", "3": "carbon_substituent"}, "aldehyde_carbon", ["polar"], parent_fragment_id="FG_CARBONYL", exclusive_group="carbonyl_family", priority=70),
        r("FG_CARBOXYLIC_ACID", "carboxylic_acid", "functional_group", "[CX3:1](=[OX1:2])[OX2H1:3]", {"1": "carbonyl_carbon", "2": "carbonyl_oxygen", "3": "acid_oxygen"}, "carbonyl_carbon", ["polar", "acidic", "hydrogen_bonding"], parent_fragment_id="FG_CARBONYL", exclusive_group="carbonyl_family", priority=80),
        r("FG_CARBOXYLATE", "carboxylate", "functional_group", "[CX3:1](=[OX1:2])[O-:3]", {"1": "carbonyl_carbon", "2": "carbonyl_oxygen", "3": "anionic_oxygen"}, "carbonyl_carbon", ["ionic", "polar"], parent_fragment_id="FG_CARBONYL", exclusive_group="ionic_family", priority=85),
        r("FG_ANHYDRIDE", "anhydride", "functional_group", "[CX3:1](=[OX1:2])[OX2:3][CX3:4](=[OX1:5])", {"1": "carbonyl_carbon_a", "2": "carbonyl_oxygen_a", "3": "bridging_oxygen", "4": "carbonyl_carbon_b", "5": "carbonyl_oxygen_b"}, "bridging_oxygen", ["polar", "reactive"], parent_fragment_id="FG_ESTER", exclusive_group="carbonyl_family", priority=90),
        r("FG_THIOCARBONYL", "thiocarbonyl", "functional_group", "[CX3:1]=[SX1:2]", {"1": "thiocarbonyl_carbon", "2": "thiocarbonyl_sulfur"}, "thiocarbonyl_carbon", ["polarizable"], exclusive_group="carbonyl_family", priority=65),
        r("FG_ETHER", "ether", "functional_group", "[OD2:1]([#6:2])[#6:3]", {"1": "ether_oxygen", "2": "carbon_substituent_a", "3": "carbon_substituent_b"}, "ether_oxygen", ["flexible", "polar", "backbone_possible"], exclusive_group="oxygen_linkage_family", priority=55),
        r("FG_AROMATIC_ETHER", "aromatic_ether", "functional_group", "[c:1][OX2:2][c:3]", {"1": "aryl_carbon_a", "2": "ether_oxygen", "3": "aryl_carbon_b"}, "ether_oxygen", ["flexible", "backbone_possible"], parent_fragment_id="FG_ETHER", exclusive_group="oxygen_linkage_family", priority=75),
        r("FG_THIOETHER", "thioether", "functional_group", "[SX2:1]([#6:2])[#6:3]", {"1": "thioether_sulfur", "2": "carbon_substituent_a", "3": "carbon_substituent_b"}, "thioether_sulfur", ["polarizable", "flexible"], exclusive_group="sulfur_family", priority=60),
        r("FG_SULFONE", "sulfone", "functional_group", "[SX4:1](=[OX1:2])(=[OX1:3])([#6:4])[#6:5]", {"1": "sulfone_sulfur", "2": "sulfone_oxygen_a", "3": "sulfone_oxygen_b", "4": "carbon_substituent_a", "5": "carbon_substituent_b"}, "sulfone_sulfur", ["polar", "rigidifying", "high_tg"], exclusive_group="sulfur_family", priority=90),
        r("FG_SULFOXIDE", "sulfoxide", "functional_group", "[SX3:1](=[OX1:2])([#6:3])[#6:4]", {"1": "sulfoxide_sulfur", "2": "sulfoxide_oxygen", "3": "carbon_substituent_a", "4": "carbon_substituent_b"}, "sulfoxide_sulfur", ["polar"], exclusive_group="sulfur_family", priority=80),
        r("FG_SULFONATE", "sulfonate", "functional_group", "[SX4:1](=[OX1:2])(=[OX1:3])[O-:4]", {"1": "sulfonate_sulfur", "2": "sulfonyl_oxygen_a", "3": "sulfonyl_oxygen_b", "4": "anionic_oxygen"}, "sulfonate_sulfur", ["ionic", "polar"], exclusive_group="ionic_family", priority=90),
        r("FG_NITRILE", "nitrile", "functional_group", "[CX2:1]#[NX1:2]", {"1": "nitrile_carbon", "2": "nitrile_nitrogen"}, "nitrile_carbon", ["polar", "rigidifying"], exclusive_group="nitrogen_family", priority=70),
        r("FG_HYDROXYL", "hydroxyl", "functional_group", "[OX2H:1]", {"1": "hydroxyl_oxygen"}, "hydroxyl_oxygen", ["polar", "hydrogen_bonding"], exclusive_group="oxygen_linkage_family", priority=60),
        r("FG_PRIMARY_AMINE", "primary_amine", "functional_group", "[NX3H2:1][#6:2]", {"1": "amine_nitrogen", "2": "carbon_substituent"}, "amine_nitrogen", ["basic", "hydrogen_bonding"], exclusive_group="nitrogen_family", priority=60),
        r("FG_SECONDARY_AMINE", "secondary_amine", "functional_group", "[NX3H1:1]([#6:2])[#6:3]", {"1": "amine_nitrogen", "2": "carbon_substituent_a", "3": "carbon_substituent_b"}, "amine_nitrogen", ["basic", "hydrogen_bonding"], exclusive_group="nitrogen_family", priority=60),
        r("FG_TERTIARY_AMINE", "tertiary_amine", "functional_group", "[NX3H0:1]([#6:2])([#6:3])[#6:4]", {"1": "amine_nitrogen", "2": "carbon_substituent_a", "3": "carbon_substituent_b", "4": "carbon_substituent_c"}, "amine_nitrogen", ["basic", "polar"], exclusive_group="nitrogen_family", priority=60),
        r("FG_QUATERNARY_AMMONIUM", "quaternary_ammonium", "functional_group", "[NX4+:1]([#6:2])([#6:3])([#6:4])[#6:5]", {"1": "ammonium_nitrogen", "2": "carbon_substituent_a", "3": "carbon_substituent_b", "4": "carbon_substituent_c", "5": "carbon_substituent_d"}, "ammonium_nitrogen", ["ionic", "polar"], exclusive_group="ionic_family", priority=90),
        r("FG_NITRO", "nitro", "functional_group", "[NX3+:1](=[OX1:2])[O-:3]", {"1": "nitro_nitrogen", "2": "nitro_oxygen_neutral", "3": "nitro_oxygen_anion"}, "nitro_nitrogen", ["polar", "electron_withdrawing"], exclusive_group="nitrogen_family", priority=80),
        r("FG_AZO", "azo", "functional_group", "[NX2:1]=[NX2:2]", {"1": "azo_nitrogen_a", "2": "azo_nitrogen_b"}, "azo_nitrogen_a", ["conjugated", "chromophore"], exclusive_group="nitrogen_family", priority=75),
        r("FG_ISOCYANATE", "isocyanate", "functional_group", "[NX2:1]=[CX2:2]=[OX1:3]", {"1": "isocyanate_nitrogen", "2": "isocyanate_carbon", "3": "isocyanate_oxygen"}, "isocyanate_carbon", ["reactive", "polar"], exclusive_group="carbonyl_family", priority=75),
        r("FG_EPOXY", "epoxy", "functional_group", "[OX2r3:1]1[CX4r3:2][CX4r3:3]1", {"1": "epoxy_oxygen", "2": "epoxy_carbon_a", "3": "epoxy_carbon_b"}, "epoxy_oxygen", ["reactive", "strained_ring"], exclusive_group="oxygen_linkage_family", priority=80),
        r("FG_ACETAL", "acetal", "functional_group", "[CX4:1]([OX2:2])([OX2:3])([#6:4])[#6:5]", {"1": "acetal_carbon", "2": "oxygen_a", "3": "oxygen_b", "4": "carbon_substituent_a", "5": "carbon_substituent_b"}, "acetal_carbon", ["oxygen_rich", "flexible"], exclusive_group="oxygen_linkage_family", priority=70),
        r("FG_SILOXANE", "siloxane", "functional_group", "[Si:1][OX2:2][Si:3]", {"1": "silicon_a", "2": "siloxane_oxygen", "3": "silicon_b"}, "siloxane_oxygen", ["flexible", "low_tg", "inorganic_backbone"], exclusive_group="silicon_family", priority=90),
        r("FG_SILANE", "silane", "functional_group", "[Si:1]([#6:2])([#6:3])[#6:4]", {"1": "silicon", "2": "carbon_substituent_a", "3": "carbon_substituent_b", "4": "carbon_substituent_c"}, "silicon", ["inorganic", "hydrophobic"], exclusive_group="silicon_family", priority=70),
        r("FG_PHOSPHAZENE", "phosphazene", "functional_group", "[P:1]=[N:2]", {"1": "phosphorus", "2": "phosphazene_nitrogen"}, "phosphorus", ["inorganic_backbone", "flame_retardant"], exclusive_group="phosphorus_family", priority=90),
        r("FG_PHOSPHATE", "phosphate", "functional_group", "[PX4:1](=[OX1:2])([OX2:3])([OX2:4])[OX2:5]", {"1": "phosphorus", "2": "phosphoryl_oxygen", "3": "oxygen_a", "4": "oxygen_b", "5": "oxygen_c"}, "phosphorus", ["polar", "flame_retardant"], exclusive_group="phosphorus_family", priority=80),
        r("SUB_HALOGEN", "halogen_substituent", "side_group", "[F,Cl,Br,I:1][#6:2]", {"1": "halogen", "2": "attached_carbon"}, "halogen", ["hydrophobic", "electron_withdrawing"], exclusive_group="halogen_family", priority=40),
        r("SUB_FLUORO", "fluoro_substituent", "side_group", "[F:1][#6:2]", {"1": "fluorine", "2": "attached_carbon"}, "fluorine", ["fluorinated", "hydrophobic"], parent_fragment_id="SUB_HALOGEN", exclusive_group="halogen_family", priority=60),
        r("SUB_CHLORO", "chloro_substituent", "side_group", "[Cl:1][#6:2]", {"1": "chlorine", "2": "attached_carbon"}, "chlorine", ["halogenated"], parent_fragment_id="SUB_HALOGEN", exclusive_group="halogen_family", priority=60),
        r("SUB_BROMO", "bromo_substituent", "side_group", "[Br:1][#6:2]", {"1": "bromine", "2": "attached_carbon"}, "bromine", ["halogenated"], parent_fragment_id="SUB_HALOGEN", exclusive_group="halogen_family", priority=60),
        r("SUB_TRIFLUOROMETHYL", "trifluoromethyl", "side_group", "[CX4:1]([F:2])([F:3])([F:4])[#6:5]", {"1": "cf3_carbon", "2": "fluorine_a", "3": "fluorine_b", "4": "fluorine_c", "5": "attached_carbon"}, "cf3_carbon", ["fluorinated", "hydrophobic", "electron_withdrawing"], parent_fragment_id="SUB_FLUORO", exclusive_group="halogen_family", priority=85),
        r("SUB_METHYL", "methyl", "side_group", "[CH3:1][#6:2]", {"1": "methyl_carbon", "2": "attached_carbon"}, "methyl_carbon", ["alkyl", "hydrophobic"], exclusive_group="alkyl_side_group_family", priority=45),
        r("SUB_ETHYL", "ethyl", "side_group", "[CH3:1][CH2:2][#6:3]", {"1": "terminal_methyl", "2": "methylene", "3": "attached_carbon"}, "methylene", ["alkyl", "hydrophobic"], parent_fragment_id="SUB_METHYL", exclusive_group="alkyl_side_group_family", priority=55),
        r("SUB_ISOPROPYL", "isopropyl", "side_group", "[CH:1]([CH3:2])([CH3:3])[#6:4]", {"1": "branch_carbon", "2": "methyl_a", "3": "methyl_b", "4": "attached_carbon"}, "branch_carbon", ["alkyl", "bulky"], exclusive_group="alkyl_side_group_family", priority=60),
        r("SUB_TERT_BUTYL", "tert_butyl", "side_group", "[C:1]([CH3:2])([CH3:3])([CH3:4])[#6:5]", {"1": "quaternary_carbon", "2": "methyl_a", "3": "methyl_b", "4": "methyl_c", "5": "attached_carbon"}, "quaternary_carbon", ["alkyl", "bulky"], exclusive_group="alkyl_side_group_family", priority=65),
        r("SUB_ALKOXY", "alkoxy_side_group", "side_group", "[OX2:1][CX4:2]", {"1": "alkoxy_oxygen", "2": "alkyl_carbon"}, "alkoxy_oxygen", ["flexible", "polar"], parent_fragment_id="FG_ETHER", exclusive_group="oxygen_linkage_family", priority=55),
        r("RING_AROMATIC_6", "aromatic_six_member_ring", "ring_structure", "[c:1]1[c:2][c:3][c:4][c:5][c:6]1", {"1": "aromatic_atom_1", "2": "aromatic_atom_2", "3": "aromatic_atom_3", "4": "aromatic_atom_4", "5": "aromatic_atom_5", "6": "aromatic_atom_6"}, "aromatic_atom_1", ["aromatic", "rigidifying", "pi_system"], exclusive_group="ring_family", priority=50),
        r("RING_HETEROAROMATIC_5", "heteroaromatic_five_member_ring", "ring_structure", "[a:1]1[a:2][a:3][a:4][n,o,s:5]1", {"1": "aromatic_atom_1", "2": "aromatic_atom_2", "3": "aromatic_atom_3", "4": "aromatic_atom_4", "5": "heteroaromatic_atom"}, "heteroaromatic_atom", ["aromatic", "heteroaromatic", "polar"], exclusive_group="ring_family", priority=70),
        r("RING_HETEROAROMATIC_6", "heteroaromatic_six_member_ring", "ring_structure", "[a:1]1[a:2][a:3][a:4][a:5][n,o,s:6]1", {"1": "aromatic_atom_1", "2": "aromatic_atom_2", "3": "aromatic_atom_3", "4": "aromatic_atom_4", "5": "aromatic_atom_5", "6": "heteroaromatic_atom"}, "heteroaromatic_atom", ["aromatic", "heteroaromatic", "polar"], exclusive_group="ring_family", priority=70),
        r("RING_FUSED_AROMATIC_ATOM", "fused_aromatic_ring_atom", "ring_structure", "[cR2:1]([c:2])[c:3]", {"1": "fused_aromatic_atom", "2": "neighbor_aromatic_atom_a", "3": "neighbor_aromatic_atom_b"}, "fused_aromatic_atom", ["aromatic", "fused_ring", "rigidifying"], exclusive_group="ring_family", priority=65),
        r("RING_CYCLOALIPHATIC_5", "cycloaliphatic_five_member_ring", "ring_structure", "[CX4R:1]1[CX4R:2][CX4R:3][CX4R:4][CX4R:5]1", {"1": "ring_carbon_1", "2": "ring_carbon_2", "3": "ring_carbon_3", "4": "ring_carbon_4", "5": "ring_carbon_5"}, "ring_carbon_1", ["cycloaliphatic", "hydrophobic"], exclusive_group="ring_family", priority=55),
        r("RING_CYCLOALIPHATIC_6", "cycloaliphatic_six_member_ring", "ring_structure", "[CX4R:1]1[CX4R:2][CX4R:3][CX4R:4][CX4R:5][CX4R:6]1", {"1": "ring_carbon_1", "2": "ring_carbon_2", "3": "ring_carbon_3", "4": "ring_carbon_4", "5": "ring_carbon_5", "6": "ring_carbon_6"}, "ring_carbon_1", ["cycloaliphatic", "hydrophobic"], exclusive_group="ring_family", priority=55),
        r("RING_IMIDE", "imide_ring", "ring_structure", "[NX3r:1]([CX3r:2](=[OX1:3]))[CX3r:4](=[OX1:5])", {"1": "imide_ring_nitrogen", "2": "carbonyl_carbon_a", "3": "carbonyl_oxygen_a", "4": "carbonyl_carbon_b", "5": "carbonyl_oxygen_b"}, "imide_ring_nitrogen", ["imide", "ring", "rigidifying"], parent_fragment_id="FG_IMIDE", exclusive_group="carbonyl_family", priority=100),
        r("RING_LACTONE", "lactone_ring", "ring_structure", "[OX2r:1][CX3r:2](=[OX1:3])", {"1": "ring_ester_oxygen", "2": "ring_carbonyl_carbon", "3": "carbonyl_oxygen"}, "ring_carbonyl_carbon", ["ester", "ring"], parent_fragment_id="FG_ESTER", exclusive_group="carbonyl_family", priority=85),
        r("RING_LACTAM", "lactam_ring", "ring_structure", "[NX3r:1][CX3r:2](=[OX1:3])", {"1": "ring_amide_nitrogen", "2": "ring_carbonyl_carbon", "3": "carbonyl_oxygen"}, "ring_carbonyl_carbon", ["amide", "ring"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=85),
        r("LINK_ALKYL", "alkyl_linker", "mainchain_linker", "[CX4:1]-[CX4:2]", {"1": "alkyl_carbon_a", "2": "alkyl_carbon_b"}, "alkyl_carbon_a", ["flexible", "hydrophobic", "backbone_possible"], exclusive_group="mainchain_linker_family", priority=35),
        r("LINK_METHYLENE", "methylene_linker", "mainchain_linker", "[CH2:1]", {"1": "methylene_carbon"}, "methylene_carbon", ["flexible", "backbone_possible"], exclusive_group="mainchain_linker_family", priority=30),
        r("LINK_VINYLENE", "vinylene_linker", "mainchain_linker", "[#6:1]=[#6:2]", {"1": "alkene_carbon_a", "2": "alkene_carbon_b"}, "alkene_carbon_a", ["unsaturated", "rigidifying"], exclusive_group="mainchain_linker_family", priority=55),
        r("LINK_ETHYNYLENE", "ethynylene_linker", "mainchain_linker", "[#6:1]#[#6:2]", {"1": "alkyne_carbon_a", "2": "alkyne_carbon_b"}, "alkyne_carbon_a", ["unsaturated", "rigid_linear"], exclusive_group="mainchain_linker_family", priority=60),
        r("LINK_PHENYLENE_PARA", "para_phenylene_linkage", "mainchain_linker", "[c:1]1[cH:2][cH:3][c:4][cH:5][cH:6]1", {"1": "aryl_connection_a", "2": "aryl_h_atom_2", "3": "aryl_h_atom_3", "4": "aryl_connection_b", "5": "aryl_h_atom_5", "6": "aryl_h_atom_6"}, "aryl_connection_a", ["aromatic", "rigid_linear"], parent_fragment_id="RING_AROMATIC_6", exclusive_group="ring_family", priority=65),
        r("LINK_AROMATIC_CARBONYL", "aromatic_carbonyl_linkage", "mainchain_linker", "[c:1][CX3:2](=[OX1:3])[c:4]", {"1": "aryl_carbon_a", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "aryl_carbon_b"}, "carbonyl_carbon", ["rigidifying", "polar"], parent_fragment_id="FG_KETONE", exclusive_group="carbonyl_family", priority=85),
        r("LINK_AROMATIC_SULFONE", "aromatic_sulfone_linkage", "mainchain_linker", "[c:1][SX4:2](=[OX1:3])(=[OX1:4])[c:5]", {"1": "aryl_carbon_a", "2": "sulfone_sulfur", "3": "oxygen_a", "4": "oxygen_b", "5": "aryl_carbon_b"}, "sulfone_sulfur", ["rigidifying", "polar"], parent_fragment_id="FG_SULFONE", exclusive_group="sulfur_family", priority=95),
        r("LINK_AROMATIC_SULFIDE", "aromatic_sulfide_linkage", "mainchain_linker", "[c:1][SX2:2][c:3]", {"1": "aryl_carbon_a", "2": "sulfide_sulfur", "3": "aryl_carbon_b"}, "sulfide_sulfur", ["polarizable", "flexible"], parent_fragment_id="FG_THIOETHER", exclusive_group="sulfur_family", priority=75),
        r("COMP_AROMATIC_AMIDE_N", "aromatic_amide_n_linkage", "composite_motif", "[c:1][NX3:2][CX3:3](=[OX1:4])", {"1": "aryl_carbon", "2": "amide_nitrogen", "3": "carbonyl_carbon", "4": "carbonyl_oxygen"}, "carbonyl_carbon", ["aromatic", "amide", "hydrogen_bonding"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=95),
        r("COMP_AROMATIC_AMIDE_C", "aromatic_amide_c_linkage", "composite_motif", "[c:1][CX3:2](=[OX1:3])[NX3:4]", {"1": "aryl_carbon", "2": "carbonyl_carbon", "3": "carbonyl_oxygen", "4": "amide_nitrogen"}, "carbonyl_carbon", ["aromatic", "amide", "rigidifying"], parent_fragment_id="FG_AMIDE", exclusive_group="carbonyl_family", priority=95),
        r("COMP_AROMATIC_IMIDE", "aromatic_imide", "composite_motif", "[c:1][NX3:2]([CX3:3](=[OX1:4]))[CX3:5](=[OX1:6])", {"1": "aryl_carbon", "2": "imide_nitrogen", "3": "carbonyl_carbon_a", "4": "carbonyl_oxygen_a", "5": "carbonyl_carbon_b", "6": "carbonyl_oxygen_b"}, "imide_nitrogen", ["aromatic", "imide", "rigidifying"], parent_fragment_id="FG_IMIDE", exclusive_group="carbonyl_family", priority=105),
        r("COMP_FLUORINATED_AROMATIC", "fluorinated_aromatic", "composite_motif", "[F:1][c:2]", {"1": "fluorine", "2": "aryl_carbon"}, "aryl_carbon", ["fluorinated", "aromatic", "hydrophobic"], parent_fragment_id="SUB_FLUORO", exclusive_group="halogen_family", priority=80),
        r("COMP_AROMATIC_ETHER", "aromatic_ether_linkage", "composite_motif", "[c:1][OX2:2][c:3]", {"1": "aryl_carbon_a", "2": "ether_oxygen", "3": "aryl_carbon_b"}, "ether_oxygen", ["aromatic", "flexible"], parent_fragment_id="FG_AROMATIC_ETHER", exclusive_group="oxygen_linkage_family", priority=80),
        r("COMP_BISPHENOL_A_BRIDGE", "bisphenol_a_bridge", "composite_motif", "[c:1][CX4:2]([CH3:3])([CH3:4])[c:5]", {"1": "aryl_carbon_a", "2": "isopropylidene_carbon", "3": "methyl_a", "4": "methyl_b", "5": "aryl_carbon_b"}, "isopropylidene_carbon", ["bulky", "hydrophobic", "cardo_like"], exclusive_group="alkyl_side_group_family", priority=85),
        r("COMP_PERFLUOROALKYL", "perfluoroalkyl_segment", "composite_motif", "[CX4:1]([F:2])([F:3])[CX4:4]([F:5])([F:6])", {"1": "fluorinated_carbon_a", "2": "fluorine_a", "3": "fluorine_b", "4": "fluorinated_carbon_b", "5": "fluorine_c", "6": "fluorine_d"}, "fluorinated_carbon_a", ["fluorinated", "hydrophobic"], parent_fragment_id="SUB_FLUORO", exclusive_group="halogen_family", priority=80),
        r("COMP_RIGID_ETHYNYL_AROMATIC", "rigid_ethynyl_aromatic_segment", "composite_motif", "[c:1][#6:2]#[#6:3][c:4]", {"1": "aryl_carbon_a", "2": "alkyne_carbon_a", "3": "alkyne_carbon_b", "4": "aryl_carbon_b"}, "alkyne_carbon_a", ["rigid_linear", "conjugated"], parent_fragment_id="LINK_ETHYNYLENE", exclusive_group="mainchain_linker_family", priority=85),
        r("COMP_CONJUGATED_AROMATIC_PAIR", "conjugated_aromatic_pair", "composite_motif", "[c:1]-[c:2]", {"1": "aromatic_atom_a", "2": "aromatic_atom_b"}, "aromatic_atom_a", ["aromatic", "conjugated"], parent_fragment_id="RING_AROMATIC_6", exclusive_group="ring_family", priority=45),
        r("COMP_POLYSILOXANE_SIDE", "polysiloxane_side_substituted", "composite_motif", "[Si:1]([#6:2])([#6:3])[OX2:4]", {"1": "silicon", "2": "carbon_substituent_a", "3": "carbon_substituent_b", "4": "siloxane_oxygen"}, "silicon", ["siloxane", "flexible"], parent_fragment_id="FG_SILOXANE", exclusive_group="silicon_family", priority=95),
    ]


def query_map(rule: dict[str, Any]) -> tuple[Any | None, dict[str, int], str | None]:
    query = Chem.MolFromSmarts(rule["match_rule"]["pattern"])
    if query is None:
        return None, {}, "SMARTS did not compile"
    role_to_query_index: dict[str, int] = {}
    map_ids_in_query: set[str] = set()
    for atom in query.GetAtoms():
        map_num = atom.GetAtomMapNum()
        if map_num:
            map_key = str(map_num)
            map_ids_in_query.add(map_key)
            role = rule["atom_roles"].get(map_key)
            if role:
                role_to_query_index[role] = atom.GetIdx()
    role_keys = set(rule["atom_roles"])
    if role_keys != map_ids_in_query:
        return query, role_to_query_index, f"atom_roles keys {sorted(role_keys)} do not match query maps {sorted(map_ids_in_query)}"
    anchor_role = rule["anchor_rule"]["anchor_role"]
    if anchor_role not in role_to_query_index:
        return query, role_to_query_index, f"anchor_role {anchor_role} is not mapped"
    return query, role_to_query_index, None


def validate_rules(rules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    required = [
        "fragment_id",
        "fragment_name",
        "version",
        "category",
        "parent_fragment_id",
        "semantic_tags",
        "match_rule",
        "atom_roles",
        "anchor_rule",
        "ownership_rule",
        "periodic_radius",
        "allow_boundary_crossing",
        "enable_cut_shift_scan",
        "max_cut_shift",
        "dedup_key_fields",
        "overlap_policy",
    ]
    ids = Counter(rule.get("fragment_id") for rule in rules)
    for rule in rules:
        rule_errors = []
        for field in required:
            if field not in rule:
                rule_errors.append(f"missing field {field}")
        if ids[rule.get("fragment_id")] > 1:
            rule_errors.append("duplicate fragment_id")
        query, _, query_error = query_map(rule)
        if query is None or query_error:
            rule_errors.append(query_error or "invalid SMARTS")
        if rule_errors:
            errors.append({"fragment_id": rule.get("fragment_id"), "errors": rule_errors})
        else:
            valid.append(rule)
    report = {
        "rule_count": len(rules),
        "valid_rule_count": len(valid),
        "invalid_rule_count": len(errors),
        "rule_compile_success_rate": len(valid) / len(rules) if rules else 0.0,
    }
    return valid, errors, report


def match_rules(
    rules: list[dict[str, Any]],
    canonical_records: list[CanonicalRecord],
) -> tuple[dict[str, Any], dict[str, set[str]], list[dict[str, Any]], list[dict[str, Any]]]:
    denominator = len(canonical_records)
    stats: dict[str, Any] = {}
    coverage_sets: dict[str, set[str]] = {}
    examples: list[dict[str, Any]] = []
    per_polymer_counts: list[int] = []

    compiled: dict[str, tuple[Any, dict[str, int]]] = {}
    for rule in rules:
        query, role_to_query_index, query_error = query_map(rule)
        if query_error or query is None:
            continue
        compiled[rule["fragment_id"]] = (query, role_to_query_index)

    for rule in rules:
        fragment_id = rule["fragment_id"]
        query, role_to_query_index = compiled[fragment_id]
        anchor_role = rule["anchor_rule"]["anchor_role"]
        anchor_query_index = role_to_query_index[anchor_role]
        coverage: set[str] = set()
        match_count = 0
        anchor_success = 0
        rule_examples: list[dict[str, Any]] = []

        for rec in canonical_records:
            matches = rec.mol.GetSubstructMatches(query, uniquify=True)
            if not matches:
                continue
            deduped_matches = sorted({tuple(match) for match in matches})
            coverage.add(rec.record_id)
            match_count += len(deduped_matches)
            anchor_success += sum(1 for match in deduped_matches if anchor_query_index < len(match))
            if len(rule_examples) < 5:
                match = deduped_matches[0]
                atoms_by_role = {
                    role: int(match[index])
                    for role, index in role_to_query_index.items()
                    if index < len(match)
                }
                rule_examples.append(
                    {
                        "fragment_id": fragment_id,
                        "record_id": rec.record_id,
                        "canonical_smiles": rec.canonical_smiles,
                        "source_smiles": rec.normalized_smiles_examples[0] if rec.normalized_smiles_examples else rec.canonical_smiles,
                        "match_atom_indices_by_role": atoms_by_role,
                    }
                )

        coverage_sets[fragment_id] = coverage
        stats[fragment_id] = {
            "polymer_coverage_count": len(coverage),
            "polymer_coverage_ratio": len(coverage) / denominator if denominator else 0.0,
            "match_count": match_count,
            "anchor_success_ratio": anchor_success / match_count if match_count else None,
            "cut_shift_stability": None,
        }
        examples.extend(rule_examples)

    record_to_fragment_count: Counter[str] = Counter()
    record_to_instance_count: Counter[str] = Counter()
    for fid, covered in coverage_sets.items():
        for record_id in covered:
            record_to_fragment_count[record_id] += 1
            record_to_instance_count[record_id] += 1
    for rec in canonical_records:
        per_polymer_counts.append(record_to_fragment_count[rec.record_id])

    coverage_report = {
        "denominator_level": "level_3_canonical_repeat_unit_unique",
        "denominator_count": denominator,
        "polymer_with_at_least_one_fragment": sum(1 for count in per_polymer_counts if count > 0),
        "polymer_with_at_least_one_fragment_ratio": (
            sum(1 for count in per_polymer_counts if count > 0) / denominator if denominator else 0.0
        ),
        "avg_fragment_types_per_polymer": statistics.fmean(per_polymer_counts) if per_polymer_counts else 0.0,
        "median_fragment_types_per_polymer": statistics.median(per_polymer_counts) if per_polymer_counts else 0.0,
        "rules_with_any_match": sum(1 for row in stats.values() if row["polymer_coverage_count"] > 0),
    }
    return stats, coverage_sets, examples, [coverage_report]


def select_core_rules(
    rules: list[dict[str, Any]],
    stats: dict[str, Any],
    denominator: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    min_count = max(50, math.ceil(denominator * 0.004))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for rule in rules:
        row = stats.get(rule["fragment_id"], {})
        count = row.get("polymer_coverage_count", 0)
        ratio = row.get("polymer_coverage_ratio", 0.0)
        anchor_ratio = row.get("anchor_success_ratio")
        if count >= min_count or ratio >= 0.004:
            if anchor_ratio is None or anchor_ratio >= 0.999:
                accepted.append(rule)
                continue
        rejected.append(
            {
                "fragment_id": rule["fragment_id"],
                "fragment_name": rule["fragment_name"],
                "coverage_count": count,
                "coverage_ratio": ratio,
                "status": "rejected_low_frequency",
                "threshold_count": min_count,
            }
        )

    accepted.sort(
        key=lambda rule: (
            rule["category"],
            -stats[rule["fragment_id"]]["polymer_coverage_count"],
            rule["fragment_id"],
        )
    )
    return accepted, rejected


def mine_motifs(canonical_records: list[CanonicalRecord], max_candidates: int = 300) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: dict[str, set[str]] = defaultdict(set)
    match_counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    atom_counts: dict[str, int] = {}

    for rec in canonical_records:
        seen_in_record: set[str] = set()
        for atom in rec.mol.GetAtoms():
            for radius in (1, 2):
                env = AllChem.FindAtomEnvironmentOfRadiusN(rec.mol, radius, atom.GetIdx())
                if not env:
                    continue
                submol = Chem.PathToSubmol(rec.mol, env)
                Chem.RemoveStereochemistry(submol)
                atom_count = submol.GetNumAtoms()
                if atom_count < 2 or atom_count > 8:
                    continue
                try:
                    motif = Chem.MolToSmiles(submol, canonical=True, isomericSmiles=False)
                except RuntimeError:
                    continue
                if not motif:
                    continue
                atom_counts[motif] = atom_count
                match_counts[motif] += 1
                seen_in_record.add(motif)
                examples.setdefault(motif, rec.canonical_smiles)
        for motif in seen_in_record:
            coverage[motif].add(rec.record_id)

    denominator = len(canonical_records)
    rows: list[dict[str, Any]] = []
    for motif, covered in coverage.items():
        count = len(covered)
        if count < 15:
            continue
        status = "accepted_core_candidate" if count >= max(50, math.ceil(denominator * 0.004)) else "accepted_auxiliary_candidate"
        rows.append(
            {
                "motif_smiles": motif,
                "atom_count": atom_counts[motif],
                "polymer_coverage_count": count,
                "polymer_coverage_ratio": count / denominator if denominator else 0.0,
                "match_count": match_counts[motif],
                "status": status,
                "example_canonical_smiles": examples[motif],
                "note": "Mined atom-centered radius-1/2 candidate; not promoted to core unless manually converted to anchored SMARTS.",
            }
        )

    rows.sort(key=lambda row: (-row["polymer_coverage_count"], row["atom_count"], row["motif_smiles"]))
    rows = rows[:max_candidates]

    clusters: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        cluster_key = f"atoms_{row['atom_count']}"
        clusters[cluster_key].append(row["motif_smiles"])
    cluster_rows = [
        {"cluster_id": key, "motif_count": len(values), "motif_smiles": values[:50]}
        for key, values in sorted(clusters.items())
    ]
    return rows, cluster_rows


def overlap_report(core_rules: list[dict[str, Any]], coverage_sets: dict[str, set[str]]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for idx, left in enumerate(core_rules):
        left_id = left["fragment_id"]
        left_set = coverage_sets.get(left_id, set())
        for right in core_rules[idx + 1 :]:
            right_id = right["fragment_id"]
            right_set = coverage_sets.get(right_id, set())
            union = left_set | right_set
            if not union:
                continue
            inter = left_set & right_set
            jaccard = len(inter) / len(union)
            containment_left = len(inter) / len(left_set) if left_set else 0.0
            containment_right = len(inter) / len(right_set) if right_set else 0.0
            if jaccard >= 0.80 or max(containment_left, containment_right) >= 0.90:
                pairs.append(
                    {
                        "fragment_id_a": left_id,
                        "fragment_id_b": right_id,
                        "jaccard": jaccard,
                        "containment_a": containment_left,
                        "containment_b": containment_right,
                        "exclusive_group_a": left["overlap_policy"]["exclusive_group"],
                        "exclusive_group_b": right["overlap_policy"]["exclusive_group"],
                    }
                )
    pairs.sort(key=lambda row: (-row["jaccard"], row["fragment_id_a"], row["fragment_id_b"]))
    return {
        "high_overlap_pairs": pairs,
        "high_overlap_pair_count": len(pairs),
        "exclusive_group_conflicts": [
            row
            for row in pairs
            if row["exclusive_group_a"] is not None and row["exclusive_group_a"] == row["exclusive_group_b"]
        ],
    }


def write_reports(
    *,
    data_hash: str,
    row_count: int,
    audit: dict[str, Any],
    schema_report: dict[str, Any],
    invalid_rules: list[dict[str, Any]],
    core_rules: list[dict[str, Any]],
    rejected_rules: list[dict[str, Any]],
    stats: dict[str, Any],
    coverage_report: dict[str, Any],
    overlap: dict[str, Any],
    mined_count: int,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    record_type_labels = {
        "main_repeat_unit": "主构建 repeat-unit 样本",
        "monomer_or_descriptor_record": "小分子/单体/描述符记录，不进入主词表",
        "incomplete_attachment": "连接点不完整样本",
        "copolymer_candidate": "共聚物或多 repeat-unit 候选",
        "ionomer_or_multicomponent_candidate": "离子/盐/多组分候选",
        "unresolved_R_group": "未定义 R 基样本",
        "parser_failed": "解析失败样本",
    }
    data_quality = [
        "# fragment_vocab_v1 数据质量报告",
        "",
        f"- 生成时间 UTC: `{generated_at}`",
        f"- 源数据: `{DATA_FILE}`",
        f"- 源数据 SHA256: `{data_hash}`",
        f"- CSV 行数: `{row_count}`",
        f"- RDKit 版本: `{rdBase.rdkitVersion}`",
        "",
        "## 去重层级统计",
        "",
        f"- level 1 raw unique: `{audit['level_1_raw_unique']}`",
        f"- level 1 文本排除后的两连接点主候选 raw unique: `{audit['level_1_raw_two_attachment_main_after_text_exclusions']}`",
        f"- level 2 attachment 统一后的主构建 unique: `{audit['level_2_attachment_normalized_main_unique']}`",
        f"- level 3 canonical repeat-unit unique: `{audit['level_3_canonical_repeat_unit_unique']}`",
        f"- level 4 repeat-unit graph hash unique: `{audit['level_4_repeat_unit_graph_hash_unique']}`",
        "- level 5 primitive periodic graph hash unique: `未实现`",
        "",
        "## 记录类型统计",
        "",
    ]
    for key, value in sorted(audit["record_type_counts_raw_unique"].items()):
        data_quality.append(f"- {key}: `{value}`（{record_type_labels.get(key, '未定义类型')}）")
    (PROCESSED_DIR / "data_quality_report.md").write_text("\n".join(data_quality) + "\n", encoding="utf-8")

    validation_lines = [
        "# fragment_vocab_v1.0 验证报告",
        "",
        f"- 生成时间 UTC: `{generated_at}`",
        f"- 源数据 SHA256: `{data_hash}`",
        f"- RDKit 版本: `{rdBase.rdkitVersion}`",
        f"- 覆盖率分母层级: `{coverage_report['denominator_level']}`",
        f"- 覆盖率分母数量: `{coverage_report['denominator_count']}`",
        "",
        "## 规则可执行性",
        "",
        f"- seed 规则数: `{schema_report['rule_count']}`",
        f"- 有效 seed 规则数: `{schema_report['valid_rule_count']}`",
        f"- 无效规则数: `{schema_report['invalid_rule_count']}`",
        f"- 规则编译成功率: `{schema_report['rule_compile_success_rate']:.4f}`",
        f"- 最终核心规则数: `{len(core_rules)}`",
        f"- 因低频未进入核心的规则数: `{len(rejected_rules)}`",
        "",
        "## 覆盖率",
        "",
        f"- 至少匹配 1 个 fragment 的 polymer 数: `{coverage_report['polymer_with_at_least_one_fragment']}`",
        f"- 至少匹配 1 个 fragment 的比例: `{coverage_report['polymer_with_at_least_one_fragment_ratio']:.4f}`",
        f"- 每个 polymer 平均 fragment 类型数: `{coverage_report['avg_fragment_types_per_polymer']:.4f}`",
        f"- 每个 polymer 的 fragment 类型数中位数: `{coverage_report['median_fragment_types_per_polymer']}`",
        f"- 至少有一次命中的规则数: `{coverage_report['rules_with_any_match']}`",
        "",
        "## Motif 挖掘",
        "",
        f"- 写出的 mined candidate 数: `{mined_count}`",
        "- mined candidate 只作为人工审核候选保留；只有补齐稳定 anchor SMARTS 规则后才会提升到核心词表。",
        "",
        "## 稳定性",
        "",
        "- cut-shift 稳定性: `未评估`",
        "- 边界归属准确率: `未评估`",
        "- 原因：当前仓库此前没有物化的 periodic repeat-unit graph builder 和 cut-shift scanner。本次生成的核心词表已经保留匹配器所需的 schema 字段。",
        "",
        "## 重叠与冲突",
        "",
        f"- 高重叠规则对数量: `{overlap['high_overlap_pair_count']}`",
        f"- 同 exclusive group 内冲突数量: `{len(overlap['exclusive_group_conflicts'])}`",
        "",
        "## 覆盖率最高的核心 fragments",
        "",
    ]
    top_rules = sorted(core_rules, key=lambda rule: -stats[rule["fragment_id"]]["polymer_coverage_count"])[:25]
    for rule in top_rules:
        row = stats[rule["fragment_id"]]
        validation_lines.append(
            f"- {rule['fragment_id']}: `{row['polymer_coverage_count']}` ({row['polymer_coverage_ratio']:.4f})"
        )
    if invalid_rules:
        validation_lines.extend(["", "## 无效 seed 规则", ""])
        for row in invalid_rules:
            validation_lines.append(f"- {row['fragment_id']}: {row['errors']}")
    VALIDATION_REPORT.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")

    write_json(
        VALIDATION_DIR / "review_report.json",
        {
            "review_status": "automated_draft",
            "manual_review_required": True,
            "manual_review_reason": "化学语义正确性和 cut-shift 稳定性仍需要领域审核，并依赖 periodic graph matcher 做最终验证。",
            "generated_at_utc": generated_at,
            "core_rule_count": len(core_rules),
            "rejected_low_frequency_rules": rejected_rules,
        },
    )
    write_json(VALIDATION_DIR / "coverage_report.json", coverage_report)
    write_json(VALIDATION_DIR / "overlap_report.json", overlap)
    write_json(
        VALIDATION_DIR / "stability_report.json",
        {
            "cut_shift_stability": None,
            "presence_label_consistency": None,
            "instance_key_jaccard": None,
            "status": "not_evaluated",
            "reason": "当前仓库尚未实现 periodic repeat-unit graph cut-shift scanner。",
        },
    )


def build() -> dict[str, Any]:
    ensure_dirs()
    data_hash = sha256_file(DATA_FILE)
    rows, grouped = read_property_records(DATA_FILE)
    clean_rows, canonical_records, failed_cases, audit = canonicalize_main_records(grouped)

    write_jsonl(PROCESSED_DIR / "property_records_by_polymer.jsonl", audit.pop("property_records_rows"))
    write_jsonl(PROCESSED_DIR / "clean_polymer_strings_main.jsonl", clean_rows)
    write_jsonl(
        PROCESSED_DIR / "canonical_repeat_units.jsonl",
        [
            {
                "record_id": rec.record_id,
                "canonical_repeat_unit_string": rec.canonical_smiles,
                "canonical_hash": rec.canonical_hash,
                "graph_hash": rec.graph_hash,
                "attachment_normalized_smiles_examples": rec.normalized_smiles_examples,
                "raw_smiles_examples": rec.raw_smiles_examples,
                "source_level2_count": rec.source_count,
            }
            for rec in canonical_records
        ],
    )
    write_jsonl(PROCESSED_DIR / "repeat_unit_graphs.jsonl", repeat_unit_graph_rows(canonical_records))
    write_jsonl(PROCESSED_DIR / "graph_failed_cases.jsonl", [row for row in failed_cases if row["stage"] == "phase_1_canonicalization"])

    seeds = seed_rules()
    write_jsonl(SEED_DIR / "seed_fragment_rules_v0.jsonl", seeds)
    valid_seed_rules, invalid_rules, schema_report = validate_rules(seeds)

    seed_stats, seed_coverage_sets, seed_examples, coverage_reports = match_rules(valid_seed_rules, canonical_records)
    coverage_report_seed = coverage_reports[0]
    core_rules, rejected_rules = select_core_rules(valid_seed_rules, seed_stats, len(canonical_records))
    core_stats, core_coverage_sets, core_examples, coverage_reports_core = match_rules(core_rules, canonical_records)
    coverage_report = coverage_reports_core[0]

    mined_rows, cluster_rows = mine_motifs(canonical_records)
    write_jsonl(MINING_DIR / "mined_motif_candidates.jsonl", mined_rows)
    write_jsonl(MINING_DIR / "motif_clusters.jsonl", cluster_rows)

    overlap = overlap_report(core_rules, core_coverage_sets)

    write_jsonl(VOCAB_JSONL, core_rules)
    write_json(VOCAB_JSON, core_rules)
    write_json(STATS_JSON, {fid: core_stats[fid] for fid in sorted(core_stats)})
    write_jsonl(EXAMPLES_JSONL, core_examples)
    write_jsonl(FAILED_JSONL, failed_cases)

    write_reports(
        data_hash=data_hash,
        row_count=len(rows),
        audit=audit,
        schema_report=schema_report,
        invalid_rules=invalid_rules,
        core_rules=core_rules,
        rejected_rules=rejected_rules,
        stats=core_stats,
        coverage_report=coverage_report,
        overlap=overlap,
        mined_count=len(mined_rows),
    )

    summary = {
        "source_data": str(DATA_FILE),
        "source_sha256": data_hash,
        "csv_rows": len(rows),
        "rdkit_version": rdBase.rdkitVersion,
        "audit": audit,
        "seed_rule_count": len(seeds),
        "valid_seed_rule_count": len(valid_seed_rules),
        "invalid_seed_rule_count": len(invalid_rules),
        "core_rule_count": len(core_rules),
        "mined_candidate_count": len(mined_rows),
        "coverage": coverage_report,
        "outputs": {
            "core_vocab_jsonl": str(VOCAB_JSONL),
            "core_vocab_json": str(VOCAB_JSON),
            "stats": str(STATS_JSON),
            "examples": str(EXAMPLES_JSONL),
            "validation_report": str(VALIDATION_REPORT),
            "failed_cases": str(FAILED_JSONL),
        },
    }
    write_json(FRAGMENT_DIR / "fragment_vocab_v1.0.build_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fragment_vocab_v1.0 from the polymer SMILES CSV.")
    parser.add_argument("--summary", action="store_true", help="Print the build summary JSON to stdout.")
    args = parser.parse_args()
    summary = build()
    if args.summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"wrote {VOCAB_JSONL}")


if __name__ == "__main__":
    main()
