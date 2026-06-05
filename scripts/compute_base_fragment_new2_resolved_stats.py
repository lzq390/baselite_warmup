from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCAB = ROOT / "fragments_1" / "base_fragment_new2.json"
DEFAULT_PERIODS = ROOT / "data" / "processed" / "periods2_from_unique_standardized_smiles.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "base_fragment_new2_resolved_stats.csv"
DEFAULT_RING_MATCH_OUTPUT = ROOT / "data" / "processed" / "base_fragment_new2_ring_matches.jsonl"

try:
    from rdkit import Chem, RDLogger, rdBase
except Exception as exc:  # pragma: no cover - clear CLI failure.
    raise SystemExit("RDKit is required. Use the baselite_warmup conda environment.") from exc


RDLogger.DisableLog("rdApp.*")


ACTIVE_CORE_STATUS = "core"
VALID_CORE_STATUSES = {"core", "derived_attribute", "deprecated_alias", "rejected"}
VALID_CONSTRAINT_KEYS = {
    "exact_fluorine_count",
    "exclude_atom_role_adjacent_to_carbonyl",
    "exclude_perfluoroalkyl_chain",
}
VALID_MATCH_RULE_TYPES = {"smarts", "rdkit_ring", "derived_view"}


def query_map(rule: dict[str, Any]) -> tuple[Any, dict[str, int]]:
    match_rule = rule["match_rule"]
    match_type = match_rule.get("type", "smarts")
    if match_type in {"rdkit_ring", "derived_view"}:
        role_to_query_index = {}
        for map_num, role in rule.get("atom_roles", {}).items():
            try:
                role_to_query_index[role] = int(map_num) - 1
            except ValueError:
                continue
        return None, role_to_query_index

    query = Chem.MolFromSmarts(rule["match_rule"]["pattern"])
    if query is None:
        raise ValueError(f"SMARTS did not compile for {rule['fragment_id']}")
    role_to_query_index: dict[str, int] = {}
    for atom in query.GetAtoms():
        map_num = atom.GetAtomMapNum()
        if not map_num:
            continue
        role = rule["atom_roles"].get(str(map_num))
        if role:
            role_to_query_index[role] = atom.GetIdx()
    return query, role_to_query_index


def is_active_core(rule: dict[str, Any]) -> bool:
    return rule.get("core_status", ACTIVE_CORE_STATUS) == ACTIVE_CORE_STATUS


def validate_rule(rule: dict[str, Any]) -> None:
    status = rule.get("core_status", ACTIVE_CORE_STATUS)
    if status not in VALID_CORE_STATUSES:
        raise ValueError(f"Unsupported core_status for {rule['fragment_id']}: {status}")
    match_rule = rule.get("match_rule", {})
    match_type = match_rule.get("type", "smarts")
    if match_type not in VALID_MATCH_RULE_TYPES:
        raise ValueError(f"Unsupported match_rule type for {rule['fragment_id']}: {match_type}")
    if match_type == "rdkit_ring":
        if "ring_size" not in match_rule:
            raise ValueError(f"rdkit_ring rule must define ring_size for {rule['fragment_id']}")
        if match_rule.get("ring_filter", "any") not in {
            "any",
            "carbocycle",
            "heterocycle",
            "polycyclic",
            "aromatic",
            "nonaromatic",
        }:
            raise ValueError(f"Unsupported ring_filter for {rule['fragment_id']}: {match_rule.get('ring_filter')}")
    if match_type == "smarts" and "pattern" not in match_rule:
        raise ValueError(f"SMARTS rule must define pattern for {rule['fragment_id']}")
    constraints = match_rule.get("constraints", {})
    unknown_constraints = set(constraints) - VALID_CONSTRAINT_KEYS
    if unknown_constraints:
        unknown = ", ".join(sorted(unknown_constraints))
        raise ValueError(f"Unsupported constraint(s) for {rule['fragment_id']}: {unknown}")


