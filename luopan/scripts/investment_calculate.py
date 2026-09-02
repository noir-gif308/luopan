#!/usr/bin/env python3
"""Calculate transparent investment scenario returns with Decimal arithmetic."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


CASES = ("downside", "base", "upside")
RETURN_QUANTUM = Decimal("0.000000000001")


def load_payload(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        parse_float=Decimal,
        parse_int=Decimal,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value is forbidden: {value}")
        ),
    )


def positive_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive JSON number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a positive JSON number") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be a positive finite JSON number")
    return result


def nonnegative_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative JSON number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a non-negative JSON number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be a non-negative finite JSON number")
    return result


def json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return json_number(value)
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def calculate(payload: dict) -> list[dict]:
    reference = positive_decimal(payload.get("reference_value"), "reference_value")
    years = positive_decimal(payload.get("horizon_years"), "horizon_years")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 3:
        raise ValueError("scenarios must contain exactly downside, base, and upside")
    by_case = {item.get("case"): item for item in scenarios if isinstance(item, dict)}
    if set(by_case) != set(CASES) or len(by_case) != 3:
        raise ValueError("scenarios must contain one unique downside, base, and upside case")

    targets = {
        case: nonnegative_decimal(by_case[case].get("target_value"), f"{case}.target_value")
        for case in CASES
    }
    if not targets["downside"] <= targets["base"] <= targets["upside"]:
        raise ValueError("target values must satisfy downside <= base <= upside")

    rows = []
    with localcontext() as context:
        context.prec = 40
        for case in CASES:
            item = dict(by_case[case])
            target = targets[case]
            total_return = target / reference - Decimal(1)
            annual_return = (
                Decimal(-1)
                if target == 0
                else ((target / reference).ln() / years).exp() - Decimal(1)
            )
            item.update({
                "valuation_as_of": payload["valuation_as_of"],
                "horizon_years": json_number(years),
                "value_type": payload["reference_value_type"],
                "target_value": json_number(target),
                "currency": payload["currency"],
                "expected_total_return": json_number(total_return.quantize(RETURN_QUANTUM)),
                "expected_annual_return": json_number(annual_return.quantize(RETURN_QUANTUM)),
            })
            rows.append(json_safe(item))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = load_payload(args.input)
        rows = calculate(payload)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as exc:
        raise SystemExit(f"invalid investment scenario input: {exc}") from exc
    output = {
        "valuation_scenarios": rows,
        "limitations": [
            "回报只由参考值、目标值和持有期计算；估值方法与业务假设仍需独立证据和反证。"
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps({"out": str(args.out.resolve()), "scenarios": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
