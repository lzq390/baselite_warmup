from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCAB = ROOT / "fragments_core_v1" / "core_fragment_v1.json"
DEFAULT_PERIODS = ROOT / "data" / "processed" / "periods2_from_unique_standardized_smiles.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "core_fragment_v1_resolved_stats.csv"
DEFAULT_RING_MATCH_OUTPUT = ROOT / "data" / "processed" / "core_fragment_v1_ring_matches.jsonl"

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
    "exclude_atom_role_adjacent_to_sulfonyl",
    "exclude_atom_role_with_oxygen_neighbor",
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


def atom_has_oxygen_neighbor(atom: Any) -> bool:
    return any(neighbor.GetAtomicNum() == 8 for neighbor in atom.GetNeighbors())


def is_sulfonyl_sulfur(atom: Any) -> bool:
    if atom.GetAtomicNum() != 16:
        return False
    double_oxygen_count = 0
    for bond in atom.GetBonds():
        other = bond.GetOtherAtom(atom)
        if other.GetAtomicNum() == 8 and bond.GetBondType() == Chem.BondType.DOUBLE:
            double_oxygen_count += 1
    return double_oxygen_count >= 2


def atom_is_adjacent_to_sulfonyl(atom: Any) -> bool:
    return any(is_sulfonyl_sulfur(neighbor) for neighbor in atom.GetNeighbors())


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


def atom_environment_label(atom: Any) -> str:
    if atom.GetAtomicNum() == 0:
        return "*"
    if atom.GetAtomicNum() == 6:
        return "C_aromatic" if atom.GetIsAromatic() else "C_aliphatic"
    return atom.GetSymbol()


def carbon_neighbor_environment(neighbors: list[Any], prefix: str) -> str:
    aromatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    aliphatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and not atom.GetIsAromatic())
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    if dummy_count >= 2:
        return f"boundary_{prefix}"
    if dummy_count == 1:
        if aromatic_count:
            return f"boundary_aryl_{prefix}"
        if aliphatic_count:
            return f"boundary_alkyl_{prefix}"
        return f"boundary_{prefix}"
    if aromatic_count == 2:
        return f"diaryl_{prefix}"
    if aromatic_count == 1:
        return f"aryl_alkyl_{prefix}"
    return f"dialkyl_{prefix}"


def neighbor_signature(atoms: list[Any]) -> str:
    return ",".join(sorted(atom_environment_label(atom) for atom in atoms)) if atoms else "none"


def bond_order_label(bond: Any | None) -> str:
    if bond is None:
        return "unknown"
    bond_type = bond.GetBondType()
    if bond_type == Chem.BondType.SINGLE:
        return "single"
    if bond_type == Chem.BondType.DOUBLE:
        return "double"
    if bond_type == Chem.BondType.TRIPLE:
        return "triple"
    if bond_type == Chem.BondType.AROMATIC:
        return "aromatic"
    return str(bond_type).lower()


def atom_class_label(atom: Any) -> str:
    atomic_num = atom.GetAtomicNum()
    if atomic_num == 0:
        return "boundary"
    if atomic_num == 6:
        return "aromatic_carbon" if atom.GetIsAromatic() else "aliphatic_carbon"
    if atomic_num == 7:
        return "nitrogen"
    if atomic_num == 8:
        return "oxygen"
    if atomic_num == 14:
        return "silicon"
    if atomic_num == 15:
        return "phosphorus"
    if atomic_num == 16:
        return "sulfur"
    if atomic_num in HALOGEN_ATOMIC_NUMS:
        return "halogen"
    return "other_heteroatom"


def role_atom(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
    role: str,
) -> Any:
    return mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, role))


def amine_degree_label(heavy_neighbor_count: int, hydrogen_count: int) -> str:
    if hydrogen_count >= 2 or heavy_neighbor_count <= 1:
        return "primary"
    if hydrogen_count == 1:
        return "secondary"
    return "tertiary"


def amine_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    nitrogen = role_atom(mol, match, role_to_query_index, "amine_nitrogen")
    heavy_neighbor_count = sum(1 for neighbor in nitrogen.GetNeighbors() if neighbor.GetAtomicNum() != 1)
    hydrogen_count = nitrogen.GetTotalNumHs()
    degree = amine_degree_label(heavy_neighbor_count, hydrogen_count)
    return {
        "amine_degree": degree,
        "amine_heavy_neighbor_count": heavy_neighbor_count,
        "amine_hydrogen_count": hydrogen_count,
        "amine_in_ring": nitrogen.IsInRing(),
        "amine_aromatic": nitrogen.GetIsAromatic(),
        "amine_environment": f"{degree}_{'ring' if nitrogen.IsInRing() else 'nonring'}",
    }


