#!/usr/bin/env python3
"""Run one isolated Scrapling dynamic capture for Luopan.

This bridge is intentionally bundled with Luopan rather than delegating to a
mutable shared bridge. Each invocation creates and destroys its own empty
browser profile, allows requests only to the approved public host boundary,
and writes a bounded JSON result for ``browser_capture.py`` to inspect.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from collection_common import host_matches, require_public_network_url


DEDICATED_CHROMIUM = Path(os.environ.get("LUOPAN_CHROMIUM", ""))
GOOGLE_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
MIN_OUTPUT_BYTES = 4 * 1024


def browser_executable() -> str:
    if DEDICATED_CHROMIUM.is_file():
        return str(DEDICATED_CHROMIUM)
    return str(GOOGLE_CHROME)


def truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    if limit <= 0:
        return ""
    return encoded[:limit].decode("utf-8", errors="ignore")


def allowed_request_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        if not host_matches(url, allowed_hosts):
            return False
        require_public_network_url(url)
        return True
    except ValueError:
        return False


def page_setup_for(allowed_hosts: tuple[str, ...]):
    def page_setup(page: Any) -> None:
        def route_request(route: Any) -> None:
            if allowed_request_url(str(route.request.url), allowed_hosts):
                route.continue_()
            else:
                route.abort()

        page.route("**/*", route_request)

    return page_setup


def response_text(page: Any) -> str:
    getter = getattr(page, "get_all_text", None)
    if callable(getter):
        try:
            value = getter()
            if isinstance(value, str):
                return value.strip()
        except Exception:
            pass
    return str(getattr(page, "text", "") or "").strip()


def response_html(page: Any) -> str:
    for attribute in ("html_content", "body"):
        value = getattr(page, attribute, None)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if value is not None:
            rendered = str(value)
            if rendered:
                return rendered
    return ""


def bounded_json(payload: dict[str, Any], max_output_bytes: int) -> bytes:
    # Leave space for metadata and retain both rendered text and raw HTML.
    per_body_limit = max(0, (max_output_bytes - 4 * 1024) // 2)
    for key in ("title", "resolved_url", "error"):
        payload[key] = truncate_utf8(str(payload.get(key) or ""), 1024)
    for key in ("body_text", "body_html"):
        payload[key] = truncate_utf8(str(payload.get(key) or ""), per_body_limit)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) <= max_output_bytes:
        return raw

    # Metadata can still exceed a very small custom limit. Fail closed while
    # retaining a diagnostic instead of writing an unbounded process result.
    payload["body_text"] = ""
    payload["body_html"] = ""
    payload["output_truncated"] = True
    payload["error"] = "browser result exceeded the configured output limit"
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > max_output_bytes:
        raise ValueError("configured output limit is too small for the capture envelope")
    return raw


def capture(url: str, *, allowed_hosts: tuple[str, ...], timeout_ms: int, max_output_bytes: int) -> dict[str, Any]:
    from scrapling.fetchers import DynamicFetcher

    with tempfile.TemporaryDirectory(prefix="luopan-browser-") as profile:
        page = DynamicFetcher.fetch(
            url,
            executable_path=browser_executable(),
            user_data_dir=profile,
            headless=True,
            timeout=timeout_ms,
            disable_resources=True,
            block_ads=True,
            google_search=False,
            page_setup=page_setup_for(allowed_hosts),
        )
        resolved_url = str(getattr(page, "url", "") or url)
        if not allowed_request_url(resolved_url, allowed_hosts):
            return {
                "ok": False,
                "error": "browser navigation left the approved public host boundary",
                "resolved_url": resolved_url,
                "capture_mode": "dynamic",
                "cookie_mode": "ephemeral",
                "body_text": "",
                "body_html": "",
            }
        title = ""
        try:
            title = str(page.css("title::text").get() or "")
        except Exception:
            pass
        return {
            "ok": True,
            "resolved_url": resolved_url,
            "capture_backend": "scrapling",
            "capture_mode": "dynamic",
            "cookie_mode": "ephemeral",
            "status": getattr(page, "status", None),
            "title": title,
            "body_text": response_text(page),
            "body_html": response_html(page),
            "error": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated Luopan dynamic-browser capture.")
    parser.add_argument("url")
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--timeout", type=int, default=45_000)
    parser.add_argument("--max-output-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("timeout must be positive")
    if args.max_output_bytes < MIN_OUTPUT_BYTES:
        parser.error(f"max-output-bytes must be at least {MIN_OUTPUT_BYTES}")
    allowed_hosts = tuple(str(item).lower().lstrip(".").rstrip(".") for item in args.allowed_host if item.strip())
    if not allowed_hosts or not allowed_request_url(args.url, allowed_hosts):
        parser.error("URL is outside the approved public host boundary")
    try:
        payload = capture(args.url, allowed_hosts=allowed_hosts, timeout_ms=args.timeout, max_output_bytes=args.max_output_bytes)
    except Exception as exc:
        payload = {
            "ok": False,
            "error": f"dynamic browser failed: {exc}",
            "resolved_url": args.url,
            "capture_mode": "dynamic",
            "cookie_mode": "ephemeral",
            "body_text": "",
            "body_html": "",
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bounded_json(payload, args.max_output_bytes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
