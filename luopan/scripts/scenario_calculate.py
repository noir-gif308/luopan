#!/usr/bin/env python3
"""Calculate transparent lower/base/upper scenario ranges.

Input format:
{
  "scenario_id": "scn-...",
  "evidence_ids": ["met-..."],
  "assumptions": [
    {"metric": "收入", "baseline": 100, "shock": {"lower": -0.1, "base": -0.2, "upper": -0.35}, "unit": "亿元", "direction": "relative"}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def calc(item: dict) -> dict:
    direction = item.get("direction", "relative")
    if direction not in {"relative", "absolute"}:
        raise ValueError(f"unsupported scenario direction: {direction!r}")
    raw_baseline = item["baseline"]
    if not isinstance(raw_baseline, (int, float)) or isinstance(raw_baseline, bool):
        raise ValueError("scenario baseline must be a JSON number")
    baseline = float(raw_baseline)
    if not math.isfinite(baseline):
        raise ValueError("scenario baseline must be finite")
    shock = item["shock"]
    values = {}
    normalized_shock = {}
    for name in ("lower", "base", "upper"):
        raw_delta = shock[name]
        if not isinstance(raw_delta, (int, float)) or isinstance(raw_delta, bool):
            raise ValueError(f"scenario shock {name} must be a JSON number")
        delta = float(raw_delta)
        if not math.isfinite(delta):
            raise ValueError(f"scenario shock {name} must be finite")
        value = baseline * (1 + delta) if direction == "relative" else baseline + delta
        if not math.isfinite(value):
            raise ValueError(f"scenario result {name} is not finite")
        values[name] = round(value, 10)
        normalized_shock[name] = delta
    return {
        "metric": item["metric"],
        "baseline": baseline,
        "lower_bound": min(values.values()),
        "base_case": values["base"],
        "upper_bound": max(values.values()),
        "unit": item.get("unit", "未注明"),
        "shock_assumption": normalized_shock,
        "direction": direction,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(
        args.input.read_text(encoding="utf-8-sig"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value is forbidden: {value}")
        ),
    )
    default_evidence_ids = payload.get("evidence_ids", [])
    assumptions = payload.get("assumptions", [])
    if not isinstance(assumptions, list) or not assumptions:
        raise SystemExit("scenario input requires at least one assumption")
    if not default_evidence_ids and not all(item.get("evidence_ids") for item in assumptions):
        raise SystemExit("scenario input requires evidence_ids at top level or on every assumption")
    results = []
    for index, item in enumerate(assumptions, 1):
        try:
            row = calc(item)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SystemExit(f"invalid scenario assumption {index}: {exc}") from exc
        row["id"] = f"sres-{payload['scenario_id'].removeprefix('scn-')}-{index:03d}"
        row["scenario_id"] = payload["scenario_id"]
        row["formula"] = "baseline * (1 + shock)" if item.get("direction", "relative") == "relative" else "baseline + shock"
        row["assumptions"] = [f"{item['metric']} 的基线={item['baseline']}", f"下/中/上冲击={item['shock']['lower']}/{item['shock']['base']}/{item['shock']['upper']}"]
        row["evidence_ids"] = item.get("evidence_ids") or default_evidence_ids
        results.append(row)
    output = {
        "scenario_results": results,
        "limitations": ["这是敏感性区间，不是企业实际预测；输入基线和冲击假设必须由来源或用户明确提供。"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "scenario_id": payload["scenario_id"], "metrics": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