def carbonyl_neighbor_atoms(mol: Any, carbonyl_carbon: Any) -> list[Any]:
    neighbors = []
    for neighbor in carbonyl_carbon.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(carbonyl_carbon.GetIdx(), neighbor.GetIdx())
        if neighbor.GetAtomicNum() == 8 and bond.GetBondType() == Chem.BondType.DOUBLE:
            continue
        neighbors.append(neighbor)
    return neighbors


def carbonyl_environment_label(neighbor_atoms: list[Any], hydrogen_count: int) -> str:
    if hydrogen_count > 0:
        return "aldehyde_or_formyl"
    if any(atom.GetAtomicNum() == 0 for atom in neighbor_atoms):
        return "boundary_carbonyl"
    if any(atom.GetAtomicNum() not in {6, 0} for atom in neighbor_atoms):
        return "acyl_heteroatom_residual"
    if len(neighbor_atoms) == 2 and all(atom.GetAtomicNum() == 6 for atom in neighbor_atoms):
        return "ketone_like"
    return "other_residual"


def carbonyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    carbon = role_atom(mol, match, role_to_query_index, "carbonyl_carbon")
    neighbor_atoms = carbonyl_neighbor_atoms(mol, carbon)
    hydrogen_count = carbon.GetTotalNumHs()
    neighbor_labels = sorted(atom_environment_label(atom) for atom in neighbor_atoms)
    if hydrogen_count:
        neighbor_labels.extend(["H"] * hydrogen_count)
    return {
        "carbonyl_environment": carbonyl_environment_label(neighbor_atoms, hydrogen_count),
        "carbonyl_neighbor_signature": ",".join(sorted(neighbor_labels)) if neighbor_labels else "none",
        "carbonyl_hydrogen_count": hydrogen_count,
        "carbonyl_dummy_attachment_count": sum(1 for atom in neighbor_atoms if atom.GetAtomicNum() == 0),
    }


def alkenylene_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    carbon_1 = role_atom(mol, match, role_to_query_index, "alkene_carbon_1")
    carbon_2 = role_atom(mol, match, role_to_query_index, "alkene_carbon_2")
    alkene_atom_indices = {carbon_1.GetIdx(), carbon_2.GetIdx()}
    hydrogens = sorted([carbon_1.GetTotalNumHs(), carbon_2.GetTotalNumHs()])
    external_neighbors = []
    for carbon in (carbon_1, carbon_2):
        for neighbor in carbon.GetNeighbors():
            if neighbor.GetIdx() not in alkene_atom_indices:
                external_neighbors.append(neighbor)
    dummy_attachment_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 0)
    carbon_substituent_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() not in {0, 1})
    hydrogen_total = sum(hydrogens)
    if hydrogen_total >= 2:
        substitution_class = "vinylene"
    elif hydrogen_total == 1:
        substitution_class = "substituted_alkenylene"
    else:
        substitution_class = "fully_substituted_alkenylene"
    return {
        "alkene_h_pattern": f"H{hydrogens[0]}-H{hydrogens[1]}",
        "alkene_substitution_class": substitution_class,
        "alkene_external_neighbor_count": len(external_neighbors),
        "alkene_carbon_substituent_count": carbon_substituent_count,
        "alkene_dummy_attachment_count": dummy_attachment_count,
        "mainchain_through_alkene": "true" if dummy_attachment_count >= 2 else "unknown",
    }


def ether_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    oxygen = role_atom(mol, match, role_to_query_index, "ether_oxygen")
    neighbors = [neighbor for neighbor in oxygen.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    aromatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    aliphatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and not atom.GetIsAromatic())
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    return {
        "ether_environment": carbon_neighbor_environment(neighbors, "ether"),
        "ether_neighbor_signature": neighbor_signature(neighbors),
        "ether_aromatic_neighbor_count": aromatic_count,
        "ether_aliphatic_neighbor_count": aliphatic_count,
        "ether_dummy_attachment_count": dummy_count,
    }


def thioether_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    sulfur = role_atom(mol, match, role_to_query_index, "thioether_sulfur")
    neighbors = [neighbor for neighbor in sulfur.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    aromatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    aliphatic_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and not atom.GetIsAromatic())
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    return {
        "thioether_environment": carbon_neighbor_environment(neighbors, "thioether"),
        "thioether_neighbor_signature": neighbor_signature(neighbors),
        "thioether_aromatic_neighbor_count": aromatic_count,
        "thioether_aliphatic_neighbor_count": aliphatic_count,
        "thioether_dummy_attachment_count": dummy_count,
    }


