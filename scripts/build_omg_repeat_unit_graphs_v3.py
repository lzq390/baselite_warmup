from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.omg_v3_common import (
        EDGE_BOOL_FIELDS,
        EDGE_CATEGORICAL_FIELDS,
        NODE_BOOL_FIELDS,
        NODE_CATEGORICAL_FIELDS,
        NODE_NUMERIC_FIELDS,
        ROOT,
        graph_row_for_record,
        read_dataset_rows,
        require_rdkit,
        split_counts,
        write_json,
    )
except ModuleNotFoundError:
    from omg_v3_common import (
        EDGE_BOOL_FIELDS,
        EDGE_CATEGORICAL_FIELDS,
        NODE_BOOL_FIELDS,
        NODE_CATEGORICAL_FIELDS,
        NODE_NUMERIC_FIELDS,
        ROOT,
        graph_row_for_record,
        read_dataset_rows,
        require_rdkit,
        split_counts,
        write_json,
    )


DEFAULT_DATASET_DIR = ROOT / "data" / "baselite_smiles_v3"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "omg_repeat_unit_graphs_v3.jsonl"
DEFAULT_AUDIT_OUTPUT_DIR = ROOT / "data" / "baselite_stage_c_v3"
NULL_CATEGORY = "__null__"


def progress_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def normalize_category(value: Any) -> str:
    if value is None or value == "":
        return NULL_CATEGORY
    return str(value)


def percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    index = round((len(sorted_values) - 1) * p)
    return sorted_values[index]


def length_stats(values: list[int]) -> dict[str, Any]:
    sorted_values = sorted(values)
    return {
        "count": len(sorted_values),
        "min": sorted_values[0] if sorted_values else 0,
        "p50": percentile(sorted_values, 0.50),
        "p90": percentile(sorted_values, 0.90),
        "p95": percentile(sorted_values, 0.95),
        "p99": percentile(sorted_values, 0.99),
        "max": sorted_values[-1] if sorted_values else 0,
        "mean": round(statistics.fmean(sorted_values), 4) if sorted_values else 0.0,
    }


class GraphAuditAccumulator:
    def __init__(self, dataset_rows: list[dict[str, Any]]) -> None:
        self.dataset_rows = dataset_rows
        self.dataset_by_record = {str(row["record_id"]): row for row in dataset_rows}
        self.dataset_canonical_hashes = {str(row["canonical_hash"]) for row in dataset_rows}
        self.remaining_record_ids = set(self.dataset_by_record)
        self.remaining_canonical_hashes = set(self.dataset_canonical_hashes)
        self.seen_record_ids: set[str] = set()
        self.seen_canonical_hashes: set[str] = set()
        self.graph_rows = 0
        self.extra_graph_record_count = 0
        self.extra_graph_record_examples: list[str] = []
        self.canonical_hash_mismatches: list[dict[str, str]] = []
        self.node_categories: dict[str, set[str]] = {field: set() for field in NODE_CATEGORICAL_FIELDS}
        self.edge_categories: dict[str, set[str]] = {field: set() for field in EDGE_CATEGORICAL_FIELDS}
        self.node_counts: list[int] = []
        self.edge_counts: list[int] = []
        self.elements: Counter[str] = Counter()
        self.bond_types: Counter[str] = Counter()

    def add_graph(self, graph: dict[str, Any]) -> None:
        self.graph_rows += 1
        record_id = str(graph["record_id"])
        canonical_hash = str(graph["canonical_hash"])
        if record_id in self.seen_record_ids:
            raise ValueError(f"duplicate record_id in graph rows: {record_id}")
        if canonical_hash in self.seen_canonical_hashes:
            raise ValueError(f"duplicate canonical_hash in graph rows: {canonical_hash}")
        self.seen_record_ids.add(record_id)
        self.seen_canonical_hashes.add(canonical_hash)

        dataset_row = self.dataset_by_record.get(record_id)
        if dataset_row is None:
            self.extra_graph_record_count += 1
            if len(self.extra_graph_record_examples) < 20:
                self.extra_graph_record_examples.append(record_id)
        else:
            self.remaining_record_ids.discard(record_id)
            self.remaining_canonical_hashes.discard(canonical_hash)
            if str(dataset_row["canonical_hash"]) != canonical_hash:
                self.canonical_hash_mismatches.append(
                    {
                        "record_id": record_id,
                        "dataset_canonical_hash": str(dataset_row["canonical_hash"]),
                        "graph_canonical_hash": canonical_hash,
                    }
                )

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        self.node_counts.append(len(nodes))
        self.edge_counts.append(len(edges))
        for node in nodes:
            self.elements[normalize_category(node.get("element"))] += 1
            for field in NODE_CATEGORICAL_FIELDS:
                self.node_categories[field].add(normalize_category(node.get(field)))
        for edge in edges:
            self.bond_types[normalize_category(edge.get("bond_type"))] += 1
            for field in EDGE_CATEGORICAL_FIELDS:
                self.edge_categories[field].add(normalize_category(edge.get(field)))

    def feature_schema(self) -> dict[str, Any]:
        node_feature_dim = (
            len(NODE_NUMERIC_FIELDS)
            + len(NODE_BOOL_FIELDS)
            + sum(len(values) for values in self.node_categories.values())
        )
        edge_feature_dim = len(EDGE_BOOL_FIELDS) + sum(len(values) for values in self.edge_categories.values())
        return {
            "schema_version": "stage_c_graph_features_v1",
            "null_category": NULL_CATEGORY,
            "node": {
                "categorical_fields": {field: sorted(values) for field, values in self.node_categories.items()},
                "numeric_fields": list(NODE_NUMERIC_FIELDS),
                "bool_fields": list(NODE_BOOL_FIELDS),
                "feature_dim": node_feature_dim,
            },
            "edge": {
                "categorical_fields": {field: sorted(values) for field, values in self.edge_categories.items()},
                "bool_fields": list(EDGE_BOOL_FIELDS),
                "feature_dim": edge_feature_dim,
                "directed_edge_policy": "bidirectional_expand_each_json_edge",
            },
        }

    def graph_stats(self) -> dict[str, Any]:
        return {
            "node_count": length_stats(self.node_counts),
            "edge_count": length_stats(self.edge_counts),
            "top_elements": self.elements.most_common(20),
            "bond_types": dict(sorted(self.bond_types.items())),
        }

    def join_quality(self) -> dict[str, Any]:
        return {
            "dataset_rows": len(self.dataset_rows),
            "graph_rows": self.graph_rows,
            "missing_graph_by_record_id": len(self.remaining_record_ids),
            "missing_graph_by_canonical_hash": len(self.remaining_canonical_hashes),
            "canonical_hash_mismatch_count": len(self.canonical_hash_mismatches),
            "canonical_hash_mismatch_examples": self.canonical_hash_mismatches[:20],
            "extra_graph_record_count": self.extra_graph_record_count,
            "extra_graph_record_examples": self.extra_graph_record_examples,
        }


