#!/usr/bin/env python3
"""Score scenario ranges against later observed values."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_results", type=Path)
    parser.add_argument("actuals", type=Path, help="JSON map of scenario_result_id to actual value")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reject_constant = lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON value is forbidden: {value}"))
    payload = json.loads(args.scenario_results.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    rows = payload.get("scenario_results", payload.get("results", []))
    actuals = json.loads(args.actuals.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    scores = []
    seen_ids = set()
    for index, row in enumerate(rows, 1):
        row_id = row.get("id")
        if not row_id:
            scores.append({"id": None, "row": index, "status": "invalid_result", "reason": "missing id"})
            continue
        if row_id in seen_ids:
            scores.append({"id": row_id, "status": "invalid_result", "reason": "duplicate id"})
            continue
        seen_ids.add(row_id)
        if row_id not in actuals:
            scores.append({"id": row_id, "status": "missing_actual"})
            continue
        try:
            actual = float(actuals[row_id])
            base = float(row["base_case"])
            lower, upper = float(row["lower_bound"]), float(row["upper_bound"])
            if not all(math.isfinite(value) for value in (actual, base, lower, upper)):
                raise ValueError("actual and scenario bounds must be finite")
            if not lower <= base <= upper:
                raise ValueError("scenario bounds must satisfy lower_bound <= base_case <= upper_bound")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            scores.append({"id": row_id, "status": "invalid_actual", "reason": str(exc)})
            continue
        error = actual - base
        pct_error = None if actual == 0 else abs(error) / abs(actual)
        if not math.isfinite(error) or (pct_error is not None and not math.isfinite(pct_error)):
            scores.append({
                "id": row_id,
                "status": "invalid_actual",
                "reason": "derived backtest error is not finite",
            })
            continue
        scores.append({"id": row_id, "status": "scored", "actual": actual, "within_interval": lower <= actual <= upper, "absolute_error": abs(error), "absolute_pct_error": pct_error})
    scored = [row for row in scores if row["status"] == "scored"]
    summary = {
        "scored": len(scored),
        "interval_coverage": sum(row["within_interval"] for row in scored) / len(scored) if scored else None,
        "mean_absolute_pct_error": sum(row["absolute_pct_error"] for row in scored if row["absolute_pct_error"] is not None) / sum(row["absolute_pct_error"] is not None for row in scored) if any(row.get("absolute_pct_error") is not None for row in scored) else None,
    }
    output = {"summary": summary, "scores": scores, "limitations": ["回测只评价历史区间覆盖与基准误差；样本少时不能证明预测能力。"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