def sulfinyl_environment_label(single_bond_neighbors: list[Any]) -> str:
    if any(atom.GetAtomicNum() == 0 for atom in single_bond_neighbors):
        return "boundary_sulfinyl"
    if len(single_bond_neighbors) == 2 and all(atom.GetAtomicNum() == 6 for atom in single_bond_neighbors):
        return "sulfoxide"
    return "other_sulfinyl"


def sulfinyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    sulfur = role_atom(mol, match, role_to_query_index, "sulfinyl_sulfur")
    single_bond_neighbors = []
    for neighbor in sulfur.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(sulfur.GetIdx(), neighbor.GetIdx())
        if bond.GetBondType() == Chem.BondType.DOUBLE and neighbor.GetAtomicNum() == 8:
            continue
        single_bond_neighbors.append(neighbor)
    carbon_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() == 6)
    boundary_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() == 0)
    hetero_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() not in {0, 6})
    return {
        "sulfinyl_environment": sulfinyl_environment_label(single_bond_neighbors),
        "sulfinyl_substituent_signature": neighbor_signature(single_bond_neighbors),
        "sulfinyl_carbon_attachment_count": carbon_attachment_count,
        "sulfinyl_hetero_attachment_count": hetero_attachment_count,
        "sulfinyl_boundary_attachment_count": boundary_attachment_count,
    }


def nitrile_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    carbon = role_atom(mol, match, role_to_query_index, "nitrile_carbon")
    parent_atoms = []
    for neighbor in carbon.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(carbon.GetIdx(), neighbor.GetIdx())
        if neighbor.GetAtomicNum() == 7 and bond.GetBondType() == Chem.BondType.TRIPLE:
            continue
        parent_atoms.append(neighbor)
    parent = parent_atoms[0] if parent_atoms else None
    if parent is None:
        environment = "terminal_nitrile_unknown"
        attached_class = "none"
        attached_symbol = "none"
        attached_aromatic = False
    elif parent.GetAtomicNum() == 0:
        environment = "boundary_nitrile"
        attached_class = "boundary"
        attached_symbol = "*"
        attached_aromatic = False
    elif parent.GetAtomicNum() == 6 and parent.GetIsAromatic():
        environment = "aromatic_nitrile"
        attached_class = "aromatic_carbon"
        attached_symbol = "C"
        attached_aromatic = True
    elif parent.GetAtomicNum() == 6:
        environment = "aliphatic_nitrile"
        attached_class = "aliphatic_carbon"
        attached_symbol = "C"
        attached_aromatic = False
    else:
        environment = "heteroatom_attached_nitrile"
        attached_class = "heteroatom"
        attached_symbol = parent.GetSymbol()
        attached_aromatic = parent.GetIsAromatic()
    return {
        "nitrile_environment": environment,
        "nitrile_attached_atom_symbol": attached_symbol,
        "nitrile_attached_atom_class": attached_class,
        "nitrile_attached_atom_aromatic": attached_aromatic,
    }


def hydroxyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    attached = role_atom(mol, match, role_to_query_index, "attached_atom")
    atomic_num = attached.GetAtomicNum()
    if atomic_num == 6 and attached.GetIsAromatic():
        environment = "phenolic_hydroxyl"
        attached_class = "aromatic_carbon"
    elif atomic_num == 6:
        environment = "aliphatic_alcohol"
        attached_class = "aliphatic_carbon"
    elif atomic_num == 16:
        environment = "sulfur_oxoacid_hydroxyl"
        attached_class = "sulfur"
    elif atomic_num == 15:
        environment = "phosphorus_oxoacid_hydroxyl"
        attached_class = "phosphorus"
    elif atomic_num == 7:
        environment = "nitrogen_hydroxyl"
        attached_class = "nitrogen"
    elif atomic_num == 14:
        environment = "silanol_like"
        attached_class = "silicon"
    else:
        environment = "other_heteroatom_hydroxyl"
        attached_class = "heteroatom" if atomic_num not in {0, 6} else "boundary"
    return {
        "hydroxyl_environment": environment,
        "hydroxyl_attached_atom_symbol": atom_environment_label(attached),
        "hydroxyl_attached_atom_class": attached_class,
        "hydroxyl_attached_atom_aromatic": attached.GetIsAromatic(),
        "hydroxyl_is_phenolic": environment == "phenolic_hydroxyl",
        "hydroxyl_is_alcohol": environment == "aliphatic_alcohol",
        "hydroxyl_is_heteroatom_bound": atomic_num not in {0, 6},
    }


