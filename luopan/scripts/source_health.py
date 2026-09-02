#!/usr/bin/env python3
"""Probe configured external sources and emit source_health[] records."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collection_common import USER_AGENT, require_public_network_url


SENSITIVE_HEADERS = {"authorization", "x-worldmonitor-key"}
MAX_PROBE_BYTES = 512 * 1024
CHALLENGE_MARKERS = (
    "captcha",
    "verify you are human",
    "cloudflare challenge",
    "验证码",
    "安全验证",
    "访问过于频繁",
)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
        for header in list(headers):
            if header.lower() in SENSITIVE_HEADERS:
                del headers[header]


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


def read_limited(stream, max_bytes: int = MAX_PROBE_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"probe response exceeds {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def response_header(response, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    return str(getter(name, "") if getter else "")


def classify_body(content: bytes, content_type: str) -> tuple[str, str | None]:
    if not content.strip():
        return "partial", "HTTP succeeded but the response body was empty."
    lowered_type = content_type.lower()
    text = content.decode("utf-8", errors="replace")
    lowered = text.lower()
    auth_text = any(marker in lowered for marker in ("unauthorized", "forbidden", "invalid api key", "authentication required"))
    looks_html = "text/html" in lowered_type or "application/xhtml" in lowered_type or "<html" in lowered[:1000]
    if looks_html:
        challenge = next((marker for marker in CHALLENGE_MARKERS if marker in lowered), None)
        login_form = bool(
            re.search(r"<form\b", lowered)
            and (
                re.search(r"type\s*=\s*['\"]?password", lowered)
                or any(marker in lowered for marker in ("sign in", "log in", "登录", "用户认证"))
            )
        )
        if challenge or login_form:
            marker = challenge or "login form"
            return "not_configured", f"HTTP 200 returned an authentication or challenge page ({marker})."
        return "partial", "HTTP 200 returned HTML, not a machine-readable health payload."
    looks_json = "json" in lowered_type or content.lstrip().startswith((b"{", b"["))
    if looks_json:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return "partial", "Response claimed to be JSON but could not be parsed."
        if isinstance(payload, dict):
            status_value = str(payload.get("status") or payload.get("code") or "").lower()
            error_value = payload.get("error")
            failed = (
                payload.get("success") is False
                or payload.get("ok") is False
                or bool(error_value)
                or status_value in {"error", "failed", "unauthorized", "forbidden"}
            )
            if failed:
                message = str(error_value or payload.get("message") or status_value or "JSON payload reported failure")
                auth = status_value in {"unauthorized", "forbidden"} or any(
                    marker in message.lower() for marker in ("unauthorized", "forbidden", "api key", "quota")
                )
                return ("not_configured" if auth else "partial"), message
        return "available", None
    if lowered_type.startswith("text/plain"):
        challenge = next((marker for marker in CHALLENGE_MARKERS if marker in lowered), None)
        if challenge:
            return "not_configured", f"Plain-text response reported a challenge page ({challenge})."
        if auth_text:
            return "not_configured", "Plain-text response reported an authentication failure."
        return "available", None
    return "partial", f"Unsupported or missing Content-Type: {content_type or '<missing>'}."


def probe(
    name: str,
    url: str,
    key_env: str | None,
    layer: str,
    budget: float,
    trusted_origin: str | None = None,
) -> dict:
    observed = now()
    if budget < 0:
        raise ValueError("freshness budget must be non-negative")
    try:
        target_origin = url_origin(url, allow_private=trusted_origin is not None)
    except ValueError as exc:
        return {"id": f"sh-{name}", "source_group": name, "provider": name, "layer": layer, "status": "unavailable", "observed_at": observed, "last_success_at": None, "freshness_budget_hours": budget, "coverage": [], "missing_coverage": [url], "fallback_used": False, "notes": str(exc), "source_ids": []}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if trusted_origin is not None:
        if target_origin != trusted_https_origin(trusted_origin):
            raise ValueError("request URL origin does not match trusted_origin")
        if key_env and not os.getenv(key_env):
            return {"id": f"sh-{name}", "source_group": name, "provider": name, "layer": layer, "status": "not_configured", "observed_at": observed, "last_success_at": None, "freshness_budget_hours": budget, "coverage": [], "missing_coverage": ["未配置授权凭据"], "fallback_used": False, "notes": f"环境变量 {key_env} 未配置。", "source_ids": []}
        if key_env:
            headers["X-WorldMonitor-Key"] = os.environ[key_env]
    try:
        with open_request(Request(url, headers=headers), timeout=15) as response:
            final_url = response.geturl()
            final_origin = url_origin(final_url, allow_private=trusted_origin is not None)
            if target_origin[0] == "https" and final_origin[0] != "https":
                raise URLError("HTTPS probe redirected to HTTP; response rejected")
            if trusted_origin is not None and final_origin != target_origin:
                raise URLError("trusted probe redirected to a different origin; response rejected")
            if not 200 <= response.status < 300:
                status, notes = "partial", f"HTTP {response.status}"
            else:
                status, notes = classify_body(read_limited(response), response_header(response, "Content-Type"))
            coverage = [final_url] if status == "available" else []
            missing = [] if status == "available" else [final_url]
            return {"id": f"sh-{name}", "source_group": name, "provider": name, "layer": layer, "status": status, "observed_at": observed, "last_success_at": observed if status == "available" else None, "freshness_budget_hours": budget, "coverage": coverage, "missing_coverage": missing, "fallback_used": False, "notes": notes, "source_ids": []}
    except HTTPError as exc:
        status = "not_configured" if exc.code in {401, 403} else "unavailable"
        return {"id": f"sh-{name}", "source_group": name, "provider": name, "layer": layer, "status": status, "observed_at": observed, "last_success_at": None, "freshness_budget_hours": budget, "coverage": [], "missing_coverage": [url], "fallback_used": False, "notes": f"HTTP {exc.code}", "source_ids": []}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"id": f"sh-{name}", "source_group": name, "provider": name, "layer": layer, "status": "unavailable", "observed_at": observed, "last_success_at": None, "freshness_budget_hours": budget, "coverage": [], "missing_coverage": [url], "fallback_used": False, "notes": str(exc), "source_ids": []}


def from_search_health(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    observed = payload.get("observed_at") or now()
    engines = payload.get("engines", {})
    rows = []
    for name, probes in engines.items():
        errors = [item.get("error") for item in probes.values() if item.get("error")]
        result_counts = [item.get("result_count", 0) for item in probes.values()]
        any_results = any(result_counts)
        exact = probes.get("exact_name", {})
        footprints = probes.get("footprints", {})
        site = probes.get("site_constraint")
        issues = [str(item) for item in payload.get("interpretation", []) if str(item).startswith(f"{name}:")]
        if errors:
            issues.append(f"{len(errors)} 个探针报错")
        if exact.get("noisy_domain_ratio", 0) >= 0.5:
            issues.append("精确名称结果垃圾域占比过高")
        if site and site.get("result_count", 0) and (site.get("expected_domain_ratio") or 0) < 0.8:
            issues.append("site 约束未可靠落在目标域")
        core_complete = exact.get("result_count", 0) > 0 and footprints.get("result_count", 0) > 0
        site_reliable = not site or (site.get("result_count", 0) > 0 and (site.get("expected_domain_ratio") or 0) >= 0.8)
        clean = exact.get("noisy_domain_ratio", 0) < 0.5
        if not any_results:
            status = "unavailable"
        elif payload.get("recommended_status") == "usable_with_vertical_sources" and not errors and core_complete and site_reliable and clean:
            status = "available"
        else:
            status = "partial"
        if payload.get("recommended_status") == "degraded" and any_results:
            issues.append("整体搜索诊断为 degraded，本引擎仅用于候选发现")
        rows.append({"id": f"sh-search-{name}", "source_group": "search-discovery", "provider": name, "layer": "discovery", "status": status, "observed_at": observed, "last_success_at": observed if any_results else None, "freshness_budget_hours": 24, "coverage": ["候选 URL 发现"] if any_results else [], "missing_coverage": ["稳定的中文垂直检索", "垂直企业级数据"] if status != "available" else ["垂直企业级数据"], "fallback_used": status == "partial", "notes": "; ".join(dict.fromkeys(issues)) or None, "source_ids": []})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, help="JSON array: {name,url,key_env,trusted_origin,layer,budget_hours}")
    parser.add_argument("--search-health", type=Path, help="existing search_health.py JSON output")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.search_health:
        rows = from_search_health(args.search_health)
    elif args.config:
        configs = json.loads(args.config.read_text(encoding="utf-8-sig"))
    else:
        configs = [{"name": "worldmonitor", "url": "https://worldmonitor.app/mcp", "key_env": "WORLD_MONITOR_KEY", "trusted_origin": "https://worldmonitor.app", "layer": "monitoring", "budget_hours": 24}]
    if not args.search_health:
        rows = [probe(item["name"], item["url"], item.get("key_env"), item.get("layer", "monitoring"), float(item.get("budget_hours", 24)), item.get("trusted_origin")) for item in configs]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"generated_at": now(), "source_health": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "sources": len(rows), "statuses": {row["status"]: sum(item["status"] == row["status"] for item in rows) for row in rows}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
