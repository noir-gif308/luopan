#!/usr/bin/env python3
"""Optional Firecrawl search adapter with a stable local JSON envelope."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collection_common import read_limited, require_public_network_url


DEFAULT_FIRECRAWL_ORIGIN = "https://api.firecrawl.dev"
SENSITIVE_HEADERS = {"authorization", "x-worldmonitor-key"}
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
MONTHLY_CREDIT_LIMIT = 1000
DEFAULT_USAGE_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Luopan" / "firecrawl-usage.json"


def utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def load_usage(path: Path, month: str) -> dict:
    """Load only the current month's compact credit ledger.

    A malformed or stale ledger fails closed by resetting the accounting month;
    entries never retain response bodies or query text.
    """
    if not path.is_file():
        return {"version": 1, "month": month, "entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "month": month, "entries": []}
    if not isinstance(payload, dict) or payload.get("month") != month or not isinstance(payload.get("entries"), list):
        return {"version": 1, "month": month, "entries": []}
    entries = [
        entry for entry in payload["entries"]
        if isinstance(entry, dict) and isinstance(entry.get("credits"), int) and entry["credits"] >= 0
    ]
    return {"version": 1, "month": month, "entries": entries}


def usage_summary(ledger: dict, limit: int) -> dict:
    used = sum(entry["credits"] for entry in ledger["entries"])
    return {
        "month": ledger["month"],
        "credit_limit": limit,
        "used_credits": used,
        "remaining_credits": max(0, limit - used),
    }


def save_usage(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def url_origin(value: str, *, origin_only: bool = False, allow_private: bool = False) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid URL port: {value}") from exc
    scheme = parsed.scheme.lower()
    if (
        scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"credentialed Firecrawl origins must be HTTPS without user information: {value}")
    if origin_only and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError(f"Firecrawl origin must not contain a path, query, or fragment: {value}")
    if not allow_private:
        require_public_network_url(value)
    return scheme, parsed.hostname.lower(), port or 443


def canonical_origin(origin: tuple[str, str, int]) -> str:
    scheme, host, port = origin
    rendered_host = f"[{host}]" if ":" in host else host
    port_suffix = "" if port == 443 else f":{port}"
    return f"{scheme}://{rendered_host}{port_suffix}"


def authorized_base_url(base_url: str, trusted_origin: str | None = None) -> str:
    base_origin = url_origin(base_url, origin_only=True, allow_private=trusted_origin is not None)
    official_origin = url_origin(DEFAULT_FIRECRAWL_ORIGIN, origin_only=True)
    if trusted_origin is None:
        if base_origin != official_origin:
            raise ValueError("custom --base-url requires a matching --trusted-origin")
    elif base_origin != url_origin(trusted_origin, origin_only=True, allow_private=True):
        raise ValueError("--base-url origin does not match --trusted-origin")
    return canonical_origin(base_origin)


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


def make_search_request(base_url: str, trusted_origin: str | None, api_key: str, payload: dict) -> Request:
    authorized_base = authorized_base_url(base_url, trusted_origin)
    return Request(
        f"{authorized_base}/v2/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--include-domain", action="append", default=[])
    parser.add_argument("--exclude-domain", action="append", default=[])
    parser.add_argument("--country", default="CN")
    parser.add_argument("--location")
    parser.add_argument("--scrape", action="store_true", help="Ask Firecrawl to scrape result pages")
    parser.add_argument("--monthly-credit-limit", type=int, default=MONTHLY_CREDIT_LIMIT, help="hard local stop for the current UTC month's recorded Firecrawl credits")
    parser.add_argument("--usage-file", type=Path, default=DEFAULT_USAGE_FILE, help="compact local monthly credit ledger")
    parser.add_argument("--base-url", default=os.environ.get("FIRECRAWL_BASE_URL", DEFAULT_FIRECRAWL_ORIGIN))
    parser.add_argument("--trusted-origin", help="explicit HTTPS origin allowed to receive the API key")
    args = parser.parse_args()

    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if args.monthly_credit_limit < 1:
        parser.error("--monthly-credit-limit must be positive")
    ledger = load_usage(args.usage_file, utc_month())
    usage = usage_summary(ledger, args.monthly_credit_limit)
    if usage["remaining_credits"] <= 0:
        print(json.dumps({
            "status": "quota_exhausted",
            "reason": "local Firecrawl monthly credit limit reached; request was not sent",
            "query": args.query,
            "usage": usage,
        }, ensure_ascii=False, indent=2))
        return 2
    if not api_key:
        print(json.dumps({
            "status": "not_configured",
            "reason": "FIRECRAWL_API_KEY is not set",
            "query": args.query,
        }, ensure_ascii=False, indent=2))
        return 2

    payload = {
        "query": args.query,
        "limit": args.limit,
        "sources": ["web"],
        "includeDomains": args.include_domain,
        "excludeDomains": args.exclude_domain,
        "country": args.country,
        "timeout": 60000,
        "ignoreInvalidURLs": False,
    }
    if args.location:
        payload["location"] = args.location
    if args.scrape:
        payload["scrapeOptions"] = {"formats": ["markdown"]}

    try:
        request = make_search_request(args.base_url, args.trusted_origin, api_key, payload)
    except ValueError as exc:
        print(json.dumps({"status": "error", "query": args.query, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    try:
        with open_request(request, timeout=70) as response:
            allow_private = args.trusted_origin is not None
            if url_origin(response.geturl(), allow_private=allow_private) != url_origin(
                request.full_url, allow_private=allow_private
            ):
                raise ValueError("Firecrawl redirected to a different origin; response rejected")
            result = json.loads(read_limited(response, MAX_RESPONSE_BYTES).decode("utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "error", "query": args.query, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if not isinstance(result, dict) or result.get("success") is False or result.get("ok") is False or result.get("error"):
        reason = result.get("error") or result.get("message") or "Firecrawl response reported failure" if isinstance(result, dict) else "Firecrawl response root is not an object"
        print(json.dumps({"status": "error", "query": args.query, "error": reason}, ensure_ascii=False, indent=2))
        return 1

    credits_used = result.get("creditsUsed", 0)
    if not isinstance(credits_used, int) or credits_used < 0:
        print(json.dumps({"status": "error", "query": args.query, "error": "Firecrawl response creditsUsed must be a non-negative integer", "usage": usage}, ensure_ascii=False, indent=2))
        return 1
    ledger["entries"].append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "credits": credits_used,
        "request_id": str(result.get("id") or ""),
    })
    save_usage(args.usage_file, ledger)
    usage = usage_summary(ledger, args.monthly_credit_limit)

    print(json.dumps({
        "status": "ok",
        "provider": "firecrawl",
        "query": args.query,
        "request": payload,
        "usage": usage,
        "response": result,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
