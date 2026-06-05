from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdkit import Chem, RDLogger, rdBase

from compute_base_fragment_new2_resolved_stats import (
    ACTIVE_CORE_STATUS,
    apply_instance_suppression,
    get_raw_matches,
    is_active_core,
    match_attributes,
    normalize_matches,
    query_map,
    validate_rule,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCAB = ROOT / "fragments_1" / "base_fragment_new2.json"
DEFAULT_CANONICAL = ROOT / "data" / "processed" / "unique_standardized_smiles.csv"
DEFAULT_PERIOD_STATS = ROOT / "data" / "processed" / "base_fragment_new2_resolved_stats.csv"
DEFAULT_PERIODS = ROOT / "data" / "processed" / "periods2_from_unique_standardized_smiles.csv"
DEFAULT_V1_VOCAB = ROOT / "fragments" / "vocab" / "fragment_vocab_v1.0.json"
DEFAULT_V1_STATS = ROOT / "fragments" / "vocab" / "fragment_vocab_v1.0.stats.json"
DEFAULT_V1_BUILD = ROOT / "fragments" / "fragment_vocab_v1.0.build_summary.json"
DEFAULT_V1_OVERLAP = ROOT / "fragments" / "validation" / "overlap_report.json"
DEFAULT_OUTPUT = ROOT / "docs" / "base_fragment_new2_core_audit_report.html"

RDLogger.DisableLog("rdApp.*")

V1_REFERENCES = {
    "fragment_001": ["FG_AMIDE", "COMP_AROMATIC_AMIDE_N", "COMP_AROMATIC_AMIDE_C"],
    "fragment_002": ["FG_IMIDE", "RING_IMIDE", "COMP_AROMATIC_IMIDE"],
    "fragment_003": ["FG_ESTER"],
    "fragment_004": ["FG_ETHER", "FG_AROMATIC_ETHER", "SUB_ALKOXY"],
    "fragment_005": ["FG_CARBONATE"],
    "fragment_006": ["FG_URETHANE"],
    "fragment_007": ["FG_UREA"],
    "fragment_008": ["FG_THIOETHER", "LINK_AROMATIC_SULFIDE"],
    "fragment_009": ["FG_SULFONE", "LINK_AROMATIC_SULFONE"],
    "fragment_010": [],
    "fragment_011": ["FG_NITRILE"],
    "fragment_012": ["FG_HYDROXYL"],
    "fragment_013": ["FG_SECONDARY_AMINE", "FG_TERTIARY_AMINE"],
    "fragment_014": ["FG_CARBONYL", "FG_KETONE", "LINK_AROMATIC_CARBONYL"],
    "fragment_015": ["FG_CARBOXYLIC_ACID"],
    "fragment_016": [],
    "fragment_017": ["RING_HETEROAROMATIC_5"],
    "fragment_018": [],
    "fragment_019": ["RING_AROMATIC_6", "RING_HETEROAROMATIC_6", "RING_FUSED_AROMATIC_ATOM"],
    "fragment_020": [],
    "fragment_021": ["LINK_VINYLENE"],
    "fragment_022": ["LINK_ETHYNYLENE"],
    "fragment_023": ["FG_SECONDARY_AMINE"],
    "fragment_024": ["FG_AZO"],
    "fragment_025": ["SUB_HALOGEN", "SUB_FLUORO", "SUB_CHLORO", "SUB_BROMO"],
    "fragment_026": ["SUB_TRIFLUOROMETHYL", "COMP_PERFLUOROALKYL"],
    "fragment_027": ["SUB_METHYL"],
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float | int | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def stat_bucket() -> dict[str, Any]:
    return {"record_hits": 0, "ids": set(), "match_total": 0, "max_per_record": 0}


def update_stat(bucket: dict[str, Any], record_id: str, match_count: int) -> None:
    if match_count <= 0:
        return
    bucket["record_hits"] += 1
    bucket["ids"].add(record_id)
    bucket["match_total"] += match_count
    bucket["max_per_record"] = max(bucket["max_per_record"], match_count)


def read_canonical_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def count_period_scope(path: Path) -> dict[str, int]:
    source_ids: set[str] = set()
    row_count = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            source_ids.add(row.get("source_canonical_id", ""))
    return {"period_rows": row_count, "period_source_ids": len(source_ids)}


def compute_canonical_audit(
    rules: list[dict[str, Any]],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    queries: dict[str, Any] = {}
    role_index_by_fragment: dict[str, dict[str, int]] = {}
    for rule in rules:
        validate_rule(rule)
        query, role_index = query_map(rule)
        queries[rule["fragment_id"]] = query
        role_index_by_fragment[rule["fragment_id"]] = role_index

    raw_stats = {rule["fragment_id"]: stat_bucket() for rule in rules}
    normalized_stats = {rule["fragment_id"]: stat_bucket() for rule in rules}
    resolved_stats = {rule["fragment_id"]: stat_bucket() for rule in rules}
    resolved_id_sets = {rule["fragment_id"]: set() for rule in rules}
    parser_failed = 0
    active_type_counts: list[int] = []
    unmatched_records: list[dict[str, str]] = []
    unmatched_nonactive_hits: Counter[str] = Counter()
    ring_attribute_records: list[dict[str, Any]] = []

    for row in rows:
        record_id = row["canonical_id"]
        mol = Chem.MolFromSmiles(row["standardized_smiles"])
        if mol is None:
            parser_failed += 1
            continue

        raw_matches_by_fragment = {
            rule["fragment_id"]: get_raw_matches(rule, mol, queries[rule["fragment_id"]])
            for rule in rules
        }
        normalized_matches_by_fragment = {
            rule["fragment_id"]: normalize_matches(
                rule=rule,
                mol=mol,
                raw_matches=raw_matches_by_fragment[rule["fragment_id"]],
                role_to_query_index=role_index_by_fragment[rule["fragment_id"]],
            )
            for rule in rules
        }

        active_hit_count = 0
        for rule in rules:
            fragment_id = rule["fragment_id"]
            raw_matches = raw_matches_by_fragment[fragment_id]
            normalized_matches = normalized_matches_by_fragment[fragment_id]
            update_stat(raw_stats[fragment_id], record_id, len(raw_matches))
            update_stat(normalized_stats[fragment_id], record_id, len(normalized_matches))
            if rule.get("match_rule", {}).get("type") == "rdkit_ring":
                for match in normalized_matches:
                    ring_attribute_records.append(
                        {
                            "record_id": record_id,
                            "fragment_id": fragment_id,
                            "attributes": match_attributes(rule, mol, match),
                        }
                    )

            resolved_matches = apply_instance_suppression(
                fragment_id=fragment_id,
                rule=rule,
                matches_by_fragment=normalized_matches_by_fragment,
                role_index_by_fragment=role_index_by_fragment,
            )
            if is_active_core(rule):
                resolved_count = len(resolved_matches)
                update_stat(resolved_stats[fragment_id], record_id, resolved_count)
                if resolved_count:
                    active_hit_count += 1
                    resolved_id_sets[fragment_id].add(record_id)

        active_type_counts.append(active_hit_count)
        if active_hit_count == 0:
            nonactive_hits = [
                rule["fragment_id"]
                for rule in rules
                if not is_active_core(rule) and normalized_matches_by_fragment[rule["fragment_id"]]
            ]
            unmatched_nonactive_hits.update(nonactive_hits)
            enriched_row = dict(row)
            enriched_row["_nonactive_hits"] = ", ".join(nonactive_hits)
            unmatched_records.append(enriched_row)

    return {
        "raw": raw_stats,
        "normalized": normalized_stats,
        "resolved": resolved_stats,
        "resolved_id_sets": resolved_id_sets,
        "parser_failed": parser_failed,
        "active_type_counts": active_type_counts,
        "unmatched_records": unmatched_records,
        "unmatched_nonactive_hits": unmatched_nonactive_hits,
        "ring_attribute_records": ring_attribute_records,
    }


def summarize_distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"avg": 0, "median": 0, "max": 0, "histogram": {}}
    return {
        "avg": sum(values) / len(values),
        "median": statistics.median(values),
        "max": max(values),
        "histogram": dict(sorted(Counter(values).items())),
    }


def attribute_distribution(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    ring_counts: Counter[str] = Counter()
    record_ids: dict[str, set[str]] = {}
    for record in records:
        value = record["attributes"].get(key)
        if isinstance(value, bool):
            label = "true" if value else "false"
        elif isinstance(value, list):
            label = ",".join(value) if value else "none"
        else:
            label = str(value)
        ring_counts[label] += 1
        record_ids.setdefault(label, set()).add(record["record_id"])
    return [
        {"label": label, "records": len(record_ids[label]), "rings": ring_count}
        for label, ring_count in ring_counts.most_common()
    ]


def summarize_ring_attributes(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len({record["record_id"] for record in records}),
        "ring_count": len(records),
        "ring_atom_class": attribute_distribution(records, "ring_atom_class"),
        "hetero_atom_signature": attribute_distribution(records, "hetero_atom_signature"),
        "aromaticity": attribute_distribution(records, "aromaticity"),
        "ring_aromatic_atom_count": attribute_distribution(records, "ring_aromatic_atom_count"),
        "ring_aromaticity_class": attribute_distribution(records, "ring_aromaticity_class"),
        "polycyclic": attribute_distribution(records, "polycyclic"),
        "external_connection_count": attribute_distribution(records, "external_connection_count"),
        "external_connection_topology": attribute_distribution(records, "external_connection_topology"),
        "exocyclic_substituent_count": attribute_distribution(records, "exocyclic_substituent_count"),
        "exocyclic_substituent_topology": attribute_distribution(records, "exocyclic_substituent_topology"),
        "polycyclic_connection_count": attribute_distribution(records, "polycyclic_connection_count"),
        "polycyclic_connection_topology": attribute_distribution(records, "polycyclic_connection_topology"),
        "substitution_count": attribute_distribution(records, "substitution_count"),
        "substitution_topology": attribute_distribution(records, "substitution_topology"),
        "attachment_count": attribute_distribution(records, "attachment_count"),
        "mainchain_through_ring": attribute_distribution(records, "mainchain_through_ring"),
    }


def ring_records_for_fragment(records: list[dict[str, Any]], fragment_id: str) -> list[dict[str, Any]]:
    return [record for record in records if record["fragment_id"] == fragment_id]


def overlap_pairs(
    rules: list[dict[str, Any]],
    id_sets: dict[str, set[str]],
    *,
    min_jaccard: float = 0.45,
    min_containment: float = 0.9,
) -> list[dict[str, Any]]:
    active_rules = [rule for rule in rules if is_active_core(rule)]
    pairs: list[dict[str, Any]] = []
    for idx, left in enumerate(active_rules):
        left_id = left["fragment_id"]
        left_set = id_sets[left_id]
        if not left_set:
            continue
        for right in active_rules[idx + 1 :]:
            right_id = right["fragment_id"]
            right_set = id_sets[right_id]
            if not right_set:
                continue
            shared = len(left_set & right_set)
            if not shared:
                continue
            union = len(left_set | right_set)
            jaccard = shared / union
            containment_left = shared / len(left_set)
            containment_right = shared / len(right_set)
            if jaccard >= min_jaccard or max(containment_left, containment_right) >= min_containment:
                pairs.append(
                    {
                        "a": left_id,
                        "b": right_id,
                        "a_name": left["fragment_name"],
                        "b_name": right["fragment_name"],
                        "jaccard": jaccard,
                        "containment_a": containment_left,
                        "containment_b": containment_right,
                        "shared": shared,
                    }
                )
    return sorted(pairs, key=lambda row: (row["jaccard"], row["shared"]), reverse=True)


def read_period_stats(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["fragment_id"]: row for row in csv.DictReader(handle)}


def load_json_or_empty(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def status_badge(status: str) -> str:
    cls = {
        "core": "ok",
        "derived_attribute": "info",
        "deprecated_alias": "muted",
        "rejected": "warn",
    }.get(status, "muted")
    return f'<span class="badge {cls}">{esc(status)}</span>'


def risk_badge(level: str) -> str:
    cls = {"关注": "warn", "观察": "info", "通过": "ok"}.get(level, "muted")
    return f'<span class="badge {cls}">{esc(level)}</span>'


def build_rule_rows(
    rules: list[dict[str, Any]],
    canonical_audit: dict[str, Any],
    period_stats: dict[str, dict[str, str]],
    denominator: int,
    v1_stats: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in rules:
        fragment_id = rule["fragment_id"]
        raw = canonical_audit["raw"][fragment_id]
        normalized = canonical_audit["normalized"][fragment_id]
        resolved = canonical_audit["resolved"][fragment_id]
        period = period_stats.get(fragment_id, {})
        status = rule.get("core_status", ACTIVE_CORE_STATUS)
        resolved_records = resolved["record_hits"]
        resolved_ratio = resolved_records / denominator if denominator else 0
        normalized_records = normalized["record_hits"]
        normalized_total = normalized["match_total"]
        resolved_total = resolved["match_total"]
        suppression_drop = normalized_total - resolved_total if is_active_core(rule) else normalized_total
        suppression_drop_ratio = suppression_drop / normalized_total if normalized_total else 0
        raw_drop_ratio = (raw["match_total"] - normalized_total) / raw["match_total"] if raw["match_total"] else 0

        notes: list[str] = []
        risk = "通过"
        if is_active_core(rule) and resolved_records == 0:
            risk = "关注"
            notes.append("active core 零命中")
        if is_active_core(rule) and 0 < resolved_ratio < 0.005:
            risk = "观察"
            notes.append("低频 core，建议保留但单独标注 rare")
        if is_active_core(rule) and resolved_ratio >= 0.5:
            risk = "观察"
            notes.append("高覆盖泛化规则，适合作 roll-up 或父级特征")
        if raw_drop_ratio >= 0.2:
            notes.append("raw->normalized 下降明显，dedup/constraints 生效")
        if is_active_core(rule) and suppression_drop_ratio >= 0.2:
            notes.append("resolved suppression 生效")
        if not is_active_core(rule) and normalized_total > 0:
            notes.append("非 active，仅保留审计命中，不进入 resolved 输出")
        if status in {"deprecated_alias", "rejected"}:
            notes.append(f"{status} 不应下游输出")
        if not notes:
            notes.append("当前口径无明显异常")

        v1_refs = []
        for ref_id in V1_REFERENCES.get(fragment_id, []):
            if ref_id in v1_stats:
                ref = v1_stats[ref_id]
                v1_refs.append(
                    f"{ref_id} {ref.get('polymer_coverage_count', 0):,}/{pct(ref.get('polymer_coverage_ratio', 0), 1)}"
                )
            else:
                v1_refs.append(f"{ref_id} -")

        rows.append(
            {
                "fragment_id": fragment_id,
                "name": rule["fragment_name"],
                "category": rule["category"],
                "status": status,
                "active": is_active_core(rule),
                "priority": rule.get("overlap_policy", {}).get("priority", ""),
                "raw_records": raw["record_hits"],
                "raw_total": raw["match_total"],
                "normalized_records": normalized_records,
                "normalized_total": normalized_total,
                "resolved_records": resolved_records,
                "resolved_ratio": resolved_ratio,
                "resolved_total": resolved_total,
                "resolved_max": resolved["max_per_record"],
                "period_resolved_source_hits": int(period.get("resolved_source_hits", 0) or 0),
                "period_resolved_period_hits": int(period.get("resolved_period_hits", 0) or 0),
                "period_resolved_total": int(period.get("resolved_match_total", 0) or 0),
                "raw_drop_ratio": raw_drop_ratio,
                "suppression_drop_ratio": suppression_drop_ratio,
                "risk": risk,
                "notes": notes,
                "v1_refs": v1_refs,
            }
        )
    return rows


def render_cards(cards: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"""
        <section class="card">
          <div class="label">{esc(label)}</div>
          <div class="metric">{esc(value)}</div>
          <p>{esc(note)}</p>
        </section>
        """
        for label, value, note in cards
    )


def render_histogram(histogram: dict[int, int], total: int) -> str:
    bars = []
    max_count = max(histogram.values()) if histogram else 1
    for key, count in histogram.items():
        width = count / max_count * 100
        bars.append(
            f"""
            <div class="hist-row">
              <span class="hist-key">{esc(key)}</span>
              <span class="hist-bar"><span style="width:{width:.1f}%"></span></span>
              <span class="hist-value">{fmt_int(count)} ({pct(count / total if total else 0, 1)})</span>
            </div>
            """
        )
    return "\n".join(bars)


def render_attribute_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class=\"subtle\">无四元环属性命中。</p>"
    body = []
    for row in rows:
        body.append(
            f"""
            <tr>
              <td>{esc(row['label'])}</td>
              <td class="num">{fmt_int(row['records'])}</td>
              <td class="num">{fmt_int(row['rings'])}</td>
            </tr>
            """
        )
    return f"""
    <table class="compact-table">
      <thead>
        <tr>
          <th>value</th>
          <th>records</th>
          <th>rings</th>
        </tr>
      </thead>
      <tbody>{''.join(body)}</tbody>
    </table>
    """


def render_rule_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            f"""
            <tr>
              <td><code>{esc(row['fragment_id'])}</code><br><span class="subtle">{esc(row['name'])}</span></td>
              <td>{status_badge(row['status'])}</td>
              <td>{esc(row['category'])}</td>
              <td class="num">{fmt_int(row['resolved_records'])}</td>
              <td class="num">{pct(row['resolved_ratio'], 2)}</td>
              <td class="num">{fmt_int(row['resolved_total'])}</td>
              <td class="num">{fmt_int(row['resolved_max'])}</td>
              <td class="num">{fmt_int(row['period_resolved_source_hits'])}</td>
              <td>{risk_badge(row['risk'])}</td>
              <td>{esc('; '.join(row['notes']))}</td>
              <td class="refs">{esc('; '.join(row['v1_refs']) if row['v1_refs'] else '无直接参考')}</td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>36-rule id</th>
          <th>status</th>
          <th>category</th>
          <th>canonical resolved rows</th>
          <th>canonical ratio</th>
          <th>match total</th>
          <th>max</th>
          <th>period source hits</th>
          <th>audit</th>
          <th>notes</th>
          <th>59-rule refs</th>
        </tr>
      </thead>
      <tbody>{''.join(body)}</tbody>
    </table>
    """


def render_overlap_table(pairs: list[dict[str, Any]]) -> str:
    if not pairs:
        return "<p>没有达到阈值的 polymer-level 高重叠 active core 对。</p>"
    body = []
    for pair in pairs[:30]:
        body.append(
            f"""
            <tr>
              <td><code>{esc(pair['a'])}</code><br><span class="subtle">{esc(pair['a_name'])}</span></td>
              <td><code>{esc(pair['b'])}</code><br><span class="subtle">{esc(pair['b_name'])}</span></td>
              <td class="num">{fmt_int(pair['shared'])}</td>
              <td class="num">{pct(pair['jaccard'], 2)}</td>
              <td class="num">{pct(pair['containment_a'], 2)}</td>
              <td class="num">{pct(pair['containment_b'], 2)}</td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>A</th>
          <th>B</th>
          <th>shared rows</th>
          <th>Jaccard</th>
          <th>A in B</th>
          <th>B in A</th>
        </tr>
      </thead>
      <tbody>{''.join(body)}</tbody>
    </table>
    """


def build_html(
    *,
    rules: list[dict[str, Any]],
    canonical_rows: list[dict[str, str]],
    canonical_audit: dict[str, Any],
    rule_rows: list[dict[str, Any]],
    period_scope: dict[str, int],
    overlap_rows: list[dict[str, Any]],
    v1_vocab: list[dict[str, Any]],
    v1_build: dict[str, Any],
    v1_overlap: dict[str, Any],
) -> str:
    denominator = len(canonical_rows)
    status_counts = Counter(rule.get("core_status", ACTIVE_CORE_STATUS) for rule in rules)
    active_count = sum(1 for rule in rules if is_active_core(rule))
    dist = summarize_distribution(canonical_audit["active_type_counts"])
    covered = denominator - len(canonical_audit["unmatched_records"])
    high_generic = [row for row in rule_rows if row["active"] and row["resolved_ratio"] >= 0.5]
    low_core = [row for row in rule_rows if row["active"] and 0 < row["resolved_ratio"] < 0.005]
    nonactive_with_hits = [
        row
        for row in rule_rows
        if not row["active"] and (row["normalized_records"] > 0 or row["normalized_total"] > 0)
    ]
    v1_coverage = v1_build.get("coverage", {})
    four_ring_summary = summarize_ring_attributes(
        ring_records_for_fragment(canonical_audit["ring_attribute_records"], "fragment_016")
    )
    five_aromatic_summary = summarize_ring_attributes(
        ring_records_for_fragment(canonical_audit["ring_attribute_records"], "fragment_017")
    )
    five_nonaromatic_summary = summarize_ring_attributes(
        ring_records_for_fragment(canonical_audit["ring_attribute_records"], "fragment_018")
    )
    six_aromatic_summary = summarize_ring_attributes(
        ring_records_for_fragment(canonical_audit["ring_attribute_records"], "fragment_019")
    )
    six_nonaromatic_summary = summarize_ring_attributes(
        ring_records_for_fragment(canonical_audit["ring_attribute_records"], "fragment_020")
    )
    five_ring_record_count = len(
        {
            record["record_id"]
            for record in canonical_audit["ring_attribute_records"]
            if record["fragment_id"] in {"fragment_017", "fragment_018"}
        }
    )
    six_ring_record_count = len(
        {
            record["record_id"]
            for record in canonical_audit["ring_attribute_records"]
            if record["fragment_id"] in {"fragment_019", "fragment_020"}
        }
    )
    five_ring_count = five_aromatic_summary["ring_count"] + five_nonaromatic_summary["ring_count"]
    six_ring_count = six_aromatic_summary["ring_count"] + six_nonaromatic_summary["ring_count"]

    cards = [
        ("片段规则数", str(len(rules)), f"active core {active_count}; 其余为非核心派生属性"),
        ("11580 覆盖", f"{fmt_int(covered)} / {fmt_int(denominator)}", pct(covered / denominator if denominator else 0, 3)),
        ("平均 active 类型", f"{dist['avg']:.2f}", f"中位数 {dist['median']}; 最大 {dist['max']}"),
        ("四元环 core", f"{fmt_int(four_ring_summary['record_count'])} / {fmt_int(four_ring_summary['ring_count'])}", "records / rings"),
        ("五元环 core", f"{fmt_int(five_ring_record_count)} / {fmt_int(five_ring_count)}", "records / rings"),
        ("六元环 core", f"{fmt_int(six_ring_record_count)} / {fmt_int(six_ring_count)}", "records / rings"),
        ("period 展开口径", fmt_int(period_scope["period_rows"]), f"source id {fmt_int(period_scope['period_source_ids'])}"),
        ("59 条参考词表", str(len(v1_vocab)), f"v1 覆盖 {pct(v1_coverage.get('polymer_with_at_least_one_fragment_ratio', 0), 3)}"),
        ("RDKit", rdBase.rdkitVersion, f"parser failed {canonical_audit['parser_failed']}"),
    ]

    top_rows = sorted(
        [row for row in rule_rows if row["active"]],
        key=lambda row: row["resolved_records"],
        reverse=True,
    )[:12]
    top_list = "\n".join(
        f"<li><code>{esc(row['fragment_id'])}</code> {esc(row['name'])}: "
        f"{fmt_int(row['resolved_records'])} ({pct(row['resolved_ratio'], 1)})</li>"
        for row in top_rows
    )
    low_list = "\n".join(
        f"<li><code>{esc(row['fragment_id'])}</code> {esc(row['name'])}: "
        f"{fmt_int(row['resolved_records'])} ({pct(row['resolved_ratio'], 2)})</li>"
        for row in low_core
    ) or "<li>没有低于 0.5% 且非零命中的 active core。</li>"
    high_generic_list = "\n".join(
        f"<li><code>{esc(row['fragment_id'])}</code> {esc(row['name'])}: "
        f"{fmt_int(row['resolved_records'])} ({pct(row['resolved_ratio'], 1)})，建议输出解释时作为父级/roll-up。</li>"
        for row in high_generic
    ) or "<li>没有超过 50% 覆盖的 active core。</li>"
    nonactive_list = "\n".join(
        f"<li><code>{esc(row['fragment_id'])}</code> {esc(row['name'])}: normalized "
        f"{fmt_int(row['normalized_records'])} rows / {fmt_int(row['normalized_total'])} matches，resolved 已归零。</li>"
        for row in nonactive_with_hits[:12]
    ) or "<li>非 active 条目没有 normalized 命中。</li>"
    unmatched_examples = "\n".join(
        f"<li><code>{esc(row['canonical_id'])}</code> {esc(row['standardized_smiles'])}"
        f"<br><span class=\"subtle\">non-active hits: {esc(row.get('_nonactive_hits') or 'none')}</span></li>"
        for row in canonical_audit["unmatched_records"][:12]
    ) or "<li>无未覆盖样例。</li>"
    gap_aux = "\n".join(
        f"<li><code>{esc(fragment_id)}</code>: {fmt_int(count)} unmatched rows</li>"
        for fragment_id, count in canonical_audit["unmatched_nonactive_hits"].most_common(8)
    ) or "<li>未覆盖条目没有命中任何非 active 规则。</li>"

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>base_fragment_new2 片段规则审计报告</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17212b;
      --muted: #657384;
      --line: #d9e0e8;
      --paper: #ffffff;
      --band: #f5f7fa;
      --ok: #217a52;
      --ok-bg: #e6f4ee;
      --warn: #a35b00;
      --warn-bg: #fff2d8;
      --info: #245a9c;
      --info-bg: #e8f1ff;
      --bad: #a93d3d;
      --bad-bg: #ffe8e8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--band);
      line-height: 1.55;
    }}
    header {{
      padding: 34px 42px 26px;
      background: #1f3544;
      color: #fff;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #d8e4ec; max-width: 980px; }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 28px 32px 48px; }}
    h2 {{ margin: 34px 0 12px; font-size: 22px; }}
    h3 {{ margin: 22px 0 10px; font-size: 17px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin: 20px 0;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
      min-width: 0;
    }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .metric {{ font-size: 25px; font-weight: 700; margin-top: 4px; }}
    .card p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
    .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px 20px;
      margin: 16px 0;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 16px;
    }}
    ul {{ margin: 8px 0 0 20px; padding: 0; }}
    li {{ margin: 5px 0; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .92em;
      background: #eef2f6;
      border-radius: 4px;
      padding: 1px 4px;
    }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1180px; }}
    table.compact-table {{ min-width: 0; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ text-align: left; background: #eef3f7; font-size: 12px; color: #344657; position: sticky; top: 0; }}
    td {{ font-size: 13px; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .subtle {{ color: var(--muted); font-size: 12px; }}
    .refs {{ color: #394b5c; min-width: 220px; }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }}
    .badge.ok {{ color: var(--ok); background: var(--ok-bg); }}
    .badge.warn {{ color: var(--warn); background: var(--warn-bg); }}
    .badge.info {{ color: var(--info); background: var(--info-bg); }}
    .badge.muted {{ color: #52616f; background: #edf0f2; }}
    .hist-row {{
      display: grid;
      grid-template-columns: 42px minmax(140px, 1fr) 150px;
      align-items: center;
      gap: 10px;
      margin: 6px 0;
    }}
    .hist-key {{ font-variant-numeric: tabular-nums; color: var(--muted); }}
    .hist-bar {{
      height: 12px;
      background: #e5ebf1;
      border-radius: 999px;
      overflow: hidden;
    }}
    .hist-bar span {{ display: block; height: 100%; background: #4c8fb5; }}
    .hist-value {{ color: var(--muted); font-size: 13px; }}
    footer {{ color: var(--muted); font-size: 12px; margin-top: 30px; }}
    @media (max-width: 1100px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .two-col {{ grid-template-columns: 1fr; }}
      header {{ padding: 28px 24px 22px; }}
      main {{ padding: 22px 18px 36px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>base_fragment_new2 片段规则审计报告</h1>
    <p>主审计对象为 <code>fragments_1/base_fragment_new2.json</code>；其中 active core 是 {active_count} 条。59 条 <code>fragment_vocab_v1.0</code> 仅作为参考系。报告同时使用 11580 条 canonical repeat-unit 与 period-expanded resolved 统计。</p>
  </header>
  <main>
    <section class="grid">
      {render_cards(cards)}
    </section>

    <section class="panel">
      <h2>审计结论</h2>
      <ul>
        <li>修后的 {len(rules)} 条规则可以作为当前主片段体系继续使用；其中真正进入下游 resolved 输出的是 {active_count} 条 active core。</li>
        <li>覆盖口径上，11580 条 canonical repeat-unit 中有 {fmt_int(covered)} 条命中至少一个 active core，覆盖率为 {pct(covered / denominator if denominator else 0, 3)}。</li>
        <li>仍有 {fmt_int(len(canonical_audit["unmatched_records"]))} 条 canonical repeat-unit 未命中 active core，主要需要判断是否补充全脂肪/烷基/取代烯烃类核心，或继续视为当前词表范围外。</li>
        <li>非 active 条目包括 {status_counts.get('derived_attribute', 0)} 条 derived attribute、{status_counts.get('deprecated_alias', 0)} 条 deprecated alias、{status_counts.get('rejected', 0)} 条 rejected；它们有些仍有 raw/normalized 命中，但 resolved 输出已归零。</li>
        <li><code>fragment_016 four_membered_ring</code> 已作为结构-性质相关核心片段进入 active core；碳/杂环、芳香性、稠合、多取代和取代位置作为 match attributes 保留。</li>
        <li><code>fragment_017</code> 与 <code>fragment_018</code> 已改为 RDKit 真实五元环 matcher；fully aromatic / not fully aromatic 决定两个 active core，环环境信息进入 attributes。</li>
        <li><code>fragment_019</code> 与 <code>fragment_020</code> 已改为 RDKit 真实六元环 matcher；fully aromatic / not fully aromatic 决定两个 active core，环环境信息进入 attributes。</li>
        <li>主要剩余风险不是编译或零命中，而是高覆盖泛化规则的解释层级：醚、酯、酰胺、羰基等应在最终解释中作为父级/roll-up 或和更具体规则配合。</li>
      </ul>
    </section>

    <section class="two-col">
      <div class="panel">
        <h2>Top active core</h2>
        <ul>{top_list}</ul>
      </div>
      <div class="panel">
        <h2>active 类型分布</h2>
        {render_histogram(dist['histogram'], denominator)}
      </div>
    </section>

    <section class="two-col">
      <div class="panel">
        <h2>需要继续观察</h2>
        <h3>高覆盖泛化规则</h3>
        <ul>{high_generic_list}</ul>
        <h3>低频但化学语义明确的 core</h3>
        <ul>{low_list}</ul>
      </div>
      <div class="panel">
        <h2>非 active 命中</h2>
        <p>这些条目仍可用于审计，但不应进入核心输出。</p>
        <ul>{nonactive_list}</ul>
      </div>
    </section>

    <section class="panel">
      <h2>四元环结构属性</h2>
      <p><code>fragment_016 four_membered_ring</code> 是唯一四元环 active core。下面的碳/杂环、芳香性、稠合/多环连接和外接取代基信息来自同一个 ring match 的 attributes，不再作为独立 fragment id 重复计数。</p>
      <div class="two-col">
        <div>
          <h3>环原子类别</h3>
          {render_attribute_table(four_ring_summary['ring_atom_class'])}
          <h3>芳香性</h3>
          {render_attribute_table(four_ring_summary['aromaticity'])}
        </div>
        <div>
          <h3>稠合/多环</h3>
          {render_attribute_table(four_ring_summary['polycyclic'])}
          <h3>稠合/多环连接位置数</h3>
          {render_attribute_table(four_ring_summary['polycyclic_connection_count'])}
        </div>
      </div>
      <div class="two-col">
        <div>
          <h3>外接取代基数</h3>
          {render_attribute_table(four_ring_summary['exocyclic_substituent_count'])}
          <h3>外接取代基拓扑</h3>
          {render_attribute_table(four_ring_summary['exocyclic_substituent_topology'])}
        </div>
        <div>
          <h3>总外部连接数</h3>
          {render_attribute_table(four_ring_summary['external_connection_count'])}
          <h3>总外部连接拓扑</h3>
          {render_attribute_table(four_ring_summary['external_connection_topology'])}
        </div>
      </div>
      <h3>稠合/多环连接拓扑</h3>
      {render_attribute_table(four_ring_summary['polycyclic_connection_topology'])}
      <div class="two-col">
        <div>
          <h3>dummy attachment 数</h3>
          {render_attribute_table(four_ring_summary['attachment_count'])}
        </div>
        <div>
          <h3>主链穿环判定</h3>
          {render_attribute_table(four_ring_summary['mainchain_through_ring'])}
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>五元环结构属性</h2>
      <p><code>fragment_017 five_membered_aromatic_ring</code> 与 <code>fragment_018 five_membered_not_fully_aromatic_ring</code> 均使用 RDKit ring info 枚举真实五元环。fully aromatic / not fully aromatic 保留为两个 active core；杂环、杂原子 signature、稠合、多环连接和取代环境作为 attributes 输出，不新增杂环 active core。</p>
      <p class="subtle"><code>fragment_018</code> 表示 not fully aromatic five-membered ring，包括普通饱和五元环，以及 fused/imide/fluorene-like 等部分 aromatic atom 参与的真实五元环。它与 imide/fused imide 的高共现属于 ring scaffold 与 functional group 的不同解释层级，不应互相 suppress。</p>
      <div class="two-col">
        <div>
          <h3>芳香五元环：环原子类别</h3>
          {render_attribute_table(five_aromatic_summary['ring_atom_class'])}
          <h3>芳香五元环：杂原子 signature</h3>
          {render_attribute_table(five_aromatic_summary['hetero_atom_signature'])}
          <h3>芳香五元环：芳香性分级</h3>
          {render_attribute_table(five_aromatic_summary['ring_aromaticity_class'])}
          <h3>芳香五元环：稠合/多环</h3>
          {render_attribute_table(five_aromatic_summary['polycyclic'])}
          <h3>芳香五元环：外接取代基数</h3>
          {render_attribute_table(five_aromatic_summary['exocyclic_substituent_count'])}
          <h3>芳香五元环：主链穿环判定</h3>
          {render_attribute_table(five_aromatic_summary['mainchain_through_ring'])}
        </div>
        <div>
          <h3>not fully aromatic 五元环：环原子类别</h3>
          {render_attribute_table(five_nonaromatic_summary['ring_atom_class'])}
          <h3>not fully aromatic 五元环：杂原子 signature</h3>
          {render_attribute_table(five_nonaromatic_summary['hetero_atom_signature'])}
          <h3>not fully aromatic 五元环：芳香原子数</h3>
          {render_attribute_table(five_nonaromatic_summary['ring_aromatic_atom_count'])}
          <h3>not fully aromatic 五元环：芳香性分级</h3>
          {render_attribute_table(five_nonaromatic_summary['ring_aromaticity_class'])}
          <h3>not fully aromatic 五元环：稠合/多环</h3>
          {render_attribute_table(five_nonaromatic_summary['polycyclic'])}
          <h3>not fully aromatic 五元环：外接取代基数</h3>
          {render_attribute_table(five_nonaromatic_summary['exocyclic_substituent_count'])}
          <h3>not fully aromatic 五元环：主链穿环判定</h3>
          {render_attribute_table(five_nonaromatic_summary['mainchain_through_ring'])}
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>六元环结构属性</h2>
      <p><code>fragment_019 six_membered_aromatic_ring</code> 与 <code>fragment_020 six_membered_not_fully_aromatic_ring</code> 均使用 RDKit ring info 枚举真实六元环。fully aromatic / not fully aromatic 保留为两个 active core；杂环、稠合、多环连接和取代环境作为 attributes 输出。</p>
      <p class="subtle">六元杂环、稠合六元环、多取代六元环不新增独立 active core；这些语义由同一个 ring match 的 attributes 表达。</p>
      <div class="two-col">
        <div>
          <h3>芳香六元环：环原子类别</h3>
          {render_attribute_table(six_aromatic_summary['ring_atom_class'])}
          <h3>芳香六元环：杂原子 signature</h3>
          {render_attribute_table(six_aromatic_summary['hetero_atom_signature'])}
          <h3>芳香六元环：芳香性分级</h3>
          {render_attribute_table(six_aromatic_summary['ring_aromaticity_class'])}
          <h3>芳香六元环：稠合/多环</h3>
          {render_attribute_table(six_aromatic_summary['polycyclic'])}
          <h3>芳香六元环：外接取代基数</h3>
          {render_attribute_table(six_aromatic_summary['exocyclic_substituent_count'])}
          <h3>芳香六元环：主链穿环判定</h3>
          {render_attribute_table(six_aromatic_summary['mainchain_through_ring'])}
        </div>
        <div>
          <h3>not fully aromatic 六元环：环原子类别</h3>
          {render_attribute_table(six_nonaromatic_summary['ring_atom_class'])}
          <h3>not fully aromatic 六元环：杂原子 signature</h3>
          {render_attribute_table(six_nonaromatic_summary['hetero_atom_signature'])}
          <h3>not fully aromatic 六元环：芳香原子数</h3>
          {render_attribute_table(six_nonaromatic_summary['ring_aromatic_atom_count'])}
          <h3>not fully aromatic 六元环：芳香性分级</h3>
          {render_attribute_table(six_nonaromatic_summary['ring_aromaticity_class'])}
          <h3>not fully aromatic 六元环：稠合/多环</h3>
          {render_attribute_table(six_nonaromatic_summary['polycyclic'])}
          <h3>not fully aromatic 六元环：外接取代基数</h3>
          {render_attribute_table(six_nonaromatic_summary['exocyclic_substituent_count'])}
          <h3>not fully aromatic 六元环：主链穿环判定</h3>
          {render_attribute_table(six_nonaromatic_summary['mainchain_through_ring'])}
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>11580 canonical 口径逐条审计</h2>
      <div class="table-wrap">
        {render_rule_table(rule_rows)}
      </div>
    </section>

    <section class="panel">
      <h2>active core 高重叠对</h2>
      <p>这里按 canonical row 的 resolved 命中集合计算，阈值为 Jaccard ≥ 45% 或任一方向 containment ≥ 90%。这是分子级共现，不等于实例级冲突，但能提示解释层级。</p>
      <div class="table-wrap">
        {render_overlap_table(overlap_rows)}
      </div>
    </section>

    <section class="two-col">
      <div class="panel">
        <h2>未覆盖样例</h2>
        <p>最多展示 12 条 canonical repeat-unit；这些条目没有命中任何 active core。</p>
        <h3>未覆盖条目的非 active 命中</h3>
        <ul>{gap_aux}</ul>
        <h3>样例</h3>
        <ul>{unmatched_examples}</ul>
      </div>
      <div class="panel">
        <h2>59 条参考词表启示</h2>
        <ul>
          <li>59 条 v1 是高覆盖 feature vocabulary，不是本轮主核心词表；其验证覆盖为 {pct(v1_coverage.get('polymer_with_at_least_one_fragment_ratio', 0), 3)}，平均每条 polymer 命中 {v1_coverage.get('avg_fragment_types_per_polymer', 0):.2f} 类。</li>
          <li>v1 的高重叠规则对为 {fmt_int(v1_overlap.get('high_overlap_pair_count', 0))}，说明当前词表引入 resolved 层是必要且方向正确的。</li>
          <li>可借鉴 v1 的拆分方向：醚可拆 aromatic ether / alkoxy，胺可拆 secondary / tertiary，环可拆 heteroaromatic / cycloaliphatic / fused，卤素可拆 F/Cl/Br/CF3/perfluoroalkyl。</li>
          <li>这些拆分不建议直接平铺进当前 active core；应先定义 priority、父子关系和 instance suppression 后再提升。</li>
        </ul>
      </div>
    </section>

    <footer>
      生成时间 UTC: {esc(generated)} · RDKit {esc(rdBase.rdkitVersion)} · canonical file: {esc(DEFAULT_CANONICAL.relative_to(ROOT))} · period stats: {esc(DEFAULT_PERIOD_STATS.relative_to(ROOT))}
    </footer>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HTML audit report for base_fragment_new2.")
    parser.add_argument("--vocab", type=Path, default=DEFAULT_VOCAB)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--period-stats", type=Path, default=DEFAULT_PERIOD_STATS)
    parser.add_argument("--periods", type=Path, default=DEFAULT_PERIODS)
    parser.add_argument("--v1-vocab", type=Path, default=DEFAULT_V1_VOCAB)
    parser.add_argument("--v1-stats", type=Path, default=DEFAULT_V1_STATS)
    parser.add_argument("--v1-build", type=Path, default=DEFAULT_V1_BUILD)
    parser.add_argument("--v1-overlap", type=Path, default=DEFAULT_V1_OVERLAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rules = json.loads(args.vocab.read_text(encoding="utf-8"))
    canonical_rows = read_canonical_rows(args.canonical)
    canonical_audit = compute_canonical_audit(rules, canonical_rows)
    period_stats = read_period_stats(args.period_stats)
    period_scope = count_period_scope(args.periods)
    v1_vocab = load_json_or_empty(args.v1_vocab)
    v1_stats = load_json_or_empty(args.v1_stats)
    v1_build = load_json_or_empty(args.v1_build)
    v1_overlap = load_json_or_empty(args.v1_overlap)
    rule_rows = build_rule_rows(rules, canonical_audit, period_stats, len(canonical_rows), v1_stats)
    overlaps = overlap_pairs(rules, canonical_audit["resolved_id_sets"])

    html_text = build_html(
        rules=rules,
        canonical_rows=canonical_rows,
        canonical_audit=canonical_audit,
        rule_rows=rule_rows,
        period_scope=period_scope,
        overlap_rows=overlaps,
        v1_vocab=v1_vocab,
        v1_build=v1_build,
        v1_overlap=v1_overlap,
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(args.output),
                "canonical_rows": len(canonical_rows),
                "parser_failed": canonical_audit["parser_failed"],
                "active_core_count": sum(1 for rule in rules if is_active_core(rule)),
                "covered": len(canonical_rows) - len(canonical_audit["unmatched_records"]),
                "high_overlap_pairs": len(overlaps),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