def carboxylic_acid_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    connected = role_atom(mol, match, role_to_query_index, "connected_atom")
    if connected.GetAtomicNum() == 0:
        environment = "boundary_carboxylic_acid"
        connected_class = "boundary"
    elif connected.GetAtomicNum() == 6 and connected.GetIsAromatic():
        environment = "aromatic_carboxylic_acid"
        connected_class = "aromatic_carbon"
    elif connected.GetAtomicNum() == 6:
        environment = "aliphatic_carboxylic_acid"
        connected_class = "aliphatic_carbon"
    else:
        environment = "heteroatom_attached_carboxylic_acid"
        connected_class = "heteroatom"
    return {
        "carboxylic_acid_environment": environment,
        "carboxylic_acid_connected_atom_symbol": atom_environment_label(connected),
        "carboxylic_acid_connected_atom_class": connected_class,
        "carboxylic_acid_connected_atom_aromatic": connected.GetIsAromatic(),
    }


def alkynylene_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    carbon_1 = role_atom(mol, match, role_to_query_index, "alkyne_carbon_1")
    carbon_2 = role_atom(mol, match, role_to_query_index, "alkyne_carbon_2")
    alkyne_indices = {carbon_1.GetIdx(), carbon_2.GetIdx()}
    external_neighbors = []
    for carbon in (carbon_1, carbon_2):
        for neighbor in carbon.GetNeighbors():
            if neighbor.GetIdx() not in alkyne_indices:
                external_neighbors.append(neighbor)
    dummy_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 0)
    aromatic_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    if dummy_count >= 2:
        environment = "mainchain_ethynylene"
    elif aromatic_count == 2:
        environment = "diaryl_ethynylene"
    elif aromatic_count == 1:
        environment = "aryl_alkyl_ethynylene"
    else:
        environment = "alkynylene_other"
    return {
        "alkyne_environment": environment,
        "alkyne_terminal_signature": neighbor_signature(external_neighbors),
        "alkyne_dummy_attachment_count": dummy_count,
        "alkyne_aromatic_terminal_count": aromatic_count,
        "mainchain_through_alkyne": "true" if dummy_count >= 2 else "unknown",
    }


def secondary_amine_linker_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    nitrogen = role_atom(mol, match, role_to_query_index, "secondary_nitrogen")
    neighbors = [neighbor for neighbor in nitrogen.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    if dummy_count >= 2:
        environment = "boundary_secondary_amine_linker"
    elif nitrogen.IsInRing():
        environment = "ring_secondary_amine"
    else:
        environment = "secondary_amine_linker"
    return {
        "secondary_amine_linker_environment": environment,
        "secondary_amine_neighbor_signature": neighbor_signature(neighbors),
        "secondary_amine_in_ring": nitrogen.IsInRing(),
        "secondary_amine_dummy_attachment_count": dummy_count,
    }


def azo_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    nitrogen_1 = role_atom(mol, match, role_to_query_index, "azo_nitrogen_1")
    nitrogen_2 = role_atom(mol, match, role_to_query_index, "azo_nitrogen_2")
    azo_indices = {nitrogen_1.GetIdx(), nitrogen_2.GetIdx()}
    external_neighbors = []
    for nitrogen in (nitrogen_1, nitrogen_2):
        for neighbor in nitrogen.GetNeighbors():
            if neighbor.GetIdx() not in azo_indices:
                external_neighbors.append(neighbor)
    aromatic_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    dummy_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 0)
    if aromatic_count == 2:
        environment = "diaryl_azo"
    elif dummy_count:
        environment = "boundary_azo"
    else:
        environment = "non_diaryl_azo"
    return {
        "azo_environment": environment,
        "azo_neighbor_signature": neighbor_signature(external_neighbors),
        "azo_aromatic_neighbor_count": aromatic_count,
        "azo_dummy_attachment_count": dummy_count,
    }


def trifluoromethyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    connected = role_atom(mol, match, role_to_query_index, "connected_atom")
    trifluoromethyl_carbon = role_atom(mol, match, role_to_query_index, "trifluoromethyl_carbon")
    atomic_num = connected.GetAtomicNum()
    is_aromatic = atomic_num == 6 and connected.GetIsAromatic()
    if atomic_num == 0:
        attachment_class = "attached_to_boundary"
    elif is_aromatic:
        attachment_class = "attached_to_aromatic_carbon"
    elif atomic_num == 6:
        attachment_class = "attached_to_aliphatic_carbon"
    elif atomic_num == 8:
        attachment_class = "attached_to_oxygen"
    elif atomic_num == 7:
        attachment_class = "attached_to_nitrogen"
    elif atomic_num == 16:
        attachment_class = "attached_to_sulfur"
    else:
        attachment_class = "attached_to_other_heteroatom"
    is_perfluoroalkyl_terminal = (
        atomic_num == 6
        and any(neighbor.GetAtomicNum() == 9 for neighbor in connected.GetNeighbors())
    )
    return {
        "trifluoromethyl_attachment_class": attachment_class,
        "trifluoromethyl_attachment_atom_symbol": atom_environment_label(connected),
        "trifluoromethyl_neighbor_signature": neighbor_signature([connected, trifluoromethyl_carbon]),
        "trifluoromethyl_is_aromatic_substituent": is_aromatic,
        "trifluoromethyl_is_perfluoroalkyl_terminal": is_perfluoroalkyl_terminal,
    }


def thiocarbonyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    carbon = role_atom(mol, match, role_to_query_index, "thiocarbonyl_carbon")
    sulfur = role_atom(mol, match, role_to_query_index, "thiocarbonyl_sulfur")
    external_neighbors = [neighbor for neighbor in carbon.GetNeighbors() if neighbor.GetIdx() != sulfur.GetIdx()]
    nitrogen_single_count = 0
    nitrogen_double_count = 0
    for neighbor in external_neighbors:
        bond = mol.GetBondBetweenAtoms(carbon.GetIdx(), neighbor.GetIdx())
        if neighbor.GetAtomicNum() == 7 and bond is not None:
            if bond.GetBondType() == Chem.BondType.DOUBLE:
                nitrogen_double_count += 1
            elif bond.GetBondType() == Chem.BondType.SINGLE:
                nitrogen_single_count += 1
    carbon_neighbor_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 6)
    aromatic_carbon_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    dummy_count = sum(1 for atom in external_neighbors if atom.GetAtomicNum() == 0)
    is_isothiocyanate_like = nitrogen_double_count > 0
    is_thiourea_like = nitrogen_single_count >= 2
    is_thioamide_like = nitrogen_single_count >= 1
    if is_isothiocyanate_like:
        environment = "isothiocyanate_like"
    elif is_thiourea_like:
        environment = "thiourea_like"
    elif is_thioamide_like:
        environment = "thioamide_like"
    elif dummy_count:
        environment = "boundary_thiocarbonyl"
    elif aromatic_carbon_count:
        environment = "aryl_thiocarbonyl"
    elif carbon_neighbor_count:
        environment = "aliphatic_thiocarbonyl"
    else:
        environment = "other_thiocarbonyl"
    connected_classes = sorted({atom_class_label(atom) for atom in external_neighbors})
    connected_class = connected_classes[0] if len(connected_classes) == 1 else ("mixed" if connected_classes else "none")
    return {
        "thiocarbonyl_environment": environment,
        "thiocarbonyl_neighbor_signature": neighbor_signature(external_neighbors),
        "thiocarbonyl_connected_atom_class": connected_class,
        "thiocarbonyl_is_thioamide_like": is_thioamide_like,
        "thiocarbonyl_is_thiourea_like": is_thiourea_like,
        "thiocarbonyl_is_isothiocyanate_like": is_isothiocyanate_like,
        "thiocarbonyl_dummy_attachment_count": dummy_count,
    }


def nitrogen_class_label(nitrogen: Any) -> str:
    if nitrogen.GetFormalCharge() > 0:
        return "cationic_nitrogen"
    if nitrogen.GetIsAromatic():
        return "aromatic_nitrogen"
    for neighbor in nitrogen.GetNeighbors():
        bond = nitrogen.GetOwningMol().GetBondBetweenAtoms(nitrogen.GetIdx(), neighbor.GetIdx())
        if neighbor.GetAtomicNum() == 6 and bond is not None and bond.GetBondType() == Chem.BondType.DOUBLE:
            return "imine_nitrogen"
    return "neutral_nitrogen"


def oxygen_class_label_for_n_o(oxygen: Any, nitrogen_idx: int) -> str:
    if oxygen.GetFormalCharge() < 0:
        return "anionic_oxygen"
    if oxygen.GetTotalNumHs() > 0:
        return "hydroxyl_oxygen"
    for neighbor in oxygen.GetNeighbors():
        if neighbor.GetIdx() == nitrogen_idx:
            continue
        if neighbor.GetAtomicNum() == 6:
            return "alkoxy_oxygen"
    return "neutral_oxygen"


