#!/usr/bin/env python3
"""Compare two research JSON snapshots without inventing changed facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_research import COLLECTIONS as ID_COLLECTIONS, load_json, schema_validate, semantic_validate

COLLECTION_KEYS = {
    **{name: "id" for name in ID_COLLECTIONS},
    "source_coverage": "perspective",
    "footprint_coverage": "dimension",
    "discarded_sources": "url",
}
METADATA_FIELDS_BY_COLLECTION = {
    "sources": {"retrieved_at"},
    "source_health": {"observed_at", "last_success_at"},
}
META_METADATA_FIELDS = {"generated_at"}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "research.schema.json"


def load(path: Path) -> dict:
    return load_json(path)


def index(rows: list[dict], key: str, collection: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f"{collection}: every item must be an object with {key}")
        item_id = item[key]
        if item_id in indexed:
            raise ValueError(f"{collection}: duplicate {key} {item_id}")
        indexed[item_id] = item
    return indexed


def compact(item: dict) -> str:
    for key in ("statement", "signal", "description", "name", "title", "trigger", "perspective", "dimension", "url"):
        if item.get(key):
            return str(item[key])
    return item.get("id", "")


def changed_fields(before: dict, after: dict) -> list[str]:
    return sorted(
        key
        for key in set(before) | set(after)
        if key not in before or key not in after or before[key] != after[key]
    )


def validate_snapshot(data: dict, label: str) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{label}: snapshot root must be an object")
    schema = load_json(SCHEMA_PATH)
    schema_errors = [
        message
        for message in schema_validate(data, schema)
        if not message.startswith("WARNING:")
    ]
    semantic_errors, _ = semantic_validate(data)
    errors = schema_errors + semantic_errors
    if errors:
        preview = "; ".join(errors[:5])
        suffix = f"; plus {len(errors) - 5} more" if len(errors) > 5 else ""
        raise ValueError(f"{label}: invalid research snapshot: {preview}{suffix}")


def compare(old: dict, new: dict) -> dict:
    validate_snapshot(old, "old")
    validate_snapshot(new, "new")
    result = {"generated_at": new.get("meta", {}).get("generated_at"), "old_title": old.get("meta", {}).get("title"), "new_title": new.get("meta", {}).get("title"), "collections": {}}
    for collection, identity_key in COLLECTION_KEYS.items():
        before = index(old.get(collection, []), identity_key, f"old.{collection}")
        after = index(new.get(collection, []), identity_key, f"new.{collection}")
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        material_changed = []
        metadata_changed = []
        for item_id in sorted(set(before) & set(after)):
            fields = changed_fields(before[item_id], after[item_id])
            if not fields:
                continue
            row = {"id": item_id, "before": compact(before[item_id]), "after": compact(after[item_id]), "changed_fields": fields}
            metadata_fields = METADATA_FIELDS_BY_COLLECTION.get(collection, set())
            if metadata_fields and all(field in metadata_fields for field in fields):
                metadata_changed.append(row)
            else:
                material_changed.append(row)
        result["collections"][collection] = {
            "added": [{"id": item_id, "summary": compact(after[item_id])} for item_id in added],
            "removed": [{"id": item_id, "summary": compact(before[item_id])} for item_id in removed],
            "changed": material_changed,
            "metadata_only_changed": metadata_changed,
        }
    result["research_status_changed"] = old.get("meta", {}).get("research_status") != new.get("meta", {}).get("research_status")
    result["limitations_changed"] = old.get("limitations", []) != new.get("limitations", [])
    result["top_level_changed"] = {
        field: old.get(field) != new.get(field)
        for field in (
            "scope", "intake", "identity_resolution", "investment_context",
            "investment_conclusion", "income_analysis", "decision_audit",
            "key_unknowns", "limitations",
        )
    }
    known_top_level = set(COLLECTION_KEYS) | {
        "meta", "scope", "intake", "identity_resolution", "investment_context",
        "investment_conclusion", "income_analysis", "decision_audit",
        "key_unknowns", "limitations"
    }
    result["extension_top_level_changed"] = {
        field: {
            "before_present": field in old,
            "after_present": field in new,
            "before": old.get(field),
            "after": new.get(field),
        }
        for field in sorted((set(old) | set(new)) - known_top_level)
        if field not in old or field not in new or old[field] != new[field]
    }
    meta_fields = changed_fields(old.get("meta", {}), new.get("meta", {}))
    result["meta_changed_fields"] = [field for field in meta_fields if field not in META_METADATA_FIELDS]
    result["meta_metadata_only_changed_fields"] = [field for field in meta_fields if field in META_METADATA_FIELDS]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(load(args.old), load(args.new))
    except ValueError as exc:
        raise SystemExit(f"snapshot diff rejected invalid input: {exc}") from exc
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "collections": len(result["collections"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
