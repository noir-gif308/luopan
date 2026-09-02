#!/usr/bin/env python3
"""Validate Luopan's SKILL.md frontmatter without external YAML packages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ALLOWED = {"name", "description"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    path = args.skill / "SKILL.md"
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not match:
        raise SystemExit("SKILL.md has no valid frontmatter block")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            raise SystemExit(f"invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if key in fields:
            raise SystemExit(f"duplicate frontmatter key: {key}")
        fields[key] = value.strip()

    unexpected = sorted(set(fields) - ALLOWED)
    if unexpected:
        raise SystemExit(f"unexpected frontmatter keys: {', '.join(unexpected)}")
    missing = sorted(ALLOWED - set(fields))
    if missing:
        raise SystemExit(f"missing frontmatter keys: {', '.join(missing)}")
    name = fields.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise SystemExit("name must be lowercase hyphen-case and at most 64 characters")
    description = fields.get("description", "")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        raise SystemExit("description is missing or invalid")
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
