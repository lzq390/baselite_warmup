from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v1"
DEFAULT_GRAPH_PATH = ROOT / "data" / "processed" / "repeat_unit_graphs.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "baselite_stage_c_v1"
SPLITS = ("train", "valid", "test")
NULL_CATEGORY = "__null__"

NODE_CATEGORICAL_FIELDS = ("element", "hybridization", "attachment_role")
NODE_NUMERIC_FIELDS = ("atomic_num", "degree", "formal_charge")
NODE_BOOL_FIELDS = ("aromatic", "is_attachment", "ring_membership")
EDGE_CATEGORICAL_FIELDS = ("bond_type",)
EDGE_BOOL_FIELDS = ("aromatic", "is_periodic_edge", "is_repeat_connection")


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


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_category(value: Any) -> str:
    if value is None or value == "":
        return NULL_CATEGORY
    return str(value)


def length_stats(values: list[int]) -> dict[str, Any]:
    sorted_values = sorted(values)
    if not sorted_values:
        return {"count": 0, "min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0.0}

    def percentile(p: float) -> int:
        index = round((len(sorted_values) - 1) * p)
        return sorted_values[index]

    return {
        "count": len(sorted_values),
        "min": sorted_values[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": sorted_values[-1],
        "mean": round(statistics.fmean(sorted_values), 4),
    }


def read_dataset_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_path = dataset_dir / f"{split}.jsonl"
        for line_no, row in enumerate(read_jsonl(split_path), start=1):
            for field in ("record_id", "canonical_smiles", "canonical_hash", "graph_hash", "split"):
                if row.get(field) in (None, ""):
                    raise ValueError(f"{split_path}:{line_no}: missing {field}")
            if row["split"] != split:
                raise ValueError(f"{split_path}:{line_no}: split={row['split']!r}, expected {split!r}")
            rows.append(row)
    return rows


def index_unique(rows: list[dict[str, Any]], key: str, *, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        value = str(row[key])
        if value in indexed:
            duplicates.append(value)
        indexed[value] = row
    if duplicates:
        examples = ", ".join(sorted(set(duplicates))[:5])
        raise ValueError(f"duplicate {key} in {label}: {examples}")
    return indexed


def validate_join(dataset_rows: list[dict[str, Any]], graph_rows: list[dict[str, Any]]) -> dict[str, Any]:
    graphs_by_record = index_unique(graph_rows, "record_id", label="graph rows")
    graphs_by_canonical = index_unique(graph_rows, "canonical_hash", label="graph rows")
    dataset_by_record = index_unique(dataset_rows, "record_id", label="dataset rows")

    missing_by_record = [row["record_id"] for row in dataset_rows if row["record_id"] not in graphs_by_record]
    missing_by_canonical = [row["canonical_hash"] for row in dataset_rows if row["canonical_hash"] not in graphs_by_canonical]
    extra_graph_records = sorted(set(graphs_by_record) - set(dataset_by_record))
    mismatched_hashes: list[dict[str, str]] = []

    for row in dataset_rows:
        graph = graphs_by_record.get(row["record_id"])
        if graph is None:
            continue
        if str(graph.get("canonical_hash")) != str(row["canonical_hash"]):
            mismatched_hashes.append(
                {
                    "record_id": str(row["record_id"]),
                    "dataset_canonical_hash": str(row["canonical_hash"]),
                    "graph_canonical_hash": str(graph.get("canonical_hash")),
                }
            )

    if missing_by_record or missing_by_canonical or mismatched_hashes:
        raise ValueError(
            "Stage C graph join failed: "
            f"missing_by_record={len(missing_by_record)}, "
            f"missing_by_canonical={len(missing_by_canonical)}, "
            f"canonical_hash_mismatches={len(mismatched_hashes)}"
        )

    return {
        "dataset_rows": len(dataset_rows),
        "graph_rows": len(graph_rows),
        "missing_graph_by_record_id": len(missing_by_record),
        "missing_graph_by_canonical_hash": len(missing_by_canonical),
        "canonical_hash_mismatch_count": len(mismatched_hashes),
        "extra_graph_record_count": len(extra_graph_records),
        "extra_graph_record_examples": extra_graph_records[:20],
    }


def build_graph_feature_schema(graph_rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_categories: dict[str, set[str]] = {field: set() for field in NODE_CATEGORICAL_FIELDS}
    edge_categories: dict[str, set[str]] = {field: set() for field in EDGE_CATEGORICAL_FIELDS}

    for graph in graph_rows:
        for node in graph.get("nodes", []):
            for field in NODE_CATEGORICAL_FIELDS:
                node_categories[field].add(normalize_category(node.get(field)))
        for edge in graph.get("edges", []):
            for field in EDGE_CATEGORICAL_FIELDS:
                edge_categories[field].add(normalize_category(edge.get(field)))

    node_feature_dim = len(NODE_NUMERIC_FIELDS) + len(NODE_BOOL_FIELDS) + sum(len(values) for values in node_categories.values())
    edge_feature_dim = len(EDGE_BOOL_FIELDS) + sum(len(values) for values in edge_categories.values())
    return {
        "schema_version": "stage_c_graph_features_v1",
        "null_category": NULL_CATEGORY,
        "node": {
            "categorical_fields": {field: sorted(values) for field, values in node_categories.items()},
            "numeric_fields": list(NODE_NUMERIC_FIELDS),
            "bool_fields": list(NODE_BOOL_FIELDS),
            "feature_dim": node_feature_dim,
        },
        "edge": {
            "categorical_fields": {field: sorted(values) for field, values in edge_categories.items()},
            "bool_fields": list(EDGE_BOOL_FIELDS),
            "feature_dim": edge_feature_dim,
            "directed_edge_policy": "bidirectional_expand_each_json_edge",
        },
    }


def graph_stats(graph_rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_counts = [len(row.get("nodes", [])) for row in graph_rows]
    edge_counts = [len(row.get("edges", [])) for row in graph_rows]
    elements = Counter(normalize_category(node.get("element")) for row in graph_rows for node in row.get("nodes", []))
    bond_types = Counter(normalize_category(edge.get("bond_type")) for row in graph_rows for edge in row.get("edges", []))
    return {
        "node_count": length_stats(node_counts),
        "edge_count": length_stats(edge_counts),
        "top_elements": elements.most_common(20),
        "bond_types": dict(sorted(bond_types.items())),
    }


def split_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["split"]) for row in rows)
    return {split: counts.get(split, 0) for split in SPLITS}


def build_manifest(
    *,
    dataset_dir: Path,
    graph_path: Path,
    output_dir: Path,
    dataset_rows: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    join_report: dict[str, Any],
    feature_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": "stage_c_non_vocab_dataset_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": str(dataset_dir),
        "graph_path": str(graph_path),
        "output_dir": str(output_dir),
        "outputs": {
            "manifest": str(output_dir / "stage_c_manifest.json"),
            "graph_feature_schema": str(output_dir / "graph_feature_schema.json"),
            "join_report": str(output_dir / "stage_c_join_report.md"),
        },
        "counts": {
            "dataset_rows": len(dataset_rows),
            "graph_rows": len(graph_rows),
            "split": split_counts(dataset_rows),
            "unique_record_id": len({row["record_id"] for row in dataset_rows}),
            "unique_canonical_hash": len({row["canonical_hash"] for row in dataset_rows}),
            "unique_graph_hash": len({row["graph_hash"] for row in dataset_rows}),
        },
        "join_quality": join_report,
        "graph_stats": graph_stats(graph_rows),
        "feature_schema_summary": {
            "node_feature_dim": feature_schema["node"]["feature_dim"],
            "edge_feature_dim": feature_schema["edge"]["feature_dim"],
            "node_categorical_sizes": {
                key: len(value) for key, value in feature_schema["node"]["categorical_fields"].items()
            },
            "edge_categorical_sizes": {
                key: len(value) for key, value in feature_schema["edge"]["categorical_fields"].items()
            },
        },
        "fragment_vocab": None,
        "uses_fragment_labels": False,
        "uses_graph_tensor": True,
    }


def write_join_report(path: Path, manifest: dict[str, Any]) -> None:
    counts = manifest["counts"]
    join = manifest["join_quality"]
    schema = manifest["feature_schema_summary"]
    lines = [
        "# BaseLite Stage C Non-vocab Dataset Audit",
        "",
        f"- generated_at_utc: `{manifest['generated_at_utc']}`",
        f"- dataset_dir: `{manifest['dataset_dir']}`",
        f"- graph_path: `{manifest['graph_path']}`",
        f"- dataset rows: `{counts['dataset_rows']}`",
        f"- graph rows: `{counts['graph_rows']}`",
        f"- split counts: `{counts['split']}`",
        "",
        "## Join Quality",
        "",
        f"- missing graph by record_id: `{join['missing_graph_by_record_id']}`",
        f"- missing graph by canonical_hash: `{join['missing_graph_by_canonical_hash']}`",
        f"- canonical hash mismatches: `{join['canonical_hash_mismatch_count']}`",
        f"- extra graph records: `{join['extra_graph_record_count']}`",
        "",
        "## Graph Feature Schema",
        "",
        f"- node feature dim: `{schema['node_feature_dim']}`",
        f"- edge feature dim: `{schema['edge_feature_dim']}`",
        f"- node categorical sizes: `{schema['node_categorical_sizes']}`",
        f"- edge categorical sizes: `{schema['edge_categorical_sizes']}`",
        "",
        "## Stage C Scope",
        "",
        "- Opens `L_restore` and `L_align`.",
        "- Closes fragment vocab, fragment matcher, fragment presence, and fragment consistency.",
        "- This audit does not copy graph tensors; training reads the canonical dataset and graph JSONL sources.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_stage_c_audit(dataset_dir: Path, graph_path: Path, output_dir: Path) -> dict[str, Any]:
    dataset_rows = read_dataset_rows(dataset_dir)
    graph_rows = read_jsonl(graph_path)
    join_report = validate_join(dataset_rows, graph_rows)
    feature_schema = build_graph_feature_schema(graph_rows)
    manifest = build_manifest(
        dataset_dir=dataset_dir,
        graph_path=graph_path,
        output_dir=output_dir,
        dataset_rows=dataset_rows,
        graph_rows=graph_rows,
        join_report=join_report,
        feature_schema=feature_schema,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "graph_feature_schema.json", feature_schema)
    write_json(output_dir / "stage_c_manifest.json", manifest)
    write_join_report(output_dir / "stage_c_join_report.md", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Stage C non-vocab dataset and graph inputs.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_stage_c_audit(args.dataset_dir, args.graph_path, args.output_dir)
    if args.summary:
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
