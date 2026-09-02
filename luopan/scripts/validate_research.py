#!/usr/bin/env python3
"""Validate Luopan research JSON with schema and semantic integrity checks."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit


COLLECTIONS = (
    "sources",
    "evidence",
    "source_health",
    "relationship_edges",
    "proxy_estimates",
    "investment_theses",
    "valuation_scenarios",
    "period_reviews",
    "management_commitments",
    "capital_allocation_events",
    "thesis_changes",
    "bottleneck_nodes",
    "entities",
    "products",
    "supply_chain_nodes",
    "external_signals",
    "exposure_links",
    "metrics",
    "experience_signals",
    "rd_signals",
    "product_markets",
    "customer_segments",
    "competitors",
    "business_model_links",
    "organization_signals",
    "observations",
    "narrative_risks",
    "intelligence_items",
    "scenarios",
    "monitoring_plan",
    "scenario_results",
    "claims",
    "opportunities",
)


def load_json(path: Path) -> dict:
    # PowerShell commonly writes UTF-8 BOM; accept it without weakening JSON checks.
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(
            handle,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard numeric constant is forbidden: {value}")
            ),
        )


def numeric_tokens(value: str) -> list[Decimal]:
    normalized = value.replace("−", "-").replace("–", "-")
    pattern = r"(?<![0-9.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![0-9.])"
    tokens: list[Decimal] = []
    for match in re.finditer(pattern, normalized):
        try:
            tokens.append(Decimal(match.group(0).replace(",", "")))
        except InvalidOperation:
            continue
    return tokens


def canonical_source_url(value: str) -> str:
    """Normalize a web URL for source-independence comparisons."""
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return value.strip()
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return value.strip()
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    tracking_prefixes = ("utm_",)
    tracking_names = {"fbclid", "gclid", "yclid"}
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in tracking_names
            and not any(key.lower().startswith(prefix) for prefix in tracking_prefixes)
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def normalized_excerpt(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def schema_validate(data: dict, schema: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["SCHEMA <runtime>: jsonschema is required; schema validation cannot fail open"]

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"SCHEMA {location}: {error.message}")
    return errors


def semantic_validate(data: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    objects: dict[str, dict] = {}

    if not isinstance(data, dict):
        return ["research root must be an object"], warnings

    object_arrays = (
        *COLLECTIONS,
        "source_coverage",
        "footprint_coverage",
        "discarded_sources",
    )
    malformed = False
    for field in object_arrays:
        rows = data.get(field, [])
        if not isinstance(rows, list):
            errors.append(f"{field}: must be an array")
            malformed = True
        elif any(not isinstance(item, dict) for item in rows):
            errors.append(f"{field}: every item must be an object")
            malformed = True
    for field in ("limitations", "key_unknowns"):
        if field in data and not isinstance(data[field], list):
            errors.append(f"{field}: must be an array")
            malformed = True
    for field in (
        "meta", "scope", "intake", "identity_resolution",
        "investment_context", "investment_conclusion", "income_analysis", "decision_audit",
    ):
        if field in data and data[field] is not None and not isinstance(data[field], dict):
            errors.append(f"{field}: must be an object")
            malformed = True
    if malformed:
        return errors, warnings

    def check_finite(value: object, path: str = "<root>") -> None:
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f"{path}: non-finite number is forbidden")
        elif isinstance(value, dict):
            for key, nested in value.items():
                check_finite(nested, f"{path}.{key}" if path != "<root>" else str(key))
        elif isinstance(value, list):
            for number, nested in enumerate(value):
                check_finite(nested, f"{path}[{number}]")

    check_finite(data)

    for collection in COLLECTIONS:
        for item in data.get(collection, []):
            item_id = item.get("id")
            if not item_id:
                errors.append(f"{collection}: item has no id")
                continue
            if item_id in objects:
                errors.append(f"duplicate id: {item_id}")
            objects[item_id] = item

    source_ids = {item.get("id") for item in data.get("sources", [])}
    evidence_ids = {item.get("id") for item in data.get("evidence", [])}
    entity_ids = {item.get("id") for item in data.get("entities", [])}
    product_ids = {item.get("id") for item in data.get("products", [])}
    metric_ids = {item.get("id") for item in data.get("metrics", [])}
    signal_ids = {
        item.get("id")
        for collection in ("experience_signals", "rd_signals")
        for item in data.get(collection, [])
    }
    claim_evidence_ids = source_ids | evidence_ids | metric_ids | signal_ids
    customer_ids = {item.get("id") for item in data.get("customer_segments", [])}
    supply_node_ids = {item.get("id") for item in data.get("supply_chain_nodes", [])}
    external_signal_ids = {item.get("id") for item in data.get("external_signals", [])}
    external_context_types = {"trade_flow", "shipping", "commodity", "sanctions", "infrastructure", "market_data", "event_data"}
    sources_by_id = {item.get("id"): item for item in data.get("sources", [])}

    def atomic_evidence_ids_for_ref(ref: str, seen: set[str] | None = None) -> set[str]:
        seen = set(seen or ())
        if ref in seen:
            return set()
        seen.add(ref)
        if ref in evidence_ids:
            return {ref}
        if ref not in metric_ids | signal_ids:
            return set()
        result: set[str] = set()
        for nested_ref in objects.get(ref, {}).get("evidence_ids", []):
            result.update(atomic_evidence_ids_for_ref(nested_ref, seen))
        return result

    def atomic_source_ids_for_ref(ref: str) -> set[str]:
        if ref in source_ids:
            return {ref}
        return {
            objects[evidence_id].get("source_id")
            for evidence_id in atomic_evidence_ids_for_ref(ref)
            if objects.get(evidence_id, {}).get("source_id") in source_ids
        }

    def atomic_evidence_for_refs(refs: list[str]) -> list[dict]:
        atomic_ids = {
            evidence_id
            for ref in refs
            for evidence_id in atomic_evidence_ids_for_ref(ref)
        }
        return [objects[evidence_id] for evidence_id in sorted(atomic_ids) if evidence_id in objects]

    def evidence_fingerprints(refs: list[str]) -> set[tuple[str, str]]:
        return {
            (
                str(item.get("source_id") or ""),
                normalized_excerpt(item.get("excerpt")).casefold(),
            )
            for item in atomic_evidence_for_refs(refs)
        }

    def cited_excerpts(refs: list[str]) -> str:
        return " ".join(
            normalized_excerpt(item.get("excerpt"))
            for item in atomic_evidence_for_refs(refs)
        )

    def source_dates_for_refs(refs: list[str]) -> list[tuple[str, str]]:
        rows = []
        for item in atomic_evidence_for_refs(refs):
            source = sources_by_id.get(item.get("source_id"), {})
            published = str(source.get("published_at") or "")[:10]
            rows.append((item.get("id", "<unknown>"), published))
        return rows

    def numeric_value_is_present(value: object, excerpts: str, percentage: bool = False) -> bool:
        try:
            expected = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return True
        tokens = numeric_tokens(excerpts)
        if expected in tokens:
            return True
        return percentage and "%" in excerpts and expected * Decimal("100") in tokens

    def period_is_present(period: object, excerpts: str) -> bool:
        period_text = normalized_excerpt(period)
        years = re.findall(r"(?:19|20)\d{2}", period_text)
        if years:
            return all(year in excerpts for year in years)
        return bool(period_text and period_text.casefold() in excerpts.casefold())

    def exact_date_is_present(value: object, excerpts: str) -> bool:
        try:
            expected = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return False
        compact_excerpt = re.sub(r"\s+", "", excerpts).casefold()
        numeric_candidates = {
            expected.isoformat(),
            f"{expected.year}/{expected.month:02d}/{expected.day:02d}",
            f"{expected.year}/{expected.month}/{expected.day}",
            f"{expected.year}.{expected.month:02d}.{expected.day:02d}",
            f"{expected.year}.{expected.month}.{expected.day}",
            f"{expected.year}年{expected.month:02d}月{expected.day:02d}日",
            f"{expected.year}年{expected.month}月{expected.day}日",
        }
        if any(candidate.casefold() in compact_excerpt for candidate in numeric_candidates):
            return True
        month_names = (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        )
        month = month_names[expected.month - 1]
        month_pattern = rf"(?:{month}|{month[:3]}\.?)"
        day = expected.day
        english_patterns = (
            rf"\b{month_pattern}\s+0?{day}(?:st|nd|rd|th)?\s*,?\s*{expected.year}\b",
            rf"\b0?{day}(?:st|nd|rd|th)?\s+{month_pattern}\s*,?\s*{expected.year}\b",
        )
        return any(re.search(pattern, excerpts, re.IGNORECASE) for pattern in english_patterns)

    def validate_period_value(
        owner: str,
        value: object,
        unit: object,
        period: object,
        refs: list[str],
    ) -> None:
        excerpts = cited_excerpts(refs)
        if not numeric_value_is_present(value, excerpts):
            errors.append(f"{owner}: numeric value {value} is absent from cited evidence excerpts")
        unit_text = normalized_excerpt(unit)
        if unit_text and unit_text not in excerpts:
            errors.append(f"{owner}: unit {unit_text!r} is absent from cited evidence excerpts")
        if not period_is_present(period, excerpts):
            errors.append(f"{owner}: period {period!r} is absent from cited evidence excerpts")

    def enforce_trusted_evidence(owner: str, item: dict, refs: list[str]) -> None:
        enforce_derived_source_quality(owner, item, refs)
        atomic_items = atomic_evidence_for_refs(refs)
        if not atomic_items:
            errors.append(f"{owner}: requires atomic evidence")
            return
        rumor_ids = sorted(
            item.get("id", "<unknown>")
            for item in atomic_items
            if item.get("evidence_kind") == "rumor"
        )
        if rumor_ids:
            errors.append(f"{owner}: rumor evidence cannot support this structured result: " + ", ".join(rumor_ids))
        untrusted_sources = sorted({
            item.get("source_id")
            for item in atomic_items
            if sources_by_id.get(item.get("source_id"), {}).get("verification")
            not in {"verified", "corroborated"}
        })
        if untrusted_sources:
            errors.append(f"{owner}: requires verified or corroborated sources: " + ", ".join(untrusted_sources))

    def evidence_is_external_context(evidence_id: str) -> bool:
        evidence = objects.get(evidence_id, {})
        source = sources_by_id.get(evidence.get("source_id"), {})
        return (
            source.get("evidence_type") in external_context_types
            or "aggregated_feed" in evidence.get("quality_flags", [])
        )

    def ref_has_enterprise_evidence(ref: str, target_ids: set[str]) -> bool:
        atomic_ids = atomic_evidence_ids_for_ref(ref)
        return any(
            not evidence_is_external_context(evidence_id)
            and sources_by_id.get(objects.get(evidence_id, {}).get("source_id"), {}).get("verification") != "discovery_only"
            and bool(set(objects.get(evidence_id, {}).get("subject_ids", [])) & target_ids)
            for evidence_id in atomic_ids
        )

    def enforce_derived_source_quality(
        owner: str,
        item: dict,
        refs: list[str],
    ) -> None:
        """Keep ordinary structured facts from bypassing claim-level source gates."""
        direct_sources = sorted(ref for ref in refs if ref in source_ids)
        if direct_sources:
            errors.append(
                f"{owner}: must cite atomic evidence or a derived metric/signal, not source records: "
                + ", ".join(direct_sources)
            )
        atomic_ids = {
            evidence_id
            for ref in refs
            for evidence_id in atomic_evidence_ids_for_ref(ref)
        }
        if refs and not atomic_ids:
            errors.append(f"{owner}: evidence references do not resolve to atomic evidence")
            return
        supporting_sources = {
            objects.get(evidence_id, {}).get("source_id")
            for evidence_id in atomic_ids
            if objects.get(evidence_id, {}).get("source_id") in source_ids
        }
        discovery_sources = sorted(
            source_id
            for source_id in supporting_sources
            if sources_by_id.get(source_id, {}).get("verification") == "discovery_only"
        )
        if discovery_sources:
            errors.append(
                f"{owner}: discovery-only sources cannot support structured facts: "
                + ", ".join(discovery_sources)
            )
        if item.get("confidence") == "high":
            if not any(
                objects.get(evidence_id, {}).get("stance") == "supports"
                for evidence_id in atomic_ids
            ):
                errors.append(
                    f"{owner}: high-confidence structured fact requires supporting atomic evidence"
                )
            untrusted_sources = sorted(
                source_id
                for source_id in supporting_sources
                if sources_by_id.get(source_id, {}).get("verification")
                not in {"verified", "corroborated"}
            )
            if not supporting_sources or untrusted_sources:
                errors.append(
                    f"{owner}: high-confidence structured fact requires only verified or corroborated sources"
                )

    intake = data.get("intake")
    if not intake:
        warnings.append("intake is missing; report may hide user questions or default assumptions")
    elif intake.get("interaction_mode") == "defaults_disclosed" and not intake.get("assumptions"):
        errors.append("intake defaults_disclosed requires non-empty assumptions")

    for field in ("subject", "geography", "timeframe", "decision_question"):
        if not str(data.get("scope", {}).get(field) or "").strip():
            errors.append(f"scope.{field} must be non-empty")

    research_status = data.get("meta", {}).get("research_status")
    if not research_status:
        errors.append("meta.research_status is required for every research mode")
    elif research_status == "blocked":
        if not data.get("key_unknowns"):
            errors.append("blocked research requires non-empty key_unknowns")
        if not data.get("limitations"):
            errors.append("blocked research requires non-empty limitations")
    else:
        for section in ("sources", "evidence", "claims"):
            if not data.get(section):
                errors.append(f"non-blocked research requires non-empty {section}")
    if research_status == "complete" and data.get("meta", {}).get("verification_mode") == "none":
        errors.append("complete research requires self_review or independent verification")

    def check_refs(owner: str, refs: list[str], allowed: set[str] | None = None) -> None:
        for ref in refs:
            if ref == owner:
                errors.append(f"{owner}: self-reference is forbidden")
                continue
            if ref not in objects:
                errors.append(f"{owner}: missing reference {ref}")
            elif allowed is not None and ref not in allowed:
                errors.append(f"{owner}: invalid reference type {ref}")

    for source in data.get("sources", []):
        source_id = source.get("id", "<unknown>")
        url = source.get("url", "")
        parsed = urlparse(url)
        is_web_url = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and parsed.username is None
            and parsed.password is None
        )
        is_local_urn = parsed.scheme == "urn" and parsed.path.startswith("luopan:")
        if not (is_web_url or is_local_urn):
            errors.append(f"{source_id}: invalid source URL")
        if source.get("verification") == "verified" and not str(source.get("excerpt") or "").strip():
            errors.append(f"{source_id}: verified source requires an excerpt")
        if source.get("authority") == "primary" and source.get("evidence_type") in {"research", "media", "estimate", "rumor"}:
            errors.append(f"{source_id}: primary authority conflicts with {source.get('evidence_type')} evidence type")

    for evidence in data.get("evidence", []):
        evidence_id = evidence.get("id", "<unknown>")
        source_id = evidence.get("source_id")
        if source_id not in source_ids:
            errors.append(f"{evidence_id}: source_id must reference a source")
        check_refs(evidence_id, evidence.get("subject_ids", []), entity_ids | product_ids)
        if evidence.get("evidence_kind") == "rumor" and evidence.get("stance") == "supports":
            warnings.append(f"{evidence_id}: rumor evidence supports a statement; keep it out of fact claims")
        if not str(evidence.get("excerpt") or "").strip():
            errors.append(f"{evidence_id}: evidence excerpt must contain non-whitespace text")
        if not str(evidence.get("locator") or "").strip():
            errors.append(f"{evidence_id}: evidence requires a non-empty locator")
        if not str(evidence.get("observed_at") or "").strip():
            errors.append(f"{evidence_id}: evidence requires observed_at")
        source_excerpt = normalized_excerpt(sources_by_id.get(source_id, {}).get("excerpt"))
        evidence_excerpt = normalized_excerpt(evidence.get("excerpt"))
        if evidence_excerpt and evidence_excerpt not in source_excerpt:
            errors.append(f"{evidence_id}: evidence excerpt is not present in its source excerpt")

    identity = data.get("identity_resolution")
    if identity:
        check_refs("identity_resolution", identity.get("evidence_ids", []), evidence_ids | source_ids)

    footprint_rows = data.get("footprint_coverage", [])
    footprint_dimensions: set[str] = set()
    footprint_evidence_dimensions: dict[str, set[str]] = {}
    footprint_fingerprint_dimensions: dict[tuple[str, str], set[str]] = {}
    footprint_fingerprint_ids: dict[tuple[str, str], set[str]] = {}
    for row in footprint_rows:
        dimension = row.get("dimension", "<unknown>")
        if dimension in footprint_dimensions:
            errors.append(f"footprint_coverage: duplicate dimension {dimension}")
        footprint_dimensions.add(dimension)
        check_refs(f"footprint_coverage[{dimension}]", row.get("source_ids", []), source_ids)
        check_refs(f"footprint_coverage[{dimension}]", row.get("evidence_ids", []), evidence_ids)
        for evidence_id in row.get("evidence_ids", []):
            footprint_evidence_dimensions.setdefault(evidence_id, set()).add(dimension)
            evidence = objects.get(evidence_id, {})
            fingerprint = (
                str(evidence.get("source_id") or ""),
                normalized_excerpt(evidence.get("excerpt")),
            )
            footprint_fingerprint_dimensions.setdefault(fingerprint, set()).add(dimension)
            footprint_fingerprint_ids.setdefault(fingerprint, set()).add(evidence_id)
        if row.get("status") == "covered":
            if not row.get("evidence_ids"):
                errors.append(f"footprint_coverage[{dimension}]: covered requires evidence_ids")
            if not row.get("source_ids"):
                errors.append(f"footprint_coverage[{dimension}]: covered requires source_ids")
            actual_sources = {
                objects.get(evidence_id, {}).get("source_id")
                for evidence_id in row.get("evidence_ids", [])
                if objects.get(evidence_id, {}).get("source_id") in source_ids
            }
            if set(row.get("source_ids", [])) != actual_sources:
                errors.append(
                    f"footprint_coverage[{dimension}]: source_ids must exactly match evidence source lineage"
                )
        if row.get("status") in {"partial", "gap"} and not row.get("gap_reason"):
            errors.append(f"footprint_coverage[{dimension}]: {row.get('status')} requires gap_reason")

    for edge in data.get("relationship_edges", []):
        edge_id = edge.get("id", "<unknown>")
        check_refs(edge_id, edge.get("evidence_ids", []), source_ids | evidence_ids)
        enforce_derived_source_quality(edge_id, edge, edge.get("evidence_ids", []))
        if edge.get("status") == "verified" and edge.get("confidence") == "low":
            warnings.append(f"{edge_id}: verified relationship has low confidence")

    for estimate in data.get("proxy_estimates", []):
        estimate_id = estimate.get("id", "<unknown>")
        check_refs(estimate_id, estimate.get("input_evidence_ids", []), evidence_ids)
        enforce_derived_source_quality(
            estimate_id, estimate, estimate.get("input_evidence_ids", [])
        )
        lower = estimate.get("lower_bound")
        base = estimate.get("base_case")
        upper = estimate.get("upper_bound")
        if all(isinstance(value, (int, float)) for value in (lower, base, upper)) and not lower <= base <= upper:
            errors.append(f"{estimate_id}: expected lower_bound <= base_case <= upper_bound")
        if estimate.get("confidence") == "medium" and len(estimate.get("input_evidence_ids", [])) < 2:
            errors.append(f"{estimate_id}: medium-confidence estimate requires at least two input evidence items")

    coverage_rows = data.get("source_coverage", [])
    seen_perspectives: set[str] = set()
    for row in coverage_rows:
        perspective = row.get("perspective", "<unknown>")
        if perspective in seen_perspectives:
            errors.append(f"source_coverage: duplicate perspective {perspective}")
        seen_perspectives.add(perspective)
        check_refs(f"source_coverage[{perspective}]", row.get("source_ids", []), source_ids)
        mismatched_sources = sorted(
            source_id
            for source_id in row.get("source_ids", [])
            if sources_by_id.get(source_id, {}).get("source_perspective") != perspective
        )
        if mismatched_sources:
            errors.append(
                f"source_coverage[{perspective}]: source perspective mismatch: "
                + ", ".join(mismatched_sources)
            )
        if row.get("status") == "covered" and not row.get("source_ids"):
            errors.append(f"source_coverage[{perspective}]: covered requires source_ids")
        if row.get("status") == "covered":
            usable_sources = [
                sources_by_id.get(source_id, {})
                for source_id in row.get("source_ids", [])
                if sources_by_id.get(source_id, {}).get("source_perspective") == perspective
                and sources_by_id.get(source_id, {}).get("verification") != "discovery_only"
                and str(sources_by_id.get(source_id, {}).get("excerpt") or "").strip()
            ]
            if not usable_sources:
                errors.append(
                    f"source_coverage[{perspective}]: covered requires a matching non-discovery source with an excerpt"
                )
        if row.get("status") == "gap" and not row.get("gap_reason"):
            errors.append(f"source_coverage[{perspective}]: gap requires gap_reason")

    for health in data.get("source_health", []):
        health_id = health.get("id", "<unknown>")
        check_refs(health_id, health.get("source_ids", []), source_ids)
        if health.get("status") == "available" and not health.get("source_ids"):
            warnings.append(f"{health_id}: available source group has no captured source_ids")
        if health.get("status") == "stale" and health.get("last_success_at") is None:
            errors.append(f"{health_id}: stale source group requires last_success_at")
        if health.get("status") in {"partial", "stale", "unavailable"} and not health.get("notes"):
            warnings.append(f"{health_id}: degraded source group should explain the limitation")

    intelligence_ids = {item.get("id") for item in data.get("intelligence_items", [])}
    for item in data.get("discarded_sources", []):
        owner = f"discarded source {item.get('url', '<unknown>')}"
        parsed = urlparse(item.get("url", ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{owner}: invalid URL")
        if item.get("decision") == "duplicate" and not item.get("duplicate_of"):
            errors.append(f"{owner}: duplicate requires duplicate_of")
        if item.get("decision") == "downgrade_to_intelligence" and item.get("intelligence_id") not in intelligence_ids:
            errors.append(f"{owner}: downgrade_to_intelligence requires a valid intelligence_id")

    for metric in data.get("metrics", []):
        metric_id = metric.get("id", "<unknown>")
        check_refs(metric_id, metric.get("source_ids", []), source_ids)
        metric_evidence_ids = metric.get("evidence_ids", [])
        check_refs(metric_id, metric_evidence_ids, evidence_ids)
        declared_metric_sources = set(metric.get("source_ids", []))
        actual_metric_sources = {
            objects.get(evidence_id, {}).get("source_id")
            for evidence_id in metric_evidence_ids
            if objects.get(evidence_id, {}).get("source_id") in source_ids
        }
        if declared_metric_sources != actual_metric_sources:
            errors.append(f"{metric_id}: source_ids must exactly match the sources behind evidence_ids")
        discovery_metric_sources = sorted(
            source_id
            for source_id in actual_metric_sources
            if sources_by_id.get(source_id, {}).get("verification") == "discovery_only"
        )
        if discovery_metric_sources:
            errors.append(
                f"{metric_id}: discovery-only sources cannot support metrics: "
                + ", ".join(discovery_metric_sources)
            )
        value = metric.get("value")
        if metric.get("metric_type") in {"actual", "proxy"} and not isinstance(value, (int, float)):
            errors.append(f"{metric_id}: {metric.get('metric_type')} metric value must be numeric")
        if isinstance(value, (int, float)) and metric.get("metric_type") in {"actual", "proxy"}:
            # Keep the JSON precision; :g rounds long decimals and creates false negatives.
            excerpts = " ".join(
                str(objects.get(evidence_id, {}).get("excerpt") or "")
                for evidence_id in metric_evidence_ids
            )
            expected = Decimal(str(value))
            if expected not in numeric_tokens(excerpts):
                errors.append(f"{metric_id}: numeric value {value:g} is absent from cited source excerpts")
            unit = str(metric.get("unit") or "").strip()
            if unit and unit not in excerpts:
                errors.append(f"{metric_id}: unit {unit!r} is absent from cited source excerpts")
            normalized_metric_excerpts = normalized_excerpt(excerpts).casefold()
            for field in ("period", "scope"):
                field_value = normalized_excerpt(metric.get(field))
                if field_value and field_value.casefold() not in normalized_metric_excerpts:
                    errors.append(
                        f"{metric_id}: {field} {field_value!r} is absent from cited source excerpts"
                    )
        if metric.get("value") == 0 and metric.get("metric_type") in {"estimate", "proxy"}:
            warnings.append(f"{metric_id}: zero estimate/proxy may be an unknown value encoded as zero")

    for collection in ("experience_signals", "rd_signals"):
        for signal in data.get(collection, []):
            check_refs(signal.get("id", "<unknown>"), signal.get("evidence_ids", []), evidence_ids)
            enforce_derived_source_quality(
                signal.get("id", "<unknown>"), signal, signal.get("evidence_ids", [])
            )
            if signal.get("subject_id") not in product_ids | entity_ids:
                errors.append(f"{signal.get('id')}: subject_id must reference a product or entity")
            if collection == "experience_signals" and not signal.get("sample_scope"):
                warnings.append(f"{signal.get('id')}: user experience signal has no sample_scope")

    for product in data.get("products", []):
        product_id = product.get("id", "<unknown>")
        if product.get("entity_id") not in entity_ids:
            errors.append(f"{product_id}: entity_id must reference an entity")
        check_refs(product_id, product.get("evidence_ids", []), evidence_ids)
        enforce_derived_source_quality(product_id, product, product.get("evidence_ids", []))
        profit_roles = {product.get("role"), *product.get("secondary_roles", [])}
        if "profit_engine" in profit_roles:
            if not product.get("evidence_ids"):
                errors.append(f"{product_id}: profit_engine requires evidence")
            for field in ("economic_scope", "profit_measure", "scope_contamination"):
                if not product.get(field):
                    errors.append(f"{product_id}: profit_engine requires {field}")
            if product.get("scope_contamination") != "none" and product.get("confidence") == "high":
                errors.append(f"{product_id}: contaminated profit scope cannot have high confidence")

    for node in data.get("supply_chain_nodes", []):
        node_id = node.get("id", "<unknown>")
        check_refs(node_id, node.get("evidence_ids", []), evidence_ids)
        enforce_derived_source_quality(node_id, node, node.get("evidence_ids", []))
        check_refs(node_id, node.get("product_ids", []), product_ids)

    allowed_derived_evidence = source_ids | evidence_ids | metric_ids | signal_ids

    for signal in data.get("external_signals", []):
        signal_id = signal.get("id", "<unknown>")
        check_refs(signal_id, signal.get("evidence_ids", []), allowed_derived_evidence)
        check_refs(signal_id, signal.get("affected_node_ids", []), supply_node_ids)
        if signal.get("freshness") == "stale" and signal.get("severity") in {"critical", "high"}:
            warnings.append(f"{signal_id}: high-severity interpretation relies on stale external data")
        if signal.get("status") == "forecast" and not signal.get("caveats"):
            errors.append(f"{signal_id}: forecast external signal requires caveats")

    for link in data.get("exposure_links", []):
        link_id = link.get("id", "<unknown>")
        if link.get("entity_id") not in entity_ids:
            errors.append(f"{link_id}: entity_id must reference an entity")
        check_refs(link_id, link.get("product_ids", []), product_ids)
        check_refs(link_id, link.get("supply_chain_node_ids", []), supply_node_ids)
        check_refs(link_id, link.get("external_signal_ids", []), external_signal_ids)
        check_refs(link_id, link.get("evidence_ids", []), allowed_derived_evidence)
        link_evidence_ids = set(link.get("evidence_ids", []))
        if not link_evidence_ids:
            errors.append(f"{link_id}: exposure link requires enterprise-level evidence")
        else:
            exposure_targets = {link.get("entity_id"), *link.get("product_ids", [])}
            exposure_targets.discard(None)
        if link_evidence_ids and not any(
            ref_has_enterprise_evidence(ref, exposure_targets) for ref in link_evidence_ids
        ):
            errors.append(f"{link_id}: exposure link lacks usable enterprise evidence; external-signal and discovery-only evidence are insufficient")
        if not link.get("product_ids") and not link.get("supply_chain_node_ids"):
            warnings.append(f"{link_id}: exposure is not anchored to a product or supply-chain node")
        if link.get("sensitivity") == "high" and not link.get("unknowns"):
            warnings.append(f"{link_id}: high sensitivity has no explicit unknowns")

    for market in data.get("product_markets", []):
        market_id = market.get("id", "<unknown>")
        if market.get("product_id") not in product_ids:
            errors.append(f"{market_id}: product_id must reference a product")
        check_refs(market_id, market.get("customer_segment_ids", []), customer_ids)
        check_refs(market_id, market.get("evidence_ids", []), allowed_derived_evidence)
        enforce_derived_source_quality(market_id, market, market.get("evidence_ids", []))
        if market.get("market_share") is not None:
            for field in ("share_unit", "share_period", "share_basis"):
                if not market.get(field):
                    errors.append(f"{market_id}: market_share requires {field}")
            market_atomic_ids = {
                evidence_id
                for ref in market.get("evidence_ids", [])
                for evidence_id in atomic_evidence_ids_for_ref(ref)
            }
            market_excerpts = " ".join(
                str(objects.get(evidence_id, {}).get("excerpt") or "")
                for evidence_id in market_atomic_ids
            )
            share_value = Decimal(str(market.get("market_share")))
            if share_value not in numeric_tokens(market_excerpts):
                errors.append(
                    f"{market_id}: market_share {market.get('market_share')} is absent from cited source excerpts"
                )
            for field in ("share_unit", "share_period", "share_basis"):
                field_value = str(market.get(field) or "").strip()
                if field_value and field_value not in market_excerpts:
                    errors.append(
                        f"{market_id}: {field} {field_value!r} is absent from cited source excerpts"
                    )

    for customer in data.get("customer_segments", []):
        check_refs(customer.get("id", "<unknown>"), customer.get("evidence_ids", []), source_ids | evidence_ids | signal_ids)
        enforce_derived_source_quality(
            customer.get("id", "<unknown>"), customer, customer.get("evidence_ids", [])
        )

    for competitor in data.get("competitors", []):
        competitor_id = competitor.get("id", "<unknown>")
        check_refs(competitor_id, competitor.get("target_product_ids", []), product_ids)
        check_refs(competitor_id, competitor.get("evidence_ids", []), allowed_derived_evidence)
        enforce_derived_source_quality(
            competitor_id, competitor, competitor.get("evidence_ids", [])
        )
        competitor_source_ids = competitor.get("competitor_source_ids", [])
        check_refs(competitor_id, competitor_source_ids, source_ids)
        competitor_evidence_sources = {
            source_id
            for ref in competitor.get("evidence_ids", [])
            for source_id in atomic_source_ids_for_ref(ref)
        }
        undeclared_evidence_sources = sorted(competitor_evidence_sources - set(competitor_source_ids))
        if undeclared_evidence_sources:
            errors.append(
                f"{competitor_id}: evidence sources must be declared in competitor_source_ids: "
                + ", ".join(undeclared_evidence_sources)
            )
        if competitor.get("evidence_ids") and not competitor_evidence_sources:
            errors.append(f"{competitor_id}: evidence_ids do not resolve to atomic source evidence")
        independent = [
            objects[source_id]
            for source_id in competitor_source_ids
            if source_id in objects and objects[source_id].get("source_perspective") in {"competitor", "regulator", "investor", "media", "behavioral_data"}
        ]
        if not independent:
            errors.append(f"{competitor_id}: requires a competitor or independent source")
        if (competitor.get("advantages") or competitor.get("weaknesses")) and competitor.get("threat_level") == "unknown":
            warnings.append(f"{competitor_id}: advantages/weaknesses are filled while threat_level is unknown")

    linkable_ids = entity_ids | product_ids | customer_ids
    for link in data.get("business_model_links", []):
        link_id = link.get("id", "<unknown>")
        if link.get("from_id") not in linkable_ids:
            errors.append(f"{link_id}: from_id must reference an entity, product, or customer segment")
        if link.get("to_id") not in linkable_ids:
            errors.append(f"{link_id}: to_id must reference an entity, product, or customer segment")
        check_refs(link_id, link.get("evidence_ids", []), allowed_derived_evidence)
        enforce_derived_source_quality(link_id, link, link.get("evidence_ids", []))

    for collection in ("organization_signals", "observations", "narrative_risks", "intelligence_items"):
        for item in data.get(collection, []):
            item_id = item.get("id", "<unknown>")
            check_refs(item_id, item.get("evidence_ids", []), allowed_derived_evidence)
            if collection != "intelligence_items":
                enforce_derived_source_quality(
                    item_id, item, item.get("evidence_ids", [])
                )
            if collection == "observations" and not item.get("alternative_explanations"):
                errors.append(f"{item_id}: observation requires alternative_explanations")
            if collection == "intelligence_items" and item.get("status") == "open" and not item.get("next_verification"):
                errors.append(f"{item_id}: open intelligence requires next_verification")
            if collection == "intelligence_items":
                raw_ids = item.get("raw_source_evidence_ids", [])
                check_refs(item_id, raw_ids, evidence_ids)
                if not raw_ids:
                    errors.append(f"{item_id}: intelligence requires raw_source_evidence_ids")
                for evidence_id in raw_ids:
                    evidence = objects.get(evidence_id, {})
                    if evidence.get("evidence_kind") not in {"rumor", "user_report", "observed_behavior", "expert_interpretation"}:
                        errors.append(f"{item_id}: raw evidence {evidence_id} does not carry an uncertain claim")

    for claim in data.get("claims", []):
        claim_id = claim.get("id", "<unknown>")
        refs = claim.get("evidence_ids", [])
        check_refs(claim_id, refs, claim_evidence_ids)
        counter_refs = claim.get("counter_evidence_ids", [])
        check_refs(claim_id, counter_refs, claim_evidence_ids)
        direct_source_refs = sorted(ref for ref in [*refs, *counter_refs] if ref in source_ids)
        if direct_source_refs:
            errors.append(
                f"{claim_id}: claims must cite atomic evidence or derived metrics/signals, not source records: "
                + ", ".join(direct_source_refs)
            )
        overlap = sorted(set(refs) & set(counter_refs))
        if overlap:
            errors.append(f"{claim_id}: support and counter evidence overlap: {', '.join(overlap)}")
        for number, component in enumerate(claim.get("claim_components", []), 1):
            component_owner = f"{claim_id}.claim_components[{number}]"
            component_refs = component.get("evidence_ids", [])
            check_refs(component_owner, component_refs, claim_evidence_ids)
            component_direct_sources = sorted(ref for ref in component_refs if ref in source_ids)
            if component_direct_sources:
                errors.append(
                    f"{component_owner}: must cite atomic evidence or derived metrics/signals, not source records: "
                    + ", ".join(component_direct_sources)
                )
            component_atomic = {
                evidence_id
                for ref in component_refs
                for evidence_id in atomic_evidence_ids_for_ref(ref)
            }
            component_source_ids = {
                objects.get(evidence_id, {}).get("source_id")
                for evidence_id in component_atomic
                if objects.get(evidence_id, {}).get("source_id") in source_ids
            }
            component_discovery_sources = sorted(
                source_id
                for source_id in component_source_ids
                if sources_by_id.get(source_id, {}).get("verification") == "discovery_only"
            )
            if component_discovery_sources:
                errors.append(
                    f"{component_owner}: discovery-only sources cannot support claim components: "
                    + ", ".join(component_discovery_sources)
                )
            component_contradictions = sorted(
                evidence_id
                for evidence_id in component_atomic
                if objects.get(evidence_id, {}).get("stance") == "contradicts"
            )
            if component_contradictions:
                errors.append(
                    f"{component_owner}: supporting evidence is marked contradicts: "
                    + ", ".join(component_contradictions)
                )
            if component.get("confidence") == "high" and not any(
                objects.get(evidence_id, {}).get("stance") == "supports"
                for evidence_id in component_atomic
            ):
                errors.append(f"{component_owner}: high-confidence component requires supporting atomic evidence")
            if component.get("confidence") == "high":
                component_untrusted_sources = sorted(
                    source_id
                    for source_id in component_source_ids
                    if sources_by_id.get(source_id, {}).get("verification") not in {"verified", "corroborated"}
                )
                if not component_source_ids or component_untrusted_sources:
                    errors.append(
                        f"{component_owner}: high-confidence component requires only verified or corroborated sources"
                    )
        if not refs:
            errors.append(f"{claim_id}: claim requires evidence")
            continue
        for ref in refs:
            source = objects.get(ref)
            if source and ref in source_ids:
                if source.get("verification") == "discovery_only":
                    errors.append(f"{claim_id}: discovery-only source {ref} cannot support a claim")
                if not str(source.get("excerpt") or "").strip():
                    errors.append(f"{claim_id}: source {ref} has no excerpt")

        supporting_source_ids: set[str] = set()
        supporting_atomic_evidence: list[dict] = []
        for ref in refs:
            supporting_source_ids.update(atomic_source_ids_for_ref(ref))
            supporting_atomic_evidence.extend(
                objects.get(evidence_id, {})
                for evidence_id in atomic_evidence_ids_for_ref(ref)
            )
        supporting_sources = [sources_by_id[source_id] for source_id in supporting_source_ids if source_id in sources_by_id]
        discovery_support = sorted(
            item.get("id", "<unknown>")
            for item in supporting_sources
            if item.get("verification") == "discovery_only"
        )
        if discovery_support:
            errors.append(
                f"{claim_id}: discovery-only sources cannot support claims through atomic evidence: "
                + ", ".join(discovery_support)
            )
        trusted_sources = [item for item in supporting_sources if item.get("verification") in {"verified", "corroborated"}]
        contradictory_support = sorted(
            item.get("id", "<unknown>")
            for item in supporting_atomic_evidence
            if item.get("stance") == "contradicts"
        )
        if contradictory_support:
            errors.append(
                f"{claim_id}: supporting evidence is marked contradicts: "
                + ", ".join(contradictory_support)
            )
        if claim.get("claim_type") == "fact" or claim.get("confidence") == "high":
            if not any(item.get("stance") == "supports" for item in supporting_atomic_evidence):
                errors.append(f"{claim_id}: fact/high-confidence claim requires supporting atomic evidence")
        rumor_support = [
            item.get("id", "<unknown>")
            for item in supporting_atomic_evidence
            if item.get("evidence_kind") == "rumor"
            or sources_by_id.get(item.get("source_id"), {}).get("evidence_type") == "rumor"
        ]
        rumor_support.extend(
            source_id
            for source_id in supporting_source_ids
            if sources_by_id.get(source_id, {}).get("evidence_type") == "rumor"
        )
        if claim.get("claim_type") == "fact":
            if rumor_support:
                errors.append(f"{claim_id}: fact claim cannot use rumor evidence: {', '.join(rumor_support)}")
            if not trusted_sources:
                errors.append(f"{claim_id}: fact claim requires verified or corroborated source evidence")
        if claim.get("confidence") == "high":
            if not trusted_sources:
                errors.append(f"{claim_id}: high-confidence claim requires trusted source evidence")
            untrusted = sorted(
                item.get("id", "<unknown>")
                for item in supporting_sources
                if item.get("verification") not in {"verified", "corroborated"}
            )
            if untrusted:
                errors.append(f"{claim_id}: high-confidence claim cites unverified sources: {', '.join(untrusted)}")
            if claim.get("claim_type") == "fact" and trusted_sources:
                has_primary = any(item.get("authority") == "primary" for item in trusted_sources)
                if not has_primary:
                    publishers = [
                        re.sub(r"\W+", "", str(item.get("publisher") or "").lower(), flags=re.UNICODE)
                        for item in trusted_sources
                    ]
                    canonical_urls = [canonical_source_url(str(item.get("url") or "")) for item in trusted_sources]
                    content_hashes = [str(item.get("content_hash") or "").strip().lower() for item in trusted_sources]
                    source_excerpts = [normalized_excerpt(item.get("excerpt")) for item in trusted_sources]
                    independent = (
                        len(trusted_sources) >= 2
                        and all(publishers)
                        and len(set(publishers)) == len(publishers)
                        and all(canonical_urls)
                        and len(set(canonical_urls)) == len(canonical_urls)
                        and all(re.fullmatch(r"[0-9a-f]{64}", item) for item in content_hashes)
                        and len(set(content_hashes)) == len(content_hashes)
                        and all(source_excerpts)
                        and len(set(source_excerpts)) == len(source_excerpts)
                    )
                    if not independent:
                        errors.append(
                            f"{claim_id}: high-confidence fact requires a primary source or at least two trusted sources "
                            "with distinct publishers, canonical URLs, content hashes and source excerpts"
                        )
        if claim.get("claim_type") in {"inference", "forecast"} and not claim.get("falsifier"):
            warnings.append(f"{claim_id}: inference/forecast has no falsifier")
        if claim.get("claim_type") in {"inference", "forecast"} and claim.get("confidence") == "high":
            status = claim.get("counter_search_status")
            if status not in {"searched_found", "searched_none"}:
                errors.append(f"{claim_id}: high-confidence inference requires counter_search_status")
            if status == "searched_none" and not claim.get("no_counter_evidence_reason"):
                errors.append(f"{claim_id}: searched_none requires no_counter_evidence_reason")
            if status == "searched_found":
                counter_refs = claim.get("counter_evidence_ids", [])
                if not counter_refs:
                    errors.append(f"{claim_id}: searched_found requires counter_evidence_ids")
                non_contradicting = sorted(
                    ref
                    for ref in counter_refs
                    if ref in objects and objects.get(ref, {}).get("stance") != "contradicts"
                )
                if non_contradicting:
                    errors.append(
                        f"{claim_id}: counter evidence must use contradicts stance: "
                        + ", ".join(non_contradicting)
                    )
        comparison_terms = ("之一", "更接近", "高于", "低于", "领先", "优于", "弱于")
        if any(term in claim.get("statement", "") for term in comparison_terms) and not claim.get("comparison_set"):
            errors.append(f"{claim_id}: comparative claim requires comparison_set")

    for opportunity in data.get("opportunities", []):
        check_refs(opportunity.get("id", "<unknown>"), opportunity.get("evidence_ids", []), allowed_derived_evidence)
        if not opportunity.get("next_test"):
            warnings.append(f"{opportunity.get('id')}: opportunity has no next_test")

    for scenario in data.get("scenarios", []):
        check_refs(scenario.get("id", "<unknown>"), scenario.get("evidence_ids", []), allowed_derived_evidence)
        check_refs(scenario.get("id", "<unknown>"), scenario.get("external_signal_ids", []), external_signal_ids)
        if scenario.get("external_signal_ids") and not scenario.get("transmission_path"):
            errors.append(f"{scenario.get('id', '<unknown>')}: external scenario requires transmission_path")
        if scenario.get("shock_variables") and not scenario.get("impact_dimensions"):
            errors.append(f"{scenario.get('id', '<unknown>')}: shock variables require impact_dimensions")

    for item in data.get("monitoring_plan", []):
        check_refs(item.get("id", "<unknown>"), item.get("evidence_ids", []), allowed_derived_evidence)
        if item.get("status") == "active" and item.get("baseline") is None:
            warnings.append(f"{item.get('id', '<unknown>')}: active monitor has no baseline")

    for result in data.get("scenario_results", []):
        result_id = result.get("id", "<unknown>")
        check_refs(result_id, [result.get("scenario_id", "")], {item.get("id") for item in data.get("scenarios", [])})
        check_refs(result_id, result.get("evidence_ids", []), allowed_derived_evidence)
        if not result.get("evidence_ids"):
            errors.append(f"{result_id}: scenario result requires evidence_ids for its baseline and assumptions")
        if not result.get("formula") or not result.get("assumptions"):
            errors.append(f"{result_id}: scenario result requires a transparent formula and assumptions")
        values = [result.get("lower_bound"), result.get("base_case"), result.get("upper_bound")]
        if not all(isinstance(value, (int, float)) for value in values):
            errors.append(f"{result_id}: scenario range values must be numeric")
        elif not values[0] <= values[1] <= values[2]:
            errors.append(f"{result_id}: expected lower_bound <= base_case <= upper_bound")

    research_purpose = data.get("meta", {}).get("research_purpose")
    if not research_purpose:
        errors.append("meta.research_purpose is required")
        research_purpose = "intelligence"
    if "analysis_lenses" not in data.get("meta", {}):
        errors.append("meta.analysis_lenses is required")
    if not data.get("meta", {}).get("information_regime"):
        errors.append("meta.information_regime is required")
    analysis_lenses = data.get("meta", {}).get("analysis_lenses", [])
    if not isinstance(analysis_lenses, list):
        analysis_lenses = []
    lenses = set(analysis_lenses)

    lens_sections = {
        "period_reviews": {"earnings_delta"},
        "management_commitments": {"earnings_delta", "management"},
        "capital_allocation_events": {"management"},
        "thesis_changes": {"thesis_drift"},
        "income_analysis": {"income"},
        "bottleneck_nodes": {"bottleneck"},
        "decision_audit": {"decision_audit"},
    }
    for section, allowed_lenses in lens_sections.items():
        if data.get(section) and not (lenses & allowed_lenses):
            errors.append(
                f"{section} requires analysis_lenses to include "
                + " or ".join(sorted(allowed_lenses))
            )
    if research_status != "blocked":
        if "earnings_delta" in lenses and not data.get("period_reviews"):
            errors.append("earnings_delta lens requires non-empty period_reviews")
        if "management" in lenses and not (
            data.get("management_commitments") or data.get("capital_allocation_events")
        ):
            errors.append(
                "management lens requires management_commitments or capital_allocation_events"
            )
        if "thesis_drift" in lenses and not data.get("thesis_changes"):
            errors.append("thesis_drift lens requires non-empty thesis_changes")
        if "income" in lenses and not data.get("income_analysis"):
            errors.append("income lens requires non-empty income_analysis")
        if "bottleneck" in lenses and not data.get("bottleneck_nodes"):
            errors.append("bottleneck lens requires non-empty bottleneck_nodes")
        if "decision_audit" in lenses and not data.get("decision_audit"):
            errors.append("decision_audit lens requires decision_audit")
    for investment_lens in ("thesis_drift", "income", "decision_audit"):
        if investment_lens in lenses and research_purpose not in {"investment", "both"}:
            errors.append(
                f"{investment_lens} lens requires meta.research_purpose investment or both"
            )

    decision_audit = data.get("decision_audit") or {}
    if decision_audit:
        gates = decision_audit.get("gates", [])
        gate_names = [gate.get("gate") for gate in gates]
        required_gates = {
            "thesis_clarity", "circle_of_competence", "downside_survivability",
            "evidence_sufficiency", "behavioral_independence", "opportunity_cost",
        }
        if len(gate_names) != len(set(gate_names)):
            errors.append("decision_audit.gates contains duplicate gates")
        missing_gates = sorted(required_gates - set(gate_names))
        if missing_gates:
            errors.append("decision_audit.gates missing: " + ", ".join(missing_gates))
        user_answers = (data.get("intake") or {}).get("user_answers", [])
        for number, gate in enumerate(gates, 1):
            gate_refs = gate.get("evidence_ids", [])
            answer_indices = gate.get("user_answer_indices", [])
            label = f"decision_audit.gates[{number}]"
            check_refs(label, gate_refs, allowed_derived_evidence)
            if gate.get("basis") in {"research_evidence", "mixed"} and gate.get("status") in {"pass", "fail"}:
                if not gate_refs:
                    errors.append(f"{label}: evidence-based pass/fail requires evidence_ids")
                else:
                    enforce_trusted_evidence(
                        label,
                        {"confidence": decision_audit.get("confidence")},
                        gate_refs,
                    )
            if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(user_answers) for index in answer_indices):
                errors.append(f"{label}: user_answer_indices must reference intake.user_answers")
            if gate.get("status") in {"pass", "fail"}:
                if gate.get("basis") in {"user_input", "mixed"} and not answer_indices:
                    errors.append(f"{label}: user-based pass/fail requires user_answer_indices")
                if gate.get("basis") == "user_input" and gate_refs:
                    errors.append(f"{label}: user_input basis cannot cite research evidence")
                if gate.get("basis") == "research_evidence" and answer_indices:
                    errors.append(f"{label}: research_evidence basis cannot cite user answers")
        flags = decision_audit.get("behavioral_flags", [])
        if "none" in flags and len(flags) > 1:
            errors.append("decision_audit.behavioral_flags: none cannot coexist with other flags")
        statuses = {gate.get("status") for gate in gates}
        overall_status = decision_audit.get("overall_status")
        if "fail" in statuses and overall_status != "blocked":
            errors.append("decision_audit: any failed gate requires overall_status blocked")
        elif "fail" not in statuses and "unknown" in statuses and overall_status != "insufficient":
            errors.append("decision_audit: unresolved gates require overall_status insufficient")
        elif statuses and statuses <= {"pass"} and overall_status not in {"ready", "conditional"}:
            errors.append("decision_audit: all passed gates require overall_status ready or conditional")
        if overall_status in {"ready", "conditional"} and not flags:
            errors.append("ready or conditional decision_audit requires behavioral_flags, using none when assessed clean")
        conditions = decision_audit.get("conditions", [])
        if overall_status == "conditional" and not conditions:
            errors.append("conditional decision_audit requires non-empty conditions")
        if overall_status == "ready" and conditions:
            errors.append("ready decision_audit cannot retain unresolved conditions")
        stance = (data.get("investment_conclusion") or {}).get("stance")
        if stance == "consider_entry" and overall_status != "ready":
            errors.append("decision_audit must be ready before consider_entry")
        position_status = (data.get("investment_context") or {}).get("position_status")
        if decision_audit.get("stage") == "initial_entry" and position_status != "not_held":
            errors.append("initial_entry decision_audit requires position_status not_held")
        if decision_audit.get("stage") == "add_position" and position_status != "held":
            errors.append("add_position decision_audit requires position_status held")

    commitment_ids = {item.get("id") for item in data.get("management_commitments", [])}
    thesis_ids = {item.get("id") for item in data.get("investment_theses", [])}
    for review in data.get("period_reviews", []):
        review_id = review.get("id", "<unknown>")
        review_refs = review.get("evidence_ids", [])
        check_refs(review_id, review_refs, allowed_derived_evidence)
        enforce_derived_source_quality(review_id, review, review_refs)
        check_refs(review_id, review.get("commitment_ids", []), commitment_ids)
        for number, delta in enumerate(review.get("metric_deltas", []), 1):
            current_refs = delta.get("current_evidence_ids", [])
            comparison_refs = delta.get("comparison_evidence_ids", [])
            check_refs(f"{review_id}.metric_deltas[{number}].current", current_refs, allowed_derived_evidence)
            check_refs(f"{review_id}.metric_deltas[{number}].comparison", comparison_refs, allowed_derived_evidence)
            enforce_trusted_evidence(
                f"{review_id}.metric_deltas[{number}].current",
                {"confidence": review.get("confidence")},
                current_refs,
            )
            enforce_trusted_evidence(
                f"{review_id}.metric_deltas[{number}].comparison",
                {"confidence": review.get("confidence")},
                comparison_refs,
            )
            current_fingerprints = evidence_fingerprints(current_refs)
            comparison_fingerprints = evidence_fingerprints(comparison_refs)
            if set(current_refs) & set(comparison_refs) or current_fingerprints & comparison_fingerprints:
                errors.append(
                    f"{review_id}.metric_deltas[{number}]: current and comparison periods require substantively distinct evidence"
                )
            validate_period_value(
                f"{review_id}.metric_deltas[{number}].current",
                delta.get("current_value"),
                delta.get("unit"),
                review.get("current_period"),
                current_refs,
            )
            validate_period_value(
                f"{review_id}.metric_deltas[{number}].comparison",
                delta.get("comparison_value"),
                delta.get("unit"),
                review.get("comparison_period"),
                comparison_refs,
            )
        for number, signal in enumerate(review.get("accounting_signals", []), 1):
            refs = signal.get("evidence_ids", [])
            check_refs(f"{review_id}.accounting_signals[{number}]", refs, allowed_derived_evidence)
            if signal.get("status") in {"changed", "unchanged"} and not refs:
                errors.append(
                    f"{review_id}.accounting_signals[{number}]: {signal.get('status')} requires evidence_ids"
                )

    terminal_commitment_statuses = {"met", "partially_met", "missed", "withdrawn"}
    for commitment in data.get("management_commitments", []):
        commitment_id = commitment.get("id", "<unknown>")
        original_refs = commitment.get("original_evidence_ids", [])
        outcome_refs = commitment.get("outcome_evidence_ids", [])
        check_refs(commitment_id, original_refs, allowed_derived_evidence)
        check_refs(commitment_id, outcome_refs, allowed_derived_evidence)
        enforce_trusted_evidence(commitment_id, commitment, original_refs)
        if outcome_refs:
            enforce_trusted_evidence(f"{commitment_id}.outcome", commitment, outcome_refs)
        if commitment.get("status") in terminal_commitment_statuses and not outcome_refs:
            errors.append(f"{commitment_id}: terminal commitment status requires outcome evidence")
        if outcome_refs and evidence_fingerprints(original_refs) & evidence_fingerprints(outcome_refs):
            errors.append(f"{commitment_id}: outcome evidence must be substantively distinct from the original commitment")
        made_at = commitment.get("made_at")
        due_at = commitment.get("due_at")
        if made_at and due_at and due_at < made_at:
            errors.append(f"{commitment_id}: due_at cannot precede made_at")
        if made_at and outcome_refs:
            premature = sorted(
                evidence_id
                for evidence_id, published_at in source_dates_for_refs(outcome_refs)
                if not published_at or published_at <= made_at
            )
            if premature:
                errors.append(
                    f"{commitment_id}: outcome evidence sources must be published after the commitment date: "
                    + ", ".join(premature)
                )
        if commitment.get("status") == "missed":
            if not due_at:
                errors.append(f"{commitment_id}: missed commitment requires due_at")
            else:
                report_date = str(data.get("meta", {}).get("generated_at") or "")[:10]
                if report_date <= due_at:
                    errors.append(f"{commitment_id}: cannot be marked missed before due_at")
                premature_outcomes = sorted(
                    evidence_id
                    for evidence_id, published_at in source_dates_for_refs(outcome_refs)
                    if not published_at or published_at <= due_at
                )
                if premature_outcomes:
                    errors.append(
                        f"{commitment_id}: missed status requires outcome sources published after due_at: "
                        + ", ".join(premature_outcomes)
                    )

    for event in data.get("capital_allocation_events", []):
        event_id = event.get("id", "<unknown>")
        refs = event.get("evidence_ids", [])
        check_refs(event_id, refs, allowed_derived_evidence)
        enforce_trusted_evidence(event_id, event, refs)
        if event.get("amount") is not None and not event.get("currency"):
            errors.append(f"{event_id}: a stated amount requires currency")
        event_excerpt = cited_excerpts(refs)
        if event.get("amount") is not None:
            if not numeric_value_is_present(event.get("amount"), event_excerpt):
                errors.append(f"{event_id}: amount is absent from cited evidence excerpts")
            currency = normalized_excerpt(event.get("currency"))
            if currency and currency.casefold() not in event_excerpt.casefold():
                errors.append(f"{event_id}: currency {currency!r} is absent from cited evidence excerpts")
        if not exact_date_is_present(event.get("announced_at"), event_excerpt):
            errors.append(f"{event_id}: exact announced_at date is absent from cited evidence excerpts")
        announced_at = str(event.get("announced_at") or "")
        report_date = str(data.get("meta", {}).get("generated_at") or "")[:10]
        if announced_at and report_date and announced_at > report_date:
            errors.append(f"{event_id}: announced_at cannot be later than the report date")

    theses_by_id = {item.get("id"): item for item in data.get("investment_theses", [])}
    for change in data.get("thesis_changes", []):
        change_id = change.get("id", "<unknown>")
        thesis_id = change.get("thesis_id")
        check_refs(change_id, [thesis_id] if thesis_id else [], thesis_ids)
        trigger_refs = change.get("trigger_evidence_ids", [])
        check_refs(change_id, trigger_refs, allowed_derived_evidence)
        if change.get("change_type") != "wording_only":
            if not trigger_refs:
                errors.append(f"{change_id}: material thesis change requires trigger_evidence_ids")
            else:
                enforce_derived_source_quality(change_id, change, trigger_refs)
        if change.get("change_type") == "wording_only" and (
            change.get("previous_status") != change.get("current_status")
            or change.get("direction") != "unchanged"
        ):
            errors.append(
                f"{change_id}: wording_only cannot change thesis status or direction"
            )
        if thesis_id in theses_by_id and change.get("current_status") != theses_by_id[thesis_id].get("status"):
            errors.append(f"{change_id}: current_status must match the current investment thesis")
        if change.get("baseline_as_of") and change.get("current_as_of") and change["baseline_as_of"] >= change["current_as_of"]:
            errors.append(f"{change_id}: current_as_of must be later than baseline_as_of")
        if change.get("change_type") != "wording_only" and trigger_refs:
            baseline = change.get("baseline_as_of", "")
            current = change.get("current_as_of", "")
            out_of_window = sorted(
                evidence_id
                for evidence_id, published_at in source_dates_for_refs(trigger_refs)
                if not (baseline < published_at <= current)
            )
            if out_of_window:
                errors.append(
                    f"{change_id}: trigger evidence sources must be published after baseline_as_of and no later than current_as_of: "
                    + ", ".join(out_of_window)
                )

    income = data.get("income_analysis") or {}
    if income:
        profile = income.get("distribution_profile", {})
        profile_refs = profile.get("evidence_ids", [])
        check_refs("income_analysis.distribution_profile", profile_refs, allowed_derived_evidence)
        enforce_trusted_evidence(
            "income_analysis.distribution_profile",
            {"confidence": income.get("confidence")},
            profile_refs,
        )
        profile_excerpt = cited_excerpts(profile_refs)
        try:
            history_years = Decimal(str(profile.get("history_years")))
        except (InvalidOperation, TypeError, ValueError):
            history_years = None
        if history_years is not None and history_years not in numeric_tokens(profile_excerpt):
            errors.append("income_analysis.distribution_profile: history_years is absent from cited evidence excerpts")
        for field in ("frequency", "currency"):
            value = normalized_excerpt(profile.get(field))
            if value and value.casefold() not in profile_excerpt.casefold():
                errors.append(
                    f"income_analysis.distribution_profile: {field} {value!r} is absent from cited evidence excerpts"
                )
        for number, metric in enumerate(income.get("coverage_metrics", []), 1):
            refs = metric.get("evidence_ids", [])
            check_refs(f"income_analysis.coverage_metrics[{number}]", refs, allowed_derived_evidence)
            enforce_trusted_evidence(
                f"income_analysis.coverage_metrics[{number}]",
                {"confidence": income.get("confidence")},
                refs,
            )
            validate_period_value(
                f"income_analysis.coverage_metrics[{number}]",
                metric.get("value"),
                metric.get("unit"),
                metric.get("period"),
                refs,
            )
        income_cases: dict[str, dict] = {}
        for number, scenario in enumerate(income.get("scenarios", []), 1):
            case = scenario.get("case")
            if case in income_cases:
                errors.append(f"income_analysis.scenarios: duplicate case {case}")
            income_cases[case] = scenario
            refs = scenario.get("evidence_ids", [])
            check_refs(f"income_analysis.scenarios[{number}]", refs, allowed_derived_evidence)
            enforce_trusted_evidence(
                f"income_analysis.scenarios[{number}]",
                {"confidence": income.get("confidence")},
                refs,
            )
            calculation = scenario.get("calculation") or {}
            components = calculation.get("cash_components", [])
            component_values = [item.get("value") for item in components if isinstance(item, dict)]
            distribution_amount = calculation.get("distribution_amount")
            if component_values and all(isinstance(value, (int, float)) for value in component_values):
                expected_cash = sum(Decimal(str(value)) for value in component_values)
                actual_cash = scenario.get("distributable_cash")
                if not isinstance(actual_cash, (int, float)) or Decimal(str(actual_cash)) != expected_cash:
                    errors.append(
                        f"income_analysis.scenarios[{number}]: distributable_cash does not equal cash_components"
                    )
                if isinstance(distribution_amount, (int, float)) and distribution_amount > 0:
                    expected_coverage = expected_cash / Decimal(str(distribution_amount))
                    actual_coverage = scenario.get("payout_coverage")
                    if (
                        not isinstance(actual_coverage, (int, float))
                        or abs(Decimal(str(actual_coverage)) - expected_coverage) > Decimal("0.000001")
                    ):
                        errors.append(
                            f"income_analysis.scenarios[{number}]: payout_coverage does not match calculation"
                        )
        gates = income.get("blocking_gates", [])
        gate_names = [gate.get("gate") for gate in gates]
        required_gates = {
            "coverage", "debt_refinancing", "structural_deterioration",
            "governance_integrity", "evidence_sufficiency",
        }
        if len(gate_names) != len(set(gate_names)):
            errors.append("income_analysis.blocking_gates contains duplicate gates")
        missing_gates = sorted(required_gates - set(gate_names))
        if missing_gates:
            errors.append(
                "income_analysis.blocking_gates missing: " + ", ".join(missing_gates)
            )
        for number, gate in enumerate(gates, 1):
            gate_refs = gate.get("evidence_ids", [])
            check_refs(
                f"income_analysis.blocking_gates[{number}]",
                gate_refs,
                allowed_derived_evidence,
            )
            if gate.get("status") in {"pass", "fail"}:
                enforce_trusted_evidence(
                    f"income_analysis.blocking_gates[{number}]",
                    {"confidence": income.get("confidence")},
                    gate_refs,
                )
        classification = income.get("classification")
        if research_status != "blocked" and classification not in {"insufficient_data", "unsuitable"}:
            missing_cases = sorted({"base", "adverse", "severe"} - set(income_cases))
            if missing_cases:
                errors.append(
                    "income lens requires base, adverse, and severe scenarios: "
                    + ", ".join(missing_cases)
                )
            if not income.get("coverage_metrics"):
                errors.append("income lens requires coverage_metrics unless classified insufficient_data")
        stance = (data.get("investment_conclusion") or {}).get("stance")
        if classification == "insufficient_data" and stance not in {None, "watch", "indeterminate"}:
            errors.append("insufficient income data permits only watch or indeterminate")
        if any(gate.get("status") != "pass" for gate in gates) and stance in {"consider_entry", "hold"}:
            errors.append("unresolved or failed income blocking gate cannot support consider_entry or hold")
        context_currency = (data.get("investment_context") or {}).get("currency")
        if context_currency and profile.get("currency") != context_currency:
            warnings.append(
                "income distribution currency differs from investment context currency; disclose FX exposure"
            )

    for node in data.get("bottleneck_nodes", []):
        node_id = node.get("id", "<unknown>")
        supply_node_id = node.get("supply_chain_node_id")
        check_refs(node_id, [supply_node_id] if supply_node_id else [], supply_node_ids)
        check_refs(node_id, node.get("beneficiary_entity_ids", []), entity_ids)
        refs = node.get("evidence_ids", [])
        check_refs(node_id, refs, allowed_derived_evidence)
        enforce_derived_source_quality(node_id, node, refs)
        observed_dimensions = sum((
            node.get("supply_concentration") is not None,
            node.get("expansion_lead_time_months") is not None,
            node.get("substitution_difficulty") != "unknown",
            node.get("capacity_utilization") is not None,
            node.get("demand_growth") is not None,
            node.get("qualification_lead_time_months") is not None,
            node.get("profit_capture") != "unknown",
        ))
        bottleneck_excerpt = cited_excerpts(refs)
        for field in (
            "supply_concentration",
            "capacity_utilization",
            "demand_growth",
        ):
            value = node.get(field)
            if value is not None and not numeric_value_is_present(value, bottleneck_excerpt, percentage=True):
                errors.append(f"{node_id}: {field} value is absent from cited evidence excerpts")
        for field in ("expansion_lead_time_months", "qualification_lead_time_months"):
            value = node.get(field)
            if value is not None and not numeric_value_is_present(value, bottleneck_excerpt):
                errors.append(f"{node_id}: {field} value is absent from cited evidence excerpts")
        if node.get("bottleneck_status") == "confirmed" and node.get("confidence") == "high":
            supporting_items = [
                item for item in atomic_evidence_for_refs(refs)
                if item.get("stance") == "supports"
            ]
            supporting_fingerprints = {
                (item.get("source_id"), normalized_excerpt(item.get("excerpt")).casefold())
                for item in supporting_items
            }
            supporting_sources = {
                item.get("source_id") for item in supporting_items if item.get("source_id")
            }
            publishers = {
                normalized_excerpt(sources_by_id.get(source_id, {}).get("publisher")).casefold()
                for source_id in supporting_sources
                if normalized_excerpt(sources_by_id.get(source_id, {}).get("publisher"))
            }
            canonical_urls = {
                canonical_source_url(str(sources_by_id.get(source_id, {}).get("url") or ""))
                for source_id in supporting_sources
            }
            if (
                len(supporting_fingerprints) < 2
                or len(supporting_sources) < 2
                or len(publishers) < 2
                or len(canonical_urls) < 2
            ):
                errors.append(
                    f"{node_id}: high-confidence confirmed bottleneck requires two independent supporting sources and substantively distinct evidence"
                )
            if observed_dimensions < 4:
                errors.append(f"{node_id}: high-confidence confirmed bottleneck requires four observed dimensions")

    investment_fields_present = any(
        data.get(field)
        for field in (
            "investment_context", "investment_theses", "valuation_scenarios", "investment_conclusion"
        )
    )
    if research_purpose == "intelligence" and investment_fields_present:
        errors.append("investment sections require meta.research_purpose investment or both")

    if research_purpose in {"investment", "both"}:
        context = data.get("investment_context") or {}
        theses = data.get("investment_theses", [])
        valuations = data.get("valuation_scenarios", [])
        conclusion = data.get("investment_conclusion") or {}
        if research_status != "blocked":
            for field, value in (
                ("investment_context", context),
                ("investment_theses", theses),
                ("valuation_scenarios", valuations),
                ("investment_conclusion", conclusion),
            ):
                if not value:
                    errors.append(f"{research_purpose} research requires non-empty {field}")

        context_evidence = [
            *context.get("reference_value_evidence_ids", []),
            *context.get("capital_structure_evidence_ids", []),
        ]
        if context_evidence:
            check_refs("investment_context", context_evidence, allowed_derived_evidence)
            enforce_derived_source_quality("investment_context", context, context_evidence)

        asset_type = context.get("asset_type")
        reference_value = context.get("reference_value")
        if asset_type == "listed_equity":
            if not context.get("ticker") or not context.get("exchange"):
                errors.append("listed-equity investment requires ticker and exchange")
            if context.get("access_path") != "public_market":
                errors.append("listed-equity investment requires public_market access_path")
            if context.get("reference_value_type") != "price_per_share":
                errors.append("listed-equity investment requires price_per_share reference value")
            if not isinstance(reference_value, (int, float)) or isinstance(reference_value, bool) or reference_value <= 0:
                errors.append("listed-equity investment requires a positive reference price")
            if not context.get("reference_value_evidence_ids"):
                errors.append("listed-equity investment requires reference price evidence")

        for thesis in theses:
            thesis_id = thesis.get("id", "<unknown>")
            check_refs(thesis_id, thesis.get("evidence_ids", []), allowed_derived_evidence)
            check_refs(thesis_id, thesis.get("counter_evidence_ids", []), allowed_derived_evidence)
            enforce_derived_source_quality(thesis_id, thesis, thesis.get("evidence_ids", []))
            counter_status = thesis.get("counter_search_status")
            if counter_status == "searched_found" and not thesis.get("counter_evidence_ids"):
                errors.append(f"{thesis_id}: searched_found requires counter_evidence_ids")
            if counter_status == "searched_none" and not thesis.get("counter_search_notes"):
                errors.append(f"{thesis_id}: searched_none requires counter_search_notes describing search scope")
            if thesis.get("confidence") == "high" and counter_status == "not_searched":
                errors.append(f"{thesis_id}: high-confidence investment thesis requires counter-evidence search")

        if research_status != "blocked" and not 3 <= len(theses) <= 7:
            errors.append("investment research requires 3-7 investment_theses")
        thesis_types = {item.get("thesis_type") for item in theses}
        if research_status != "blocked":
            missing_thesis_types = sorted({"business", "valuation", "risk"} - thesis_types)
            if missing_thesis_types:
                errors.append(
                    "investment theses must cover business, valuation, and risk: "
                    + ", ".join(missing_thesis_types)
                )

        cases: dict[str, dict] = {}
        for scenario in valuations:
            scenario_id = scenario.get("id", "<unknown>")
            case = scenario.get("case")
            if case in cases:
                errors.append(f"valuation_scenarios: duplicate case {case}")
            cases[case] = scenario
            check_refs(scenario_id, scenario.get("evidence_ids", []), allowed_derived_evidence)
            enforce_derived_source_quality(scenario_id, scenario, scenario.get("evidence_ids", []))
            for number, assumption in enumerate(scenario.get("assumptions", []), 1):
                assumption_refs = assumption.get("evidence_ids", [])
                check_refs(f"{scenario_id}.assumptions[{number}]", assumption_refs, allowed_derived_evidence)
                if assumption.get("basis") == "evidence" and not assumption_refs:
                    errors.append(f"{scenario_id}.assumptions[{number}]: evidence basis requires evidence_ids")
            if context:
                if scenario.get("valuation_as_of") != context.get("valuation_as_of"):
                    errors.append(f"{scenario_id}: valuation_as_of must match investment_context")
                if scenario.get("horizon_years") != context.get("holding_period_years"):
                    errors.append(f"{scenario_id}: horizon_years must match investment_context")
                if scenario.get("currency") != context.get("currency"):
                    errors.append(f"{scenario_id}: currency must match investment_context")
                if context.get("reference_value_type") != "unknown" and scenario.get("value_type") != context.get("reference_value_type"):
                    errors.append(f"{scenario_id}: value_type must match investment_context reference_value_type")

            target_value = scenario.get("target_value")
            years = scenario.get("horizon_years")
            if (
                isinstance(reference_value, (int, float)) and not isinstance(reference_value, bool)
                and isinstance(target_value, (int, float)) and not isinstance(target_value, bool)
                and isinstance(years, (int, float)) and not isinstance(years, bool)
                and reference_value > 0 and target_value >= 0 and years > 0
            ):
                try:
                    reference_decimal = Decimal(str(reference_value))
                    target_decimal = Decimal(str(target_value))
                    years_decimal = Decimal(str(years))
                    expected_total = target_decimal / reference_decimal - Decimal(1)
                    expected_annual = (
                        Decimal(-1)
                        if target_decimal == 0
                        else ((target_decimal / reference_decimal).ln() / years_decimal).exp() - Decimal(1)
                    )
                    reported_total = scenario.get("expected_total_return")
                    reported_annual = scenario.get("expected_annual_return")
                    if reported_total is None or abs(Decimal(str(reported_total)) - expected_total) > Decimal("0.000001"):
                        errors.append(f"{scenario_id}: expected_total_return does not match reference and target values")
                    if reported_annual is None or abs(Decimal(str(reported_annual)) - expected_annual) > Decimal("0.000001"):
                        errors.append(f"{scenario_id}: expected_annual_return does not match reference, target, and horizon")
                except (InvalidOperation, ValueError, OverflowError):
                    errors.append(f"{scenario_id}: investment return calculation is invalid")

        complete_cases = {"downside", "base", "upside"}
        stance = conclusion.get("stance")
        directional_stances = {"consider_entry", "hold", "reduce", "exit", "avoid"}
        if research_status == "complete" or stance in directional_stances:
            missing_cases = sorted(complete_cases - set(cases))
            if missing_cases:
                errors.append("directional investment conclusion requires downside, base, and upside cases")
        elif research_status != "blocked" and set(cases) != complete_cases:
            warnings.append("partial investment research does not contain all three valuation cases")
        if complete_cases.issubset(cases):
            target_values = [cases[name].get("target_value") for name in ("downside", "base", "upside")]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in target_values):
                if not target_values[0] <= target_values[1] <= target_values[2]:
                    errors.append("valuation targets must satisfy downside <= base <= upside")

        if conclusion:
            conclusion_refs = conclusion.get("evidence_ids", [])
            check_refs("investment_conclusion", conclusion_refs, allowed_derived_evidence)
            enforce_derived_source_quality("investment_conclusion", conclusion, conclusion_refs)
            anchor = conclusion.get("anchor_scenario_id")
            if anchor not in {item.get("id") for item in valuations if item.get("case") == "base"}:
                errors.append("investment_conclusion anchor_scenario_id must reference the base valuation case")
            position_status = context.get("position_status")
            if stance in {"hold", "reduce", "exit"} and position_status != "held":
                errors.append(f"investment stance {stance} requires position_status held")
            if stance == "consider_entry" and position_status == "held":
                warnings.append("consider_entry is ambiguous for an existing position; disclose whether this means adding")
            if stance in directional_stances:
                if context.get("freshness") != "fresh":
                    errors.append("directional investment conclusion requires fresh reference data")
                if context.get("capital_structure_status") != "verified":
                    errors.append("directional investment conclusion requires verified capital structure")
                if not context.get("capital_structure_evidence_ids"):
                    errors.append("directional investment conclusion requires capital-structure evidence")
            if asset_type == "private_equity" and stance == "consider_entry" and context.get("access_path") in {"none", "unknown"}:
                errors.append("private-equity consider_entry requires a known access path")

    if not data.get("limitations"):
        if data.get("meta", {}).get("research_status") == "complete":
            errors.append("complete research requires non-empty limitations")
        else:
            warnings.append("limitations is empty; research without limitations is usually overconfident")

    if data.get("meta", {}).get("mode") == "deep":
        research_status = data.get("meta", {}).get("research_status")
        if research_status == "blocked":
            if not data.get("key_unknowns"):
                errors.append("blocked deep research requires non-empty key_unknowns")
            if not data.get("limitations"):
                errors.append("blocked deep research requires non-empty limitations")
        else:
            deep_sections = (
                "product_markets", "customer_segments", "competitors", "business_model_links",
                "organization_signals", "observations", "narrative_risks", "intelligence_items"
            )
            for section in deep_sections:
                if not data.get(section):
                    errors.append(f"deep mode requires non-empty {section}")
            if not data.get("evidence"):
                errors.append("deep mode requires non-empty evidence")
            if not data.get("key_unknowns"):
                errors.append("deep mode requires non-empty key_unknowns")
            if not data.get("scenarios"):
                errors.append("deep mode requires non-empty scenarios")
            external_exposure_relevant = bool(data.get("external_signals") or data.get("exposure_links"))
            if external_exposure_relevant:
                if not data.get("source_health"):
                    errors.append("deep external-risk research requires source_health")
                if not data.get("external_signals") or not data.get("exposure_links"):
                    errors.append("deep external-risk research requires both external_signals and exposure_links")
                if not data.get("monitoring_plan"):
                    warnings.append("deep external-risk research has no monitoring_plan")
            for claim in data.get("claims", []):
                if not claim.get("claim_components"):
                    errors.append(f"{claim.get('id', '<unknown>')}: deep mode requires claim_components")
            required_perspectives = {
                "company", "regulator", "competitor", "customer", "channel",
                "supplier", "employee", "behavioral_data"
            }
            missing_perspectives = sorted(required_perspectives - seen_perspectives)
            if missing_perspectives:
                errors.append(f"deep mode source_coverage missing perspectives: {', '.join(missing_perspectives)}")
            covered_perspectives = {
                row.get("perspective")
                for row in coverage_rows
                if row.get("status") == "covered" and row.get("source_ids")
            }
            material_gaps = sorted({"customer", "channel", "supplier", "employee", "behavioral_data"} - covered_perspectives)
            if material_gaps and research_status == "complete":
                errors.append(f"deep mode has material uncovered perspectives: {', '.join(material_gaps)}")
            elif material_gaps:
                warnings.append(f"partial deep research has material uncovered perspectives: {', '.join(material_gaps)}")
            if research_status == "complete":
                untrusted_perspectives = sorted(
                    row.get("perspective")
                    for row in coverage_rows
                    if row.get("perspective") in required_perspectives
                    and row.get("status") == "covered"
                    and not any(
                        sources_by_id.get(source_id, {}).get("verification") in {"verified", "corroborated"}
                        and sources_by_id.get(source_id, {}).get("source_perspective") == row.get("perspective")
                        and normalized_excerpt(sources_by_id.get(source_id, {}).get("excerpt"))
                        for source_id in row.get("source_ids", [])
                    )
                )
                if untrusted_perspectives:
                    errors.append(
                        "complete deep research requires trusted excerpted sources for perspectives: "
                        + ", ".join(untrusted_perspectives)
                    )

    if data.get("meta", {}).get("mode") == "deep" and not intake:
        errors.append("deep mode requires intake to expose questions and assumptions")

    if data.get("meta", {}).get("information_regime") == "private_sparse":
        if not identity:
            errors.append("private_sparse requires identity_resolution")
        if not intake:
            errors.append("private_sparse requires intake to expose identity clues and assumptions")
        elif identity.get("resolution_status") != "resolved" and data.get("meta", {}).get("research_status") == "complete":
            errors.append("complete private_sparse research requires resolved identity")
        research_status = data.get("meta", {}).get("research_status")
        if research_status != "blocked" and not data.get("relationship_edges"):
            warnings.append("private_sparse has no relationship_edges; customers, suppliers and affiliates may be invisible")
        if research_status != "blocked" and not data.get("proxy_estimates"):
            warnings.append("private_sparse has no proxy_estimates; report should avoid unsupported size claims")
        required_footprints = {
            "identity", "ownership", "product", "customer", "supplier", "capacity",
            "organization", "technology", "channel", "judicial", "regulatory"
        }
        missing_footprints = sorted(required_footprints - footprint_dimensions)
        if missing_footprints:
            errors.append(f"private_sparse footprint_coverage missing dimensions: {', '.join(missing_footprints)}")
        material_footprint_gaps = sorted(
            row.get("dimension") for row in footprint_rows
            if row.get("dimension") in {"identity", "product", "customer", "organization", "regulatory"}
            and row.get("status") != "covered"
        )
        if material_footprint_gaps and data.get("meta", {}).get("research_status") == "complete":
            errors.append(f"complete private_sparse research has material footprint gaps: {', '.join(material_footprint_gaps)}")
        elif material_footprint_gaps and research_status != "blocked":
            warnings.append(f"private_sparse has material footprint gaps: {', '.join(material_footprint_gaps)}")
        if research_status == "complete":
            reused_footprint_evidence = sorted(
                evidence_id
                for evidence_id, dimensions in footprint_evidence_dimensions.items()
                if len(dimensions) > 1
            )
            if reused_footprint_evidence:
                errors.append(
                    "complete private_sparse footprint dimensions require distinct atomic evidence; reused: "
                    + ", ".join(reused_footprint_evidence)
                )
            cloned_footprint_evidence = sorted(
                sorted(footprint_fingerprint_ids[fingerprint])
                for fingerprint, dimensions in footprint_fingerprint_dimensions.items()
                if len(dimensions) > 1
            )
            if cloned_footprint_evidence:
                rendered_groups = "; ".join(", ".join(group) for group in cloned_footprint_evidence)
                errors.append(
                    "complete private_sparse footprint dimensions require substantively distinct evidence; "
                    "duplicate source/excerpt fingerprints: " + rendered_groups
                )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("research", type=Path)
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()

    schema_path = args.schema or Path(__file__).resolve().parents[1] / "research.schema.json"
    try:
        data = load_json(args.research)
        schema = load_json(schema_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    schema_messages = schema_validate(data, schema)
    errors = [message for message in schema_messages if not message.startswith("WARNING:")]
    warnings = [message.removeprefix("WARNING: ") for message in schema_messages if message.startswith("WARNING:")]
    semantic_errors, semantic_warnings = semantic_validate(data)
    errors.extend(semantic_errors)
    warnings.extend(semantic_warnings)

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
