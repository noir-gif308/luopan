#!/usr/bin/env python3
"""Normalize public or exported external-risk feeds into Luopan objects.

The adapter deliberately does not require a World Monitor key. It accepts a
local JSON export, a public JSON URL, or a future authenticated endpoint.
Authentication failures become an explicit not_configured result.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collection_common import USER_AGENT, read_limited, require_public_network_url


DOMAIN_TYPES = {
    "geopolitical": "geopolitics", "geopolitics": "geopolitics",
    "trade": "trade", "shipping": "shipping", "supply_chain": "shipping",
    "energy": "energy", "commodity": "commodity", "sanctions": "sanctions",
    "infrastructure": "infrastructure", "climate": "climate", "cyber": "cyber",
    "procurement": "procurement", "policy": "policy", "macro": "macro",
}
EVIDENCE_TYPES = {
    "trade": "trade_flow", "shipping": "shipping", "commodity": "commodity",
    "sanctions": "sanctions", "infrastructure": "infrastructure",
    "market_data": "market_data", "event_data": "event_data",
}
SENSITIVE_HEADERS = {"authorization", "x-worldmonitor-key"}
DEFAULT_FRESHNESS_BUDGET_HOURS = 24.0
MAX_FEED_BYTES = 10 * 1024 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in out.split("-") if part)[:48] or "signal"


def url_origin(
    value: str,
    *,
    require_https: bool = False,
    origin_only: bool = False,
    allow_private: bool = False,
) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid URL port: {value}") from exc
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"URL must be an HTTP(S) URL without user information: {value}")
    if require_https and scheme != "https":
        raise ValueError(f"trusted origin must use HTTPS: {value}")
    if origin_only and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError(f"trusted origin must not contain a path, query, or fragment: {value}")
    if not allow_private:
        require_public_network_url(value)
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def trusted_https_origin(value: str) -> tuple[str, str, int]:
    return url_origin(value, require_https=True, origin_only=True, allow_private=True)


def strip_sensitive_headers(request: Request) -> None:
    for headers in (request.headers, request.unredirected_hdrs):
        for name in list(headers):
            if name.lower() in SENSITIVE_HEADERS:
                del headers[name]


class CredentialSafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if urlsplit(req.full_url).scheme.lower() == "https" and urlsplit(redirected.full_url).scheme.lower() != "https":
            raise HTTPError(newurl, 403, "HTTPS downgrade redirect is forbidden", headers, fp)
        try:
            same_origin = url_origin(req.full_url, allow_private=True) == url_origin(
                redirected.full_url, allow_private=True
            )
            if not same_origin:
                require_public_network_url(redirected.full_url)
        except ValueError as exc:
            raise HTTPError(newurl, 403, str(exc), headers, fp) from exc
        if not same_origin:
            strip_sensitive_headers(redirected)
        return redirected


def open_request(request: Request, timeout: float):
    return build_opener(CredentialSafeRedirectHandler()).open(request, timeout=timeout)


def provider_name(explicit_provider: str | None, url: str | None, path: Path | None) -> str:
    if explicit_provider and explicit_provider.strip():
        return explicit_provider.strip()
    if path is not None:
        return "local-export"
    if url:
        try:
            return urlsplit(url).hostname or "external-feed"
        except ValueError:
            pass
    return "external-feed"


def payload_failure(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    status_value = str(payload.get("status") or payload.get("code") or "").strip().lower()
    error_value = payload.get("error")
    explicit_failure = (
        payload.get("success") is False
        or payload.get("ok") is False
        or bool(error_value)
        or status_value in {"error", "failed", "failure", "unauthorized", "forbidden"}
    )
    if not explicit_failure:
        return None
    message = str(error_value or payload.get("message") or payload.get("reason") or status_value or "feed reported failure")
    lowered = message.lower()
    auth_failure = status_value in {"unauthorized", "forbidden"} or any(
        marker in lowered for marker in ("unauthorized", "forbidden", "api key", "authentication", "quota")
    )
    return ("not_configured" if auth_failure else "unavailable", message)


def load_payload(
    path: Path | None,
    url: str | None,
    api_key_env: str,
    trusted_origin: str | None = None,
    provider: str | None = None,
    freshness_budget_hours: float = DEFAULT_FRESHNESS_BUDGET_HOURS,
) -> tuple[dict | None, dict]:
    observed = now_iso()
    explicit_provider = provider
    provider = provider_name(explicit_provider, url, path)
    if freshness_budget_hours < 0:
        raise ValueError("freshness budget must be non-negative")
    health_base = {
        "provider": provider,
        "observed_at": observed,
        "freshness_budget_hours": freshness_budget_hours,
    }
    if path:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            failure = payload_failure(payload)
            if failure:
                return None, {"status": failure[0], **health_base, "notes": failure[1]}
            return payload, {"status": "available", **health_base}
        except (OSError, json.JSONDecodeError) as exc:
            return None, {"status": "unavailable", **health_base, "notes": str(exc)}
    if not url:
        return None, {"status": "not_configured", **health_base, "notes": "未提供 --input 或 --url；没有把密钥当作默认依赖。"}
    target_origin = url_origin(url, allow_private=trusted_origin is not None)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if trusted_origin is not None:
        if target_origin != trusted_https_origin(trusted_origin):
            raise ValueError("request URL origin does not match --trusted-origin")
        if api_key_env and not os.getenv(api_key_env):
            return None, {
                "status": "not_configured",
                **health_base,
                "notes": f"环境变量 {api_key_env} 未配置。",
                "url": url,
            }
        if api_key_env:
            headers["X-WorldMonitor-Key"] = os.environ[api_key_env]
    try:
        with open_request(Request(url, headers=headers), timeout=30) as response:
            final_url = response.geturl()
            final_origin = url_origin(final_url, allow_private=trusted_origin is not None)
            if target_origin[0] == "https" and final_origin[0] != "https":
                raise ValueError("HTTPS endpoint redirected to HTTP; response rejected")
            if trusted_origin is not None and final_origin != target_origin:
                raise ValueError("trusted endpoint redirected to a different origin; response rejected")
            final_health = {
                **health_base,
                "provider": provider_name(explicit_provider, final_url, None),
                "url": final_url,
            }
            body = read_limited(response, MAX_FEED_BYTES)
            payload = json.loads(body.decode("utf-8"))
            failure = payload_failure(payload)
            if failure:
                return None, {"status": failure[0], **final_health, "notes": failure[1]}
            return payload, {"status": "available", **final_health}
    except HTTPError as exc:
        status = "not_configured" if exc.code in {401, 403} else "unavailable"
        return None, {"status": status, **health_base, "notes": f"HTTP {exc.code}", "url": url}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return None, {"status": "unavailable", **health_base, "notes": str(exc), "url": url}


def parse_record_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def signal_freshness(as_of: object, observed_at: object, budget_hours: float) -> str:
    if budget_hours < 0:
        return "unknown"
    signal_time = parse_record_datetime(as_of)
    observed_time = parse_record_datetime(observed_at)
    if signal_time is None or observed_time is None or signal_time > observed_time:
        return "unknown"
    age_hours = (observed_time - signal_time).total_seconds() / 3600
    return "fresh" if age_hours <= budget_hours else "stale"


def find_records(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("signals", "events", "flows", "items", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = find_records(value)
            if nested:
                return nested
    return []


def normalize(
    payload: dict | None,
    health: dict,
    source_url: str,
    freshness_budget_hours: float | None = None,
) -> dict:
    provider = str(health.get("provider") or "external-feed")
    provider_slug = slug(provider)
    budget = float(
        health.get("freshness_budget_hours", DEFAULT_FRESHNESS_BUDGET_HOURS)
        if freshness_budget_hours is None
        else freshness_budget_hours
    )
    if budget < 0:
        raise ValueError("freshness budget must be non-negative")
    feed_source_id = f"src-{provider_slug}-feed"
    feed_source = {
        "id": feed_source_id,
        "title": f"{provider} / external feed",
        "url": source_url or str(health.get("url") or "urn:luopan:local-export"),
        "publisher": provider,
        "published_at": None,
        "retrieved_at": health["observed_at"],
        "authority": "secondary",
        "evidence_type": "event_data",
        "source_perspective": "behavioral_data",
        "incentive_bias": "聚合平台可能继承上游筛选、覆盖与算法偏差。",
        "verification": "unverified",
        "excerpt": "结构化外部信号入口；具体信号需要回溯原始上游。" if health["status"] == "available" else None,
        "content_hash": None,
        "notes": health.get("notes"),
    }
    sources = [feed_source]
    sources_by_id = {feed_source_id: feed_source}
    source_ids_by_url = {}
    evidence = []
    rows = []
    used_signal_ids = set()
    used_evidence_ids = set()
    for idx, item in enumerate(find_records(payload or {}), 1):
        raw_domain = str(item.get("domain") or item.get("category") or item.get("type") or "other").lower()
        domain = DOMAIN_TYPES.get(raw_domain, "other")
        text = item.get("signal") or item.get("title") or item.get("name") or item.get("description")
        if not text:
            continue
        raw_record_id = slug(str(item.get("id") or item.get("event_id") or idx))
        signal_id = f"ext-{provider_slug}-{raw_record_id}-{slug(str(text))}"
        if signal_id in used_signal_ids:
            signal_id = f"{signal_id}-{idx:03d}"
        used_signal_ids.add(signal_id)
        upstream_url = str(item.get("source_url") or item.get("url") or item.get("link") or "").strip()
        source_id = feed_source_id
        if upstream_url:
            source_id = source_ids_by_url.get(upstream_url, "")
            if not source_id:
                source_id = f"src-ext-{idx:03d}-{slug(str(item.get('source') or item.get('publisher') or text))}"
                source_ids_by_url[upstream_url] = source_id
                upstream_source = {
                    "id": source_id,
                    "title": str(item.get("source_title") or item.get("title") or item.get("name") or "External signal source"),
                    "url": upstream_url,
                    "publisher": str(item.get("publisher") or item.get("source") or health.get("provider", "external-feed")),
                    "published_at": item.get("published_at") or item.get("date") or item.get("as_of"),
                    "retrieved_at": health["observed_at"],
                    "authority": "secondary",
                    "evidence_type": EVIDENCE_TYPES.get(raw_domain, "event_data"),
                    "source_perspective": "behavioral_data",
                    "incentive_bias": "上游来源的采集口径、覆盖范围和发布动机尚未独立核验。",
                    "verification": "unverified",
                    "excerpt": None,
                    "content_hash": None,
                    "notes": "由外部聚合记录提供的上游链接；仍需回溯原文核验。",
                }
                sources.append(upstream_source)
                sources_by_id[source_id] = upstream_source
        description = str(item.get("description") or "").strip()
        excerpt = str(text).strip()
        if description and description != excerpt:
            excerpt = f"{excerpt}；{description}"
        source_record = sources_by_id[source_id]
        existing_source_excerpt = str(source_record.get("excerpt") or "").strip()
        if excerpt not in existing_source_excerpt:
            source_record["excerpt"] = (
                f"{existing_source_excerpt}\n{excerpt}".strip()
                if existing_source_excerpt
                else excerpt
            )
        evidence_id = f"evd-ext-{raw_record_id}-{slug(str(text))}"
        if evidence_id in used_evidence_ids:
            evidence_id = f"{evidence_id}-{idx:03d}"
        used_evidence_ids.add(evidence_id)
        raw_as_of = item.get("as_of") or item.get("date") or item.get("published_at")
        evidence.append({
            "id": evidence_id,
            "source_id": source_id,
            "locator": upstream_url or str(item.get("id") or item.get("event_id") or f"record[{idx - 1}]"),
            "excerpt": excerpt,
            "stance": "context",
            "evidence_kind": "reported_fact" if item.get("status") in {None, "observed"} else "expert_interpretation",
            "observed_at": str(raw_as_of or health["observed_at"]),
            "subject_ids": [],
            "quality_flags": ["aggregated_feed", "upstream_not_independently_verified"],
            "notes": "该证据只证明聚合记录存在，不证明其内容已被罗盘交叉验证。",
        })
        rows.append({
            "id": signal_id,
            "domain": domain,
            "signal": str(text),
            "geography": str(item.get("geography") or item.get("country") or item.get("region") or "未注明"),
            "as_of": str(raw_as_of or health["observed_at"][:10]),
            "direction": item.get("direction") if item.get("direction") in {"adverse", "favorable", "mixed", "neutral", "unknown"} else "unknown",
            "severity": item.get("severity") if item.get("severity") in {"critical", "high", "medium", "low", "unknown"} else "unknown",
            "status": item.get("status") if item.get("status") in {"observed", "inferred", "forecast"} else "observed",
            "freshness": signal_freshness(raw_as_of, health["observed_at"], budget),
            "provider": provider,
            "affected_node_ids": [],
            "caveats": ["聚合信号尚未与企业级暴露绑定。", "需回溯原始上游和覆盖范围。"],
            "evidence_ids": [evidence_id],
        })
    source_health = {
        "id": f"sh-{provider_slug}-feed",
        "source_group": "external-environment",
        "provider": provider,
        "layer": "monitoring",
        "status": health["status"],
        "observed_at": health["observed_at"],
        "last_success_at": health["observed_at"] if health["status"] == "available" else None,
        "freshness_budget_hours": budget,
        "coverage": ["外部聚合信号"] if rows else [],
        "missing_coverage": ["企业级客户、供应商与采购量"],
        "fallback_used": False,
        "notes": health.get("notes") or ("本次为本地导入。" if health.get("provider") == "local-export" else None),
        "source_ids": [item["id"] for item in sources],
    }
    limitations = []
    if health["status"] != "available":
        limitations.append(f"外部信号入口状态为 {health['status']}：{health.get('notes') or '未获取到数据'}")
    if not rows:
        limitations.append("没有可标准化的外部信号；不能把空结果解释成环境没有风险。")
    if rows:
        limitations.append("外部聚合信号已拆为逐条原子证据，但默认仍为 unverified；进入企业结论前必须回溯上游并建立 exposure_links。")
    return {"sources": sources, "evidence": evidence, "source_health": [source_health], "external_signals": rows, "limitations": limitations}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", type=Path, help="local exported JSON")
    group.add_argument("--url", help="public or authorized JSON endpoint")
    parser.add_argument("--api-key-env", default="WORLD_MONITOR_KEY")
    parser.add_argument("--trusted-origin", help="explicit HTTPS origin allowed to receive the API key")
    parser.add_argument("--provider", help="feed provider label; defaults to the URL hostname")
    parser.add_argument("--freshness-budget-hours", type=float, default=DEFAULT_FRESHNESS_BUDGET_HOURS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload, health = load_payload(
            args.input,
            args.url,
            args.api_key_env,
            args.trusted_origin,
            args.provider,
            args.freshness_budget_hours,
        )
        result = normalize(payload, health, str(health.get("url") or args.url or ""))
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": health["status"], "signals": len(result["external_signals"]), "out": str(args.out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
