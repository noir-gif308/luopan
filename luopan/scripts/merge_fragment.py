#!/usr/bin/env python3
"""Merge a generated fragment into research.json by collection key.

This is intentionally explicit: only known collections and singleton analysis
objects are merged, so a provider cannot silently overwrite metadata.
"""

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
STRING_COLLECTIONS = {"key_unknowns", "limitations"}
SINGLETONS = {
    "identity_resolution", "investment_context", "investment_conclusion",
    "income_analysis", "decision_audit",
}
METADATA_KEYS = {"generated_at"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("research", type=Path)
    parser.add_argument("fragment", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replace", action="store_true", help="replace matching collection keys instead of append-only")
    args = parser.parse_args()
    research = load_json(args.research)
    fragment = load_json(args.fragment)
    if not isinstance(fragment, dict):
        raise SystemExit("fragment root must be an object")
    unknown = sorted(
        set(fragment) - set(COLLECTION_KEYS) - STRING_COLLECTIONS - SINGLETONS - METADATA_KEYS
    )
    if unknown:
        raise SystemExit(f"fragment contains unknown collection(s): {', '.join(unknown)}")
    changed = []
    for key, values in fragment.items():
        if key in METADATA_KEYS:
            continue
        if key in SINGLETONS:
            if not isinstance(values, dict):
                raise SystemExit(f"{key}: fragment singleton must be an object")
            if research.get(key) is not None and not args.replace:
                raise SystemExit(f"{key}: singleton already exists; use --replace only after review")
            research[key] = values
            changed.append(key)
            continue
        if not isinstance(values, list):
            raise SystemExit(f"{key}: fragment collection must be an array")
        existing = research.setdefault(key, [])
        if not isinstance(existing, list):
            raise SystemExit(f"{key}: research collection must be an array")
        if key in STRING_COLLECTIONS:
            if not all(isinstance(value, str) and value.strip() for value in values):
                raise SystemExit(f"{key}: every fragment item must be a non-empty string")
            for value in values:
                if value not in existing:
                    existing.append(value)
            changed.append(key)
            continue
        identity_key = COLLECTION_KEYS[key]
        by_id: dict[str, dict] = {}
        for item in existing:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get(identity_key), str)
                or not item[identity_key].strip()
            ):
                raise SystemExit(
                    f"{key}: existing research item must be an object with {identity_key}"
                )
            item_id = item[identity_key]
            if item_id in by_id:
                raise SystemExit(f"{key}: existing research contains duplicate id {item_id}")
            by_id[item_id] = item
        fragment_ids: set[str] = set()
        for item in values:
            if not isinstance(item, dict):
                raise SystemExit(f"{key}: every fragment item must be an object")
            item_id = item.get(identity_key)
            if not isinstance(item_id, str) or not item_id.strip():
                raise SystemExit(f"{key}: fragment item has no {identity_key}")
            if item_id in fragment_ids:
                raise SystemExit(f"{key}: fragment contains duplicate id {item_id}")
            fragment_ids.add(item_id)
            if item_id in by_id and not args.replace:
                raise SystemExit(f"{key}: duplicate id {item_id}; use --replace only after review")
            by_id[item_id] = item
        research[key] = list(by_id.values())
        changed.append(key)

    schema_path = Path(__file__).resolve().parents[1] / "research.schema.json"
    schema_messages = schema_validate(research, load_json(schema_path))
    errors = [message for message in schema_messages if not message.startswith("WARNING:")]
    semantic_errors, _ = semantic_validate(research)
    errors.extend(semantic_errors)
    if errors:
        preview = "\n".join(f"- {item}" for item in errors[:20])
        raise SystemExit(f"merged research failed validation with {len(errors)} error(s):\n{preview}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(research, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