def build_manifest(
    *,
    dataset_dir: Path,
    graph_path: Path,
    output_dir: Path,
    dataset_rows: list[dict[str, Any]],
    accumulator: GraphAuditAccumulator,
) -> dict[str, Any]:
    feature_schema = accumulator.feature_schema()
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
            "graph_rows": accumulator.graph_rows,
            "split": split_counts(dataset_rows),
            "unique_record_id": len({row["record_id"] for row in dataset_rows}),
            "unique_canonical_hash": len({row["canonical_hash"] for row in dataset_rows}),
            "unique_graph_hash": len({row["graph_hash"] for row in dataset_rows}),
        },
        "join_quality": accumulator.join_quality(),
        "graph_stats": accumulator.graph_stats(),
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
        "# BaseLite OMG v3 Stage C Non-vocab Dataset Audit",
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
        "- Graph tensors are represented by the graph JSONL sidecar.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_join_quality(manifest: dict[str, Any]) -> None:
    join = manifest["join_quality"]
    failed = {
        "missing_graph_by_record_id": join["missing_graph_by_record_id"],
        "missing_graph_by_canonical_hash": join["missing_graph_by_canonical_hash"],
        "canonical_hash_mismatch_count": join["canonical_hash_mismatch_count"],
        "extra_graph_record_count": join["extra_graph_record_count"],
    }
    failed = {key: value for key, value in failed.items() if value}
    if failed:
        raise SystemExit(f"OMG v3 graph audit failed: {json.dumps(failed, sort_keys=True)}")


def build_omg_graphs(
    dataset_dir: Path,
    graph_path: Path,
    audit_output_dir: Path,
    *,
    progress_every: int | None = 100_000,
) -> dict[str, Any]:
    Chem = require_rdkit()
    dataset_rows = read_dataset_rows(dataset_dir)
    accumulator = GraphAuditAccumulator(dataset_rows)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    with graph_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(dataset_rows, start=1):
            graph = graph_row_for_record(record, Chem)
            accumulator.add_graph(graph)
            handle.write(json.dumps(graph, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
            if progress_every and index % progress_every == 0:
                progress_log(f"[graph] rows={index}")

    feature_schema = accumulator.feature_schema()
    manifest = build_manifest(
        dataset_dir=dataset_dir,
        graph_path=graph_path,
        output_dir=audit_output_dir,
        dataset_rows=dataset_rows,
        accumulator=accumulator,
    )
    audit_output_dir.mkdir(parents=True, exist_ok=True)
    write_json(audit_output_dir / "graph_feature_schema.json", feature_schema)
    write_json(audit_output_dir / "stage_c_manifest.json", manifest)
    write_join_report(audit_output_dir / "stage_c_join_report.md", manifest)
    assert_join_quality(manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BaseLite OMG v3 repeat-unit graph sidecar.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-output-dir", type=Path, default=DEFAULT_AUDIT_OUTPUT_DIR)
    parser.add_argument("--progress-every", type=int, default=100_000)
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_omg_graphs(
        args.dataset_dir,
        args.output,
        args.audit_output_dir,
        progress_every=args.progress_every,
    )
    if args.summary:
        print(
            json.dumps(
                {
                    "graph_path": str(args.output),
                    "counts": manifest["counts"],
                    "join_quality": manifest["join_quality"],
                    "feature_schema_summary": manifest["feature_schema_summary"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