def nitrogen_oxygen_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    nitrogen = role_atom(mol, match, role_to_query_index, "nitrogen_atom")
    oxygen = role_atom(mol, match, role_to_query_index, "oxygen_atom")
    bond = mol.GetBondBetweenAtoms(nitrogen.GetIdx(), oxygen.GetIdx())
    oxygen_neighbors = []
    has_double_oxygen = False
    for neighbor in nitrogen.GetNeighbors():
        if neighbor.GetAtomicNum() != 8:
            continue
        oxygen_neighbors.append(neighbor)
        neighbor_bond = mol.GetBondBetweenAtoms(nitrogen.GetIdx(), neighbor.GetIdx())
        if neighbor_bond is not None and neighbor_bond.GetBondType() == Chem.BondType.DOUBLE:
            has_double_oxygen = True
    has_double_carbon = False
    for neighbor in nitrogen.GetNeighbors():
        neighbor_bond = mol.GetBondBetweenAtoms(nitrogen.GetIdx(), neighbor.GetIdx())
        if neighbor.GetAtomicNum() == 6 and neighbor_bond is not None and neighbor_bond.GetBondType() == Chem.BondType.DOUBLE:
            has_double_carbon = True
    is_single_no = bond is not None and bond.GetBondType() == Chem.BondType.SINGLE
    is_nitro_like = nitrogen.GetFormalCharge() > 0 and len(oxygen_neighbors) >= 2 and has_double_oxygen
    is_oxime_like = is_single_no and has_double_carbon
    is_hydroxylamine_like = is_single_no and oxygen.GetTotalNumHs() > 0
    is_alkoxyamine_like = is_single_no and any(
        neighbor.GetIdx() != nitrogen.GetIdx() and neighbor.GetAtomicNum() == 6
        for neighbor in oxygen.GetNeighbors()
    )
    if is_nitro_like:
        environment = "nitro_like"
    elif is_oxime_like:
        environment = "oxime_like"
    elif is_hydroxylamine_like:
        environment = "hydroxylamine_like"
    elif is_alkoxyamine_like:
        environment = "alkoxyamine_like"
    elif nitrogen.GetIsAromatic():
        environment = "aromatic_n_o"
    else:
        environment = "other_n_o"
    return {
        "n_o_environment": environment,
        "n_o_bond_order": bond_order_label(bond),
        "n_o_nitrogen_class": nitrogen_class_label(nitrogen),
        "n_o_oxygen_class": oxygen_class_label_for_n_o(oxygen, nitrogen.GetIdx()),
        "n_o_is_nitro_like": is_nitro_like,
        "n_o_is_oxime_like": is_oxime_like,
        "n_o_is_hydroxylamine_like": is_hydroxylamine_like,
        "n_o_is_alkoxyamine_like": is_alkoxyamine_like,
    }


def sulfanyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    attached = role_atom(mol, match, role_to_query_index, "attached_atom")
    sulfur = role_atom(mol, match, role_to_query_index, "sulfanyl_sulfur")
    neighbors = [neighbor for neighbor in sulfur.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    is_aromatic = attached.GetAtomicNum() == 6 and attached.GetIsAromatic()
    is_aliphatic = attached.GetAtomicNum() == 6 and not attached.GetIsAromatic()
    if attached.GetAtomicNum() == 0:
        environment = "boundary_sulfanyl"
    elif is_aromatic:
        environment = "aromatic_sulfanyl"
    elif is_aliphatic:
        environment = "aliphatic_sulfanyl"
    else:
        environment = "heteroatom_sulfanyl"
    return {
        "sulfanyl_environment": environment,
        "sulfanyl_attached_atom_class": atom_class_label(attached),
        "sulfanyl_neighbor_signature": neighbor_signature(neighbors),
        "sulfanyl_is_aromatic": is_aromatic,
        "sulfanyl_is_aliphatic": is_aliphatic,
        "sulfanyl_dummy_attachment_count": dummy_count,
    }


def silicon_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    silicon = role_atom(mol, match, role_to_query_index, "silicon_atom")
    neighbors = [neighbor for neighbor in silicon.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    carbon_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6)
    oxygen_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 8)
    halogen_count = sum(1 for atom in neighbors if atom.GetAtomicNum() in HALOGEN_ATOMIC_NUMS)
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    aromatic_carbon_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and atom.GetIsAromatic())
    aliphatic_carbon_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6 and not atom.GetIsAromatic())
    is_siloxane_like = False
    for oxygen in [atom for atom in neighbors if atom.GetAtomicNum() == 8]:
        if any(neighbor.GetAtomicNum() == 14 and neighbor.GetIdx() != silicon.GetIdx() for neighbor in oxygen.GetNeighbors()):
            is_siloxane_like = True
            break
    if dummy_count:
        environment = "boundary_silicon"
    elif is_siloxane_like:
        environment = "siloxane_like"
    elif halogen_count:
        environment = "halosilane_like"
    elif oxygen_count:
        environment = "siloxy_silicon"
    elif aromatic_carbon_count:
        environment = "aryl_silyl"
    elif aliphatic_carbon_count:
        environment = "alkyl_silyl"
    else:
        environment = "other_silicon"
    return {
        "silicon_environment": environment,
        "silicon_neighbor_signature": neighbor_signature(neighbors),
        "silicon_carbon_attachment_count": carbon_count,
        "silicon_oxygen_attachment_count": oxygen_count,
        "silicon_halogen_attachment_count": halogen_count,
        "silicon_dummy_attachment_count": dummy_count,
        "silicon_is_siloxane_like": is_siloxane_like,
        "silicon_is_silyl_aryl_like": aromatic_carbon_count > 0,
        "silicon_is_silyl_alkyl_like": aliphatic_carbon_count > 0,
    }