def atoms_for_roles(match: tuple[int, ...], role_to_query_index: dict[str, int], roles: list[str]) -> frozenset[int]:
    return frozenset(match[role_to_query_index[role]] for role in roles)


def atom_for_role(match: tuple[int, ...], role_to_query_index: dict[str, int], role: str) -> int:
    return match[role_to_query_index[role]]


def is_carbonyl_carbon(atom: Any) -> bool:
    if atom.GetAtomicNum() != 6:
        return False
    for bond in atom.GetBonds():
        other = bond.GetOtherAtom(atom)
        if other.GetAtomicNum() == 8 and bond.GetBondType() == Chem.BondType.DOUBLE:
            return True
    return False


def atom_is_adjacent_to_carbonyl(atom: Any) -> bool:
    return any(is_carbonyl_carbon(neighbor) for neighbor in atom.GetNeighbors())


def fluorine_neighbor_count(atom: Any) -> int:
    return sum(1 for neighbor in atom.GetNeighbors() if neighbor.GetAtomicNum() == 9)


def ring_atom_ring_membership_counts(mol: Any) -> Counter[int]:
    return Counter(atom_idx for ring in mol.GetRingInfo().AtomRings() for atom_idx in ring)


def ring_external_neighbor_indices(mol: Any, ring: tuple[int, ...], atom_idx: int) -> list[int]:
    ring_atoms = set(ring)
    atom = mol.GetAtomWithIdx(atom_idx)
    return [neighbor.GetIdx() for neighbor in atom.GetNeighbors() if neighbor.GetIdx() not in ring_atoms]


def ring_external_neighbor_bonds(mol: Any, ring: tuple[int, ...], atom_idx: int) -> list[tuple[int, Any]]:
    ring_atoms = set(ring)
    atom = mol.GetAtomWithIdx(atom_idx)
    neighbors: list[tuple[int, Any]] = []
    for neighbor in atom.GetNeighbors():
        neighbor_idx = neighbor.GetIdx()
        if neighbor_idx in ring_atoms:
            continue
        bond = mol.GetBondBetweenAtoms(atom_idx, neighbor_idx)
        neighbors.append((neighbor_idx, bond))
    return neighbors


def ring_connection_positions(mol: Any, ring: tuple[int, ...]) -> dict[str, list[int]]:
    ring_membership_counts = ring_atom_ring_membership_counts(mol)
    external_positions = []
    exocyclic_substituent_positions = []
    polycyclic_connection_positions = []
    for position, atom_idx in enumerate(ring):
        external_bonds = ring_external_neighbor_bonds(mol, ring, atom_idx)
        if external_bonds:
            external_positions.append(position)
        if any(not bond.IsInRing() for _, bond in external_bonds):
            exocyclic_substituent_positions.append(position)
        if ring_membership_counts[atom_idx] > 1:
            polycyclic_connection_positions.append(position)
    return {
        "external": external_positions,
        "exocyclic_substituent": exocyclic_substituent_positions,
        "polycyclic_connection": polycyclic_connection_positions,
    }


def substitution_topology(positions: list[int], ring_size: int) -> str:
    substitution_count = len(positions)
    if substitution_count == 0:
        return "none"
    if substitution_count == 1:
        return "mono"
    normalized_positions = sorted(set(position % ring_size for position in positions))
    candidates = []
    for anchor in normalized_positions:
        for direction in (1, -1):
            oriented = sorted(((position - anchor) * direction) % ring_size for position in normalized_positions)
            candidates.append(tuple(position + 1 for position in oriented))
    return ",".join(str(position) for position in min(candidates))


def hetero_atom_signature(hetero_symbols: list[str]) -> str:
    if not hetero_symbols:
        return "none"
    counts = Counter(hetero_symbols)
    parts = []
    for symbol in sorted(counts):
        count = counts[symbol]
        parts.append(symbol if count == 1 else f"{symbol}{count}")
    return ",".join(parts)


