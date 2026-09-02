#!/usr/bin/env python3
"""Evaluate monitoring_plan[] against a point-in-time observation JSON."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def evaluate(rule: dict, current: float, baseline: float | None) -> tuple[bool | None, str]:
    op, threshold = rule["operator"], float(rule["threshold"])
    if not math.isfinite(current) or not math.isfinite(threshold):
        return None, "current value and threshold must be finite numbers"
    if op == "gt": return current > threshold, f"{current} > {threshold}"
    if op == "gte": return current >= threshold, f"{current} >= {threshold}"
    if op == "lt": return current < threshold, f"{current} < {threshold}"
    if op == "lte": return current <= threshold, f"{current} <= {threshold}"
    if op == "eq": return current == threshold, f"{current} == {threshold}"
    if baseline is None or baseline == 0:
        return None, "变化率规则缺少非零数值基线"
    change = (current - baseline) / abs(baseline)
    if not math.isfinite(change):
        return None, "calculated change is not finite"
    if op == "change_pct_gte": return change >= threshold, f"change={change:.4f} >= {threshold}"
    if op == "change_pct_lte": return change <= threshold, f"change={change:.4f} <= {threshold}"
    return None, f"不支持的规则 {op}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path, help="research JSON containing monitoring_plan")
    parser.add_argument("observations", type=Path, help="JSON map of indicator to current value")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reject_constant = lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON value is forbidden: {value}"))
    research = json.loads(args.plan.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    observed = json.loads(args.observations.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    events = []
    for item in research.get("monitoring_plan", []):
        if item.get("status") in {"paused", "blocked"}:
            events.append({
                "id": item["id"],
                "status": "skipped",
                "indicator": item.get("indicator"),
                "triggered": None,
                "action": "monitor is paused or blocked; no trigger was evaluated",
                "requires_human_check": False,
            })
            continue
        rule = item.get("evaluation")
        key = rule.get("observation_key") if rule else item.get("indicator")
        if key not in observed:
            events.append({"id": item["id"], "status": "no_observation", "indicator": key, "action": "等待下一次采集，不解释为无变化。"})
            continue
        if rule and isinstance(observed[key], (int, float)) and not isinstance(observed[key], bool):
            baseline = item.get("baseline") if isinstance(item.get("baseline"), (int, float)) else None
            triggered, calculation = evaluate(rule, float(observed[key]), baseline)
            events.append({"id": item["id"], "status": "evaluated" if triggered is not None else "manual_required", "indicator": key, "value": observed[key], "triggered": triggered, "calculation": calculation, "action": item["action_if_triggered"] if triggered else "继续观察", "requires_human_check": triggered is not False})
        else:
            events.append({"id": item["id"], "status": "observed", "indicator": key, "value": observed[key], "trigger_rule": item["trigger"], "action": item["action_if_triggered"], "requires_human_check": True})
    output = {"evaluated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"), "events": events, "limitations": ["含 evaluation 的数值规则可自动计算是否触发；未结构化规则只提示复查。触发结果仍不等于企业经营结论。"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "events": len(events)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