def phosphorus_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    phosphorus = role_atom(mol, match, role_to_query_index, "phosphorus_atom")
    neighbors = [neighbor for neighbor in phosphorus.GetNeighbors() if neighbor.GetAtomicNum() != 1]
    oxygen_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 8)
    nitrogen_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 7)
    carbon_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 6)
    halogen_count = sum(1 for atom in neighbors if atom.GetAtomicNum() in HALOGEN_ATOMIC_NUMS)
    dummy_count = sum(1 for atom in neighbors if atom.GetAtomicNum() == 0)
    has_phosphoryl = False
    has_thiophosphoryl = False
    is_phosphazene_like = False
    for neighbor in neighbors:
        bond = mol.GetBondBetweenAtoms(phosphorus.GetIdx(), neighbor.GetIdx())
        if bond is None or bond.GetBondType() != Chem.BondType.DOUBLE:
            continue
        if neighbor.GetAtomicNum() == 8:
            has_phosphoryl = True
        elif neighbor.GetAtomicNum() == 16:
            has_thiophosphoryl = True
        elif neighbor.GetAtomicNum() == 7:
            is_phosphazene_like = True
    is_phosphate_like = has_phosphoryl and oxygen_count >= 3
    if is_phosphazene_like:
        environment = "phosphazene_like"
    elif is_phosphate_like:
        environment = "phosphate_like"
    elif has_phosphoryl:
        environment = "phosphoryl_like"
    elif has_thiophosphoryl:
        environment = "thiophosphoryl_like"
    elif dummy_count:
        environment = "boundary_phosphorus"
    elif carbon_count:
        environment = "organophosphorus"
    else:
        environment = "other_phosphorus"
    return {
        "phosphorus_environment": environment,
        "phosphorus_neighbor_signature": neighbor_signature(neighbors),
        "phosphorus_oxygen_attachment_count": oxygen_count,
        "phosphorus_nitrogen_attachment_count": nitrogen_count,
        "phosphorus_carbon_attachment_count": carbon_count,
        "phosphorus_halogen_attachment_count": halogen_count,
        "phosphorus_dummy_attachment_count": dummy_count,
        "phosphorus_has_phosphoryl": has_phosphoryl,
        "phosphorus_is_phosphate_like": is_phosphate_like,
        "phosphorus_is_phosphazene_like": is_phosphazene_like,
    }


def sulfonyl_environment_label(single_bond_neighbors: list[Any]) -> str:
    atomic_nums = {atom.GetAtomicNum() for atom in single_bond_neighbors}
    if len(single_bond_neighbors) == 2 and atomic_nums == {6}:
        return "sulfone"
    if 8 in atomic_nums:
        return "sulfonate_like"
    if 7 in atomic_nums:
        return "sulfonamide_like"
    if atomic_nums & {9, 17, 35, 53}:
        return "sulfonyl_halide_like"
    if 0 in atomic_nums:
        return "boundary_sulfonyl"
    return "other_sulfonyl"