def ring_aromaticity_class(aromatic_atom_count: int, ring_size: int) -> str:
    if aromatic_atom_count == ring_size:
        return "fully_aromatic"
    if aromatic_atom_count == 0:
        return "nonaromatic"
    return "partially_aromatic"


def mainchain_through_ring_label(dummy_attachment_count: int) -> str:
    if dummy_attachment_count >= 2:
        return "true"
    return "unknown"


def ring_match_attributes(rule: dict[str, Any], mol: Any, match: tuple[int, ...]) -> dict[str, Any]:
    atoms = [mol.GetAtomWithIdx(atom_idx) for atom_idx in match]
    hetero_symbols = sorted(atom.GetSymbol() for atom in atoms if atom.GetAtomicNum() != 6)
    aromatic_atom_count = sum(1 for atom in atoms if atom.GetIsAromatic())
    aromaticity_class = ring_aromaticity_class(aromatic_atom_count, len(match))
    ring_membership_counts = ring_atom_ring_membership_counts(mol)
    connection_positions = ring_connection_positions(mol, match)
    external_positions = connection_positions["external"]
    exocyclic_substituent_positions = connection_positions["exocyclic_substituent"]
    polycyclic_connection_positions = connection_positions["polycyclic_connection"]
    dummy_attachment_count = 0
    for atom_idx in match:
        for neighbor_idx in ring_external_neighbor_indices(mol, match, atom_idx):
            if mol.GetAtomWithIdx(neighbor_idx).GetAtomicNum() == 0:
                dummy_attachment_count += 1

    return {
        "ring_size": len(match),
        "ring_atom_class": "heterocycle" if hetero_symbols else "carbocycle",
        "hetero_atom_count": len(hetero_symbols),
        "hetero_atom_symbols": hetero_symbols,
        "hetero_atom_signature": hetero_atom_signature(hetero_symbols),
        "aromaticity": aromaticity_class,
        "ring_aromatic_atom_count": aromatic_atom_count,
        "ring_aromaticity_class": aromaticity_class,
        "polycyclic": any(ring_membership_counts[atom_idx] > 1 for atom_idx in match),
        "external_connection_count": len(external_positions),
        "external_connection_topology": substitution_topology(external_positions, len(match)),
        "exocyclic_substituent_count": len(exocyclic_substituent_positions),
        "exocyclic_substituent_topology": substitution_topology(exocyclic_substituent_positions, len(match)),
        "polycyclic_connection_count": len(polycyclic_connection_positions),
        "polycyclic_connection_topology": substitution_topology(polycyclic_connection_positions, len(match)),
        "substitution_count": len(exocyclic_substituent_positions),
        "substitution_topology": substitution_topology(exocyclic_substituent_positions, len(match)),
        "attachment_count": dummy_attachment_count,
        "mainchain_through_ring": mainchain_through_ring_label(dummy_attachment_count),
    }


def ring_passes_filter(rule: dict[str, Any], mol: Any, ring: tuple[int, ...]) -> bool:
    match_rule = rule["match_rule"]
    if len(ring) != int(match_rule["ring_size"]):
        return False
    ring_filter = match_rule.get("ring_filter", "any")
    attrs = ring_match_attributes(rule, mol, ring)
    if ring_filter == "any":
        return True
    if ring_filter == "carbocycle":
        return attrs["ring_atom_class"] == "carbocycle"
    if ring_filter == "heterocycle":
        return attrs["ring_atom_class"] == "heterocycle"
    if ring_filter == "polycyclic":
        return bool(attrs["polycyclic"])
    if ring_filter == "aromatic":
        return attrs["ring_aromaticity_class"] == "fully_aromatic"
    if ring_filter == "nonaromatic":
        return attrs["ring_aromaticity_class"] != "fully_aromatic"
    return False


