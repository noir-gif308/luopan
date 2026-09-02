#!/usr/bin/env python3
"""Verify Luopan's dedicated runtime and release regressions."""

from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

from validate_research import load_json, schema_validate


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    expected = {}
    for line in (root / "requirements-runtime.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_-]+)(?:\[[^]]+\])?==([^\s]+)", line.strip())
        if match:
            expected[match.group(1).lower()] = match.group(2)

    packages = {"yaml": "PyYAML", "jsonschema": "jsonschema", "markdown": "Markdown"}
    problems = []
    for module, distribution in packages.items():
        try:
            __import__(module)
        except ImportError:
            problems.append(f"{distribution} is missing")
            continue
        installed = importlib.metadata.version(distribution)
        wanted = expected.get(distribution.lower())
        if wanted and installed != wanted:
            problems.append(f"{distribution} {installed} is installed; expected {wanted}")
    if problems:
        print("FAILED: " + "; ".join(problems))
        return 1

    import markdown
    import yaml

    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"FAILED: invalid VERSION value {version!r}")
        return 1
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8-sig")
    if f"# 罗盘 v{version}" not in skill_text:
        print("FAILED: SKILL.md display version differs from VERSION")
        return 1
    agent_metadata = yaml.safe_load((root / "agents" / "openai.yaml").read_text(encoding="utf-8-sig"))
    if agent_metadata.get("interface", {}).get("display_name") != f"罗盘 v{version}":
        print("FAILED: agents/openai.yaml display version differs from VERSION")
        return 1
    intake_text = (root / "references" / "research-intake.md").read_text(encoding="utf-8-sig")
    intake_contract = (
        "访谈循环",
        "研究就绪门",
        "用户推测/怀疑",
        "后续每轮最多 3 个问题",
        "连续两轮回答没有新增",
        "必须阻断",
    )
    missing_intake_rules = [rule for rule in intake_contract if rule not in intake_text]
    if missing_intake_rules or "开始任何搜索、抓取或结论写作前" not in skill_text:
        print("FAILED: adaptive intake contract is incomplete: " + ", ".join(missing_intake_rules))
        return 1
    investment_text = (root / "references" / "investment-view.md").read_text(encoding="utf-8-sig")
    investment_contract = (
        "投资访谈门",
        "统一证据底座",
        "三情景估值",
        "条件式结论",
        "失败关闭",
    )
    missing_investment_rules = [rule for rule in investment_contract if rule not in investment_text]
    if missing_investment_rules or "references/investment-view.md" not in skill_text:
        print("FAILED: investment-view contract is incomplete: " + ", ".join(missing_investment_rules))
        return 1
    decision_text = (root / "references" / "decision-audit.md").read_text(encoding="utf-8-sig")
    decision_contract = (
        "六道门",
        "user_answer_indices",
        "conditions[]",
        "stage: add_position",
        "不得解释为允许加仓",
    )
    missing_decision_rules = [rule for rule in decision_contract if rule not in decision_text]
    if missing_decision_rules or "references/decision-audit.md" not in skill_text:
        print("FAILED: decision-audit contract is incomplete: " + ", ".join(missing_decision_rules))
        return 1
    referenced_docs = set(re.findall(r"references/([A-Za-z0-9-]+\.md)", skill_text))
    bundled_docs = {path.name for path in (root / "references").glob("*.md")}
    if referenced_docs != bundled_docs:
        print(
            "FAILED: reference routing mismatch; missing="
            + ",".join(sorted(referenced_docs - bundled_docs))
            + "; unlinked="
            + ",".join(sorted(bundled_docs - referenced_docs))
        )
        return 1
    if not (root / "scripts" / "investment_calculate.py").is_file():
        print("FAILED: investment calculator is missing")
        return 1
    from collection_common import USER_AGENT

    if f"LuopanResearch/{version}" not in USER_AGENT:
        print("FAILED: runtime user-agent version differs from VERSION")
        return 1

    if yaml.safe_load("name: luopan\n").get("name") != "luopan":
        print("FAILED: PyYAML behavior check failed")
        return 1
    rendered = markdown.markdown("| A | B |\n| - | - |\n| 1 | 2 |", extensions=["tables"])
    if "<table>" not in rendered or "<td>1</td>" not in rendered:
        print("FAILED: Markdown table rendering check failed")
        return 1

    schema = load_json(root / "research.schema.json")
    required_meta = set(schema["properties"]["meta"]["required"])
    if not {"research_purpose", "analysis_lenses", "information_regime"}.issubset(required_meta):
        print("FAILED: explicit routing fields are not required by the schema")
        return 1
    if "compare" in schema["properties"]["meta"]["properties"]["mode"]["enum"]:
        print("FAILED: compare mode must not be advertised before its structured contract exists")
        return 1
    data = load_json(root / "examples" / "invalid-date-format.json")
    errors = schema_validate(data, schema)
    if not any("generated_at" in item and "date-time" in item for item in errors):
        print("FAILED: JSON Schema format checker did not reject invalid generated_at")
        return 1
    positive_errors = schema_validate(load_json(root / "examples" / "deep-synthetic.json"), schema)
    if any(item.startswith("SCHEMA ") for item in positive_errors):
        print("FAILED: valid deep example failed JSON Schema validation")
        return 1
    investment_errors = schema_validate(load_json(root / "examples" / "investment-synthetic.json"), schema)
    if any(item.startswith("SCHEMA ") for item in investment_errors):
        print("FAILED: valid investment example failed JSON Schema validation")
        return 1

    for script_name in ("regression_suite.py", "security_regression.py"):
        child_env = dict(os.environ)
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / script_name)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            check=False,
        )
        if result.returncode:
            print(f"FAILED: {script_name} returned {result.returncode}")
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip())
            return 1
    print(f"Runtime smoke OK on Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