def sulfonyl_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    sulfur = role_atom(mol, match, role_to_query_index, "sulfonyl_sulfur")
    single_bond_neighbors = []
    for neighbor in sulfur.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(sulfur.GetIdx(), neighbor.GetIdx())
        if bond.GetBondType() == Chem.BondType.DOUBLE and neighbor.GetAtomicNum() == 8:
            continue
        single_bond_neighbors.append(neighbor)

    labels = sorted(atom_environment_label(atom) for atom in single_bond_neighbors)
    carbon_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() == 6)
    boundary_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() == 0)
    hetero_attachment_count = sum(1 for atom in single_bond_neighbors if atom.GetAtomicNum() not in {0, 6})
    return {
        "sulfonyl_environment": sulfonyl_environment_label(single_bond_neighbors),
        "sulfonyl_substituent_signature": ",".join(labels) if labels else "none",
        "sulfonyl_carbon_attachment_count": carbon_attachment_count,
        "sulfonyl_hetero_attachment_count": hetero_attachment_count,
        "sulfonyl_boundary_attachment_count": boundary_attachment_count,
        "sulfonyl_is_sulfone": len(single_bond_neighbors) == 2 and carbon_attachment_count == 2,
    }


HALOGEN_ATOMIC_NUMS = {9, 17, 35, 53}


def halogen_match_attributes(
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int],
) -> dict[str, Any]:
    substituted_carbon = role_atom(mol, match, role_to_query_index, "substituted_carbon")
    halogen = role_atom(mol, match, role_to_query_index, "halogen_atom")
    element = halogen.GetSymbol()
    carbon_class = "aromatic_carbon" if substituted_carbon.GetIsAromatic() else "aliphatic_carbon"
    halogen_count = sum(
        1 for neighbor in substituted_carbon.GetNeighbors() if neighbor.GetAtomicNum() in HALOGEN_ATOMIC_NUMS
    )
    fluorine_count = sum(1 for neighbor in substituted_carbon.GetNeighbors() if neighbor.GetAtomicNum() == 9)
    is_fluorine = element == "F"
    is_aromatic_substituent = substituted_carbon.GetIsAromatic()
    return {
        "halogen_element": element,
        "halogen_environment": f"{element}_on_{carbon_class}",
        "halogen_substituted_carbon_class": carbon_class,
        "halogenated_carbon_halogen_count": halogen_count,
        "halogenated_carbon_fluorine_count": fluorine_count,
        "halogen_is_fluorine": is_fluorine,
        "halogen_is_aromatic_substituent": is_aromatic_substituent,
        "halogen_is_perfluoroalkyl_like": is_fluorine and not is_aromatic_substituent and halogen_count >= 2,
    }


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


def match_attributes(
    rule: dict[str, Any],
    mol: Any,
    match: tuple[int, ...],
    role_to_query_index: dict[str, int] | None = None,
) -> dict[str, Any]:
    if rule.get("match_rule", {}).get("type", "smarts") == "rdkit_ring":
        return ring_match_attributes(rule, mol, match)
    if role_to_query_index is None:
        return {}
    fragment_id = rule["fragment_id"]
    if fragment_id == "fragment_004":
        return ether_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_008":
        return thioether_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_009":
        return sulfonyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_010":
        return sulfinyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_011":
        return nitrile_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_012":
        return hydroxyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_013":
        return amine_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_014":
        return carbonyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_015":
        return carboxylic_acid_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_021":
        return alkenylene_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_022":
        return alkynylene_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_023":
        return secondary_amine_linker_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_024":
        return azo_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_025":
        return halogen_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_026":
        return trifluoromethyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_027":
        return thiocarbonyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_028":
        return nitrogen_oxygen_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_029":
        return sulfanyl_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_030":
        return silicon_match_attributes(mol, match, role_to_query_index)
    if fragment_id == "fragment_031":
        return phosphorus_match_attributes(mol, match, role_to_query_index)
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

    sulfonyl_adjacent_roles = constraints.get("exclude_atom_role_adjacent_to_sulfonyl", [])
    if isinstance(sulfonyl_adjacent_roles, str):
        sulfonyl_adjacent_roles = [sulfonyl_adjacent_roles]
    for role in sulfonyl_adjacent_roles:
        atom = mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, role))
        if atom_is_adjacent_to_sulfonyl(atom):
            return False

    oxygen_neighbor_roles = constraints.get("exclude_atom_role_with_oxygen_neighbor", [])
    if isinstance(oxygen_neighbor_roles, str):
        oxygen_neighbor_roles = [oxygen_neighbor_roles]
    for role in oxygen_neighbor_roles:
        atom = mol.GetAtomWithIdx(atom_for_role(match, role_to_query_index, role))
        if atom_has_oxygen_neighbor(atom):
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
    parser = argparse.ArgumentParser(description="Compute raw and resolved stats for core_fragment_v1.")
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