def get_raw_matches(rule: dict[str, Any], mol: Any, query: Any) -> tuple[tuple[int, ...], ...]:
    match_type = rule.get("match_rule", {}).get("type", "smarts")
    if match_type == "derived_view":
        return ()
    if match_type == "rdkit_ring":
        return tuple(
            tuple(ring)
            for ring in mol.GetRingInfo().AtomRings()
            if ring_passes_filter(rule, mol, tuple(ring))
        )
    return mol.GetSubstructMatches(query, uniquify=True)


def match_attributes(rule: dict[str, Any], mol: Any, match: tuple[int, ...]) -> dict[str, Any]:
    if rule.get("match_rule", {}).get("type", "smarts") == "rdkit_ring":
        return ring_match_attributes(rule, mol, match)
    return {}


def attached_carbon_is_fluorinated(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> bool:
    try:
        attached_atom = mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, "attached_carbon"))
    except KeyError:
        return False
    return any(neighbor.GetAtomicNum() == 9 for neighbor in attached_atom.GetNeighbors())


def passes_constraints(
    *,
    rule: dict[str, Any],
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> bool:
    constraints = rule.get("match_rule", {}).get("constraints", {})
    adjacent_roles = constraints.get("exclude_atom_role_adjacent_to_carbonyl", [])
    if isinstance(adjacent_roles, str):
        adjacent_roles = [adjacent_roles]
    for role in adjacent_roles:
        atom = mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, role))
        if atom_is_adjacent_to_carbonyl(atom):
            return False

    if "exact_fluorine_count" in constraints:
        role = constraints.get("fluorine_count_atom_role", "trifluoromethyl_carbon")
        atom = mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, role))
        if fluorine_neighbor_count(atom) != constraints["exact_fluorine_count"]:
            return False

    if constraints.get("exclude_perfluoroalkyl_chain"):
        if attached_carbon_is_fluorinated(mol, match, role_to_query_index):
            return False

    return True


