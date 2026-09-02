#!/usr/bin/env python3
"""Capture a known public page through the approved dynamic-browser fallback.

This helper deliberately does not solve CAPTCHAs, use stealth mode, reuse
unapproved cookies, or make arbitrary browser profile changes. It invokes the
already-provisioned Scrapling bridge only in `dynamic` mode, captures the
bridge result as a raw artifact, and turns detected access challenges into an
explicit `manual_required` state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from collection_common import (
    detect_challenge,
    host_matches,
    require_public_network_url,
    save_artifact,
    sha256_bytes,
    utc_now,
    write_json,
)

SCRAPLING_PYTHON = Path(os.environ.get("SCRAPLING_PYTHON", ""))
LUOPAN_DYNAMIC_BRIDGE = Path(__file__).with_name("luopan_dynamic_bridge.py")
ALLOWED_MODE = "dynamic"
DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
ACCESS_CONTROL_STATUS = {401, 402, 403}


def safe_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must be an absolute HTTP(S) URL without user information")
    require_public_network_url(value)
    return value


def unavailable_payload(url: str, reason: str) -> dict[str, Any]:
    return {
        "collector": "approved_dynamic_browser",
        "status": "unavailable",
        "requested_url": url,
        "captured_at": utc_now(),
        "capture_mode": ALLOWED_MODE,
        "cookie_mode": "ephemeral",
        "reason": reason,
        "captures": [],
    }


def run_bridge(
    url: str,
    timeout_ms: int,
    max_output_bytes: int,
    allowed_host_suffixes: tuple[str, ...],
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the bundled isolated bridge without buffering its page body in this process."""
    if not SCRAPLING_PYTHON.is_file() or not LUOPAN_DYNAMIC_BRIDGE.is_file():
        return None, "approved Scrapling runtime or bridge is unavailable"
    with tempfile.TemporaryDirectory(prefix="luopan-bridge-result-") as temp:
        output_path = Path(temp) / "capture.json"
        command = [
            str(SCRAPLING_PYTHON), str(LUOPAN_DYNAMIC_BRIDGE), url,
            "--timeout", str(timeout_ms),
            "--max-output-bytes", str(max_output_bytes),
            "--out", str(output_path),
        ]
        for host in allowed_host_suffixes:
            command.extend(("--allowed-host", host))
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(1, timeout_ms // 1000 + 15),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"dynamic browser could not run: {exc}"
        if result.returncode != 0:
            return None, f"dynamic browser exited {result.returncode}"
        try:
            with output_path.open("rb") as handle:
                raw = handle.read(max_output_bytes + 1)
        except OSError as exc:
            return None, f"dynamic browser did not produce a capture result: {exc}"
    if len(raw) > max_output_bytes:
        return None, f"dynamic browser response exceeds {max_output_bytes} byte limit"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"dynamic browser returned invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "dynamic browser returned a non-object payload"
    return payload, None


def capture(
    url: str,
    *,
    requested_mode: str,
    timeout_ms: int,
    out_dir: Path,
    max_output_bytes: int,
    allow_browser: bool = False,
) -> dict[str, Any]:
    captured_at = utc_now()
    if requested_mode != ALLOWED_MODE:
        return {
            "collector": "approved_dynamic_browser",
            "status": "manual_required",
            "requested_url": url,
            "captured_at": captured_at,
            "capture_mode": requested_mode,
            "reason": f"browser mode {requested_mode!r} is not permitted; only {ALLOWED_MODE!r} is allowed",
            "captures": [],
        }
    if not allow_browser:
        return {
            "collector": "approved_dynamic_browser",
            "status": "manual_required",
            "requested_url": url,
            "captured_at": captured_at,
            "capture_mode": ALLOWED_MODE,
            "cookie_mode": "ephemeral",
            "reason": "dynamic browser use requires explicit --allow-browser authorization",
            "captures": [],
        }
    initial_host = (urlparse(url).hostname or "").lower().rstrip(".")
    allowed_host_suffixes = (initial_host,)
    payload, error = run_bridge(url, timeout_ms, max_output_bytes, allowed_host_suffixes)
    if error:
        return unavailable_payload(url, error)
    assert payload is not None
    resolved_url = str(payload.get("resolved_url") or url)
    try:
        safe_public_url(resolved_url)
    except ValueError as exc:
        return {
            "collector": "approved_dynamic_browser",
            "status": "manual_required",
            "requested_url": url,
            "captured_at": captured_at,
            "capture_mode": ALLOWED_MODE,
            "cookie_mode": "ephemeral",
            "reason": f"dynamic browser resolved to an unapproved target: {exc}",
            "captures": [],
        }
    if not host_matches(resolved_url, allowed_host_suffixes):
        return {
            "collector": "approved_dynamic_browser",
            "status": "manual_required",
            "requested_url": url,
            "captured_at": captured_at,
            "capture_mode": ALLOWED_MODE,
            "cookie_mode": "ephemeral",
            "reason": "dynamic browser resolved outside the approved host boundary",
            "captures": [],
        }
    if not payload.get("ok"):
        return unavailable_payload(url, str(payload.get("error") or "dynamic browser could not capture the page"))
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    raw_artifact = save_artifact(out_dir / "raw", "browser-capture", raw, ".json")
    body = str(payload.get("body_text") or "")
    html = str(payload.get("body_html") or "")
    body_artifact = save_artifact(out_dir / "pages", str(payload.get("title") or "page"), body.encode("utf-8"), ".txt") if body else None
    html_artifact = save_artifact(out_dir / "pages", str(payload.get("title") or "page"), html.encode("utf-8"), ".html") if html else None
    challenge = detect_challenge(f"{payload.get('title') or ''}\n{body}\n{html}")
    status_code = payload.get("status")
    if isinstance(status_code, str) and status_code.isdigit():
        status_code = int(status_code)
    if status_code in ACCESS_CONTROL_STATUS:
        challenge = challenge or f"HTTP {status_code} access control"
    status = "captured" if payload.get("ok") and not challenge else "manual_required"
    result = "page_captured" if status == "captured" else "challenge_detected"
    return {
        "collector": "approved_dynamic_browser",
        "status": status,
        "requested_url": url,
        "captured_at": captured_at,
        "capture_mode": ALLOWED_MODE,
        "reason": f"challenge marker detected: {challenge}" if challenge else None,
        "captures": [{
            "requested_url": url,
            "resolved_url": resolved_url,
            "status": payload.get("status"),
            "title": payload.get("title"),
            "capture_backend": payload.get("capture_backend"),
            "cookie_mode": payload.get("cookie_mode") or "ephemeral",
            "result": result,
            "challenge_marker": challenge,
            "raw_artifact": raw_artifact,
            "body_artifact": body_artifact,
            "html_artifact": html_artifact,
            "body_sha256": sha256_bytes(body.encode("utf-8")),
            "body_chars": len(body),
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a public page with the approved dynamic browser fallback.")
    parser.add_argument("url")
    parser.add_argument("--mode", default=ALLOWED_MODE, choices=("dynamic", "stealthy", "fetcher"), help="only dynamic is executed; other values produce manual_required for auditability")
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    parser.add_argument("--allow-browser", action="store_true", help="record explicit authorization for this isolated dynamic capture")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        url = safe_public_url(args.url)
        if args.timeout_ms < 1 or args.max_output_bytes < 1:
            raise ValueError("timeout and max output bytes must be positive")
    except ValueError as exc:
        parser.error(str(exc))
    payload = capture(
        url,
        requested_mode=args.mode,
        timeout_ms=args.timeout_ms,
        out_dir=args.out.parent,
        max_output_bytes=args.max_output_bytes,
        allow_browser=args.allow_browser,
    )
    write_json(args.out, payload)
    print(json.dumps({"out": str(args.out.resolve()), "status": payload["status"], "captures": len(payload["captures"])}, ensure_ascii=False))
    return 0 if payload["status"] == "captured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