def dedup_key_for_match(
    *,
    rule: dict[str, Any],
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> tuple[Any, ...]:
    if rule.get("match_rule", {}).get("type", "smarts") == "rdkit_ring":
        return ("ring_atom_set", frozenset(match))

    dedup = rule.get("deduplication")
    if dedup:
        values: list[Any] = []
        for role in dedup.get("roles", []):
            values.append(atom_for_role(match, role_to_query_index, role))
        for role_group in dedup.get("unordered_role_groups", []):
            values.append(tuple(sorted(atom_for_role(match, role_to_query_index, role) for role in role_group)))
        for role_group in dedup.get("atom_set_role_groups", []):
            values.append(frozenset(atom_for_role(match, role_to_query_index, role) for role in role_group))
        return tuple(values)

    anchor_rule = rule.get("anchor_rule", {})
    if anchor_rule.get("anchor_type") == "atom":
        anchor_role = anchor_rule.get("anchor_role")
        if anchor_role in role_to_query_index:
            return ("atom", atom_for_role(match, role_to_query_index, anchor_role))

    return ("atom_set", frozenset(match))


def normalize_matches(
    *,
    rule: dict[str, Any],
    mol: Any,
    raw_matches: tuple[tuple[int, ...], ...],
    role_to_query_index: dict[str, int],
) -> tuple[tuple[int, ...], ...]:
    normalized: dict[tuple[Any, ...], tuple[int, ...]] = {}
    for match in raw_matches:
        if not passes_constraints(rule=rule, mol=mol, match=match, role_to_query_index=role_to_query_index):
            continue
        key = dedup_key_for_match(rule=rule, match=match, role_to_query_index=role_to_query_index)
        normalized.setdefault(key, match)
    return tuple(normalized.values())


def apply_instance_suppression(
    *,
    fragment_id: str,
    rule: dict[str, Any],
    matches_by_fragment: dict[str, tuple[tuple[int, ...], ...]],
    role_index_by_fragment: dict[str, dict[str, int]],
) -> list[tuple[int, ...]]:
    matches = list(matches_by_fragment.get(fragment_id, ()))
    suppression = rule.get("overlap_policy", {}).get("instance_suppression")
    if not suppression:
        return matches

    mode = suppression.get("mode")
    if mode == "drop_if_core_atoms_covered_by_higher_priority":
        covered_cores: set[frozenset[int]] = set()
        for covering in suppression.get("covering_fragments", []):
            covering_id = covering["fragment_id"]
            covering_roles = role_index_by_fragment[covering_id]
            for covering_match in matches_by_fragment.get(covering_id, ()):
                for role_set in covering.get("core_atom_role_sets", []):
                    covered_cores.add(atoms_for_roles(covering_match, covering_roles, role_set))
        target_roles = role_index_by_fragment[fragment_id]
        core_roles = suppression["core_atom_roles"]
        return [
            match
            for match in matches
            if atoms_for_roles(match, target_roles, core_roles) not in covered_cores
        ]

    if mode == "drop_if_anchor_covered_by_higher_priority":
        covered_anchors: set[int] = set()
        for covering in suppression.get("covering_fragments", []):
            covering_id = covering["fragment_id"]
            covering_roles = role_index_by_fragment[covering_id]
            anchor_index = covering_roles[covering["anchor_role"]]
            for covering_match in matches_by_fragment.get(covering_id, ()):
                covered_anchors.add(covering_match[anchor_index])
        target_roles = role_index_by_fragment[fragment_id]
        target_anchor_index = target_roles[suppression["anchor_role"]]
        return [match for match in matches if match[target_anchor_index] not in covered_anchors]

    raise ValueError(f"Unsupported instance_suppression mode for {fragment_id}: {mode}")


def update_stats(stats: dict[str, Any], fragment_id: str, source_id: str, match_count: int) -> None:
    if match_count <= 0:
        return
    row = stats[fragment_id]
    row["period_hits"] += 1
    row["source_ids"].add(source_id)
    row["match_total"] += match_count
    row["max_per_period"] = max(row["max_per_period"], match_count)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute raw and resolved stats for base_fragment_new2.")
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--periods", type=Path, default=DEFAULT_PERIODS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ring-match-output", type=Path, default=DEFAULT_RING_MATCH_OUTPUT)
    args = parser.parse_args()

    rules = json.loads(args.vocab.read_text(encoding="utf-8"))
    queries: dict[str, Any] = {}
    role_index_by_fragment: dict[str, dict[str, int]] = {}
    for rule in rules:
        validate_rule(rule)
        query, role_index = query_map(rule)
        queries[rule["fragment_id"]] = query
        role_index_by_fragment[rule["fragment_id"]] = role_index

    raw_substruct_stats = {
        rule["fragment_id"]: {"period_hits": 0, "source_ids": set(), "match_total": 0, "max_per_period": 0}
        for rule in rules
    }
    normalized_stats = {
        rule["fragment_id"]: {"period_hits": 0, "source_ids": set(), "match_total": 0, "max_per_period": 0}
        for rule in rules
    }
    resolved_stats = {
        rule["fragment_id"]: {"period_hits": 0, "source_ids": set(), "match_total": 0, "max_per_period": 0}
        for rule in rules
    }

    with args.periods.open("r", encoding="utf-8", newline="") as handle:
        period_rows = list(csv.DictReader(handle))

    parser_failed = 0
    ring_match_records: list[dict[str, Any]] = []
    for row_index, row in enumerate(period_rows):
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is None:
            parser_failed += 1
            continue
        source_id = row.get("source_canonical_id", "")
        matches_by_fragment = {
            rule["fragment_id"]: get_raw_matches(rule, mol, queries[rule["fragment_id"]])
            for rule in rules
        }
        normalized_matches_by_fragment = {
            rule["fragment_id"]: normalize_matches(
                rule=rule,
                mol=mol,
                raw_matches=matches_by_fragment[rule["fragment_id"]],
                role_to_query_index=role_index_by_fragment[rule["fragment_id"]],
            )
            for rule in rules
        }
        for rule in rules:
            fragment_id = rule["fragment_id"]
            raw_matches = matches_by_fragment[fragment_id]
            normalized_matches = normalized_matches_by_fragment[fragment_id]
            update_stats(raw_substruct_stats, fragment_id, source_id, len(raw_matches))
            update_stats(normalized_stats, fragment_id, source_id, len(normalized_matches))
            resolved_matches = apply_instance_suppression(
                fragment_id=fragment_id,
                rule=rule,
                matches_by_fragment=normalized_matches_by_fragment,
                role_index_by_fragment=role_index_by_fragment,
            )
            if rule.get("match_rule", {}).get("type") == "rdkit_ring":
                resolved_match_set = set(resolved_matches)
                for match_index, match in enumerate(normalized_matches):
                    ring_match_records.append(
                        {
                            "period_row_index": row_index,
                            "source_canonical_id": source_id,
                            "fragment_id": fragment_id,
                            "fragment_name": rule["fragment_name"],
                            "match_index": match_index,
                            "atom_indices": list(match),
                            "active_core": is_active_core(rule),
                            "resolved": is_active_core(rule) and match in resolved_match_set,
                            "attributes": match_attributes(rule, mol, match),
                        }
                    )
            if is_active_core(rule):
                update_stats(resolved_stats, fragment_id, source_id, len(resolved_matches))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.ring_match_output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "fragment_id",
        "fragment_name",
        "category",
        "core_status",
        "active_core",
        "priority",
        "suppression_mode",
        "raw_substruct_period_hits",
        "raw_substruct_source_hits",
        "raw_substruct_match_total",
        "raw_substruct_max_per_period",
        "normalized_period_hits",
        "normalized_source_hits",
        "normalized_match_total",
        "normalized_max_per_period",
        "resolved_period_hits",
        "resolved_source_hits",
        "resolved_match_total",
        "resolved_max_per_period",
    ]
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for rule in rules:
            fragment_id = rule["fragment_id"]
            raw = raw_substruct_stats[fragment_id]
            normalized = normalized_stats[fragment_id]
            resolved = resolved_stats[fragment_id]
            writer.writerow(
                {
                    "fragment_id": fragment_id,
                    "fragment_name": rule["fragment_name"],
                    "category": rule["category"],
                    "core_status": rule.get("core_status", ACTIVE_CORE_STATUS),
                    "active_core": int(is_active_core(rule)),
                    "priority": rule["overlap_policy"]["priority"],
                    "suppression_mode": rule.get("overlap_policy", {})
                    .get("instance_suppression", {})
                    .get("mode", ""),
                    "raw_substruct_period_hits": raw["period_hits"],
                    "raw_substruct_source_hits": len(raw["source_ids"]),
                    "raw_substruct_match_total": raw["match_total"],
                    "raw_substruct_max_per_period": raw["max_per_period"],
                    "normalized_period_hits": normalized["period_hits"],
                    "normalized_source_hits": len(normalized["source_ids"]),
                    "normalized_match_total": normalized["match_total"],
                    "normalized_max_per_period": normalized["max_per_period"],
                    "resolved_period_hits": resolved["period_hits"],
                    "resolved_source_hits": len(resolved["source_ids"]),
                    "resolved_match_total": resolved["match_total"],
                    "resolved_max_per_period": resolved["max_per_period"],
                }
            )

    with args.ring_match_output.open("w", encoding="utf-8") as handle:
        for record in ring_match_records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    print(
        json.dumps(
            {
                "rdkit_version": rdBase.rdkitVersion,
                "period_rows": len(period_rows),
                "parser_failed": parser_failed,
                "rule_count": len(rules),
                "active_core_count": sum(1 for rule in rules if is_active_core(rule)),
                "output": str(args.output),
                "ring_match_output": str(args.ring_match_output),
                "ring_match_records": len(ring_match_records),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
