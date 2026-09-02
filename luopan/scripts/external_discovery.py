#!/usr/bin/env python3
"""Discover external URLs from remote indexes without retaining page bodies.

Supported routes are metadata-only candidates:
- Common Crawl CDX: historical URLs for a known domain/pattern.
- Wayback CDX: historical snapshots for a known domain/pattern.
- GDELT Doc API: recent external-news leads for an entity query.

This module deliberately does not fetch candidate pages. Candidates remain
`discovery_only` until source_intake or a reviewed collector captures an
original document.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from collection_common import USER_AGENT, read_limited, utc_now

COMMON_CRAWL_INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-30-index"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_METADATA_BYTES = 8 * 1024 * 1024


def health_row(name: str, provider: str, status: str, observed: str, *, coverage: list[str] | None = None, missing: list[str] | None = None, notes: str | None = None) -> dict[str, Any]:
    return {
        "id": f"sh-{name}", "source_group": name, "provider": provider,
        "layer": "discovery", "status": status, "observed_at": observed,
        "last_success_at": observed if status == "available" else None,
        "freshness_budget_hours": 24 * 30, "coverage": coverage or [],
        "missing_coverage": missing or [], "fallback_used": False,
        "notes": notes, "source_ids": [],
    }


def common_crawl_candidates(rows: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("original") or row.get("url") or "")
        timestamp = str(row.get("timestamp") or "")
        if not url or not timestamp or str(row.get("status") or "") != "200" or url in seen:
            continue
        seen.add(url)
        mime = str(row.get("mime") or "")
        candidates.append({
            "url": url,
            "title": url,
            "discovery_method": "archive_url_index",
            "source_url": COMMON_CRAWL_INDEX,
            "media_type": mime or None,
            "external_id": timestamp,
            "published_at": None,
            "verification": "discovery_only",
            "archive": {"provider": "Common Crawl", "pattern": pattern, "timestamp": timestamp, "digest": row.get("digest"), "length": row.get("length")},
        })
    return candidates


def curl_text(url: str, timeout: int) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout), url], capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
    except OSError as exc:
        return None, str(exc)
    if completed.returncode not in {0, 28}:
        return None, completed.stderr.strip()[:500] or f"curl exited {completed.returncode}"
    if len(completed.stdout.encode("utf-8")) > MAX_METADATA_BYTES:
        return None, f"response exceeds {MAX_METADATA_BYTES} byte limit"
    return completed.stdout, None


def discover_common_crawl(pattern: str, *, limit: int, timeout: int) -> dict[str, Any]:
    observed = utc_now()
    if not pattern.strip():
        raise ValueError("Common Crawl pattern must be non-empty")
    params = [("url", pattern), ("output", "json"), ("filter", "status:200"), ("filter", "mime:text/html"), ("collapse", "urlkey"), ("limit", str(limit))]
    url = f"{COMMON_CRAWL_INDEX}?{urlencode(params)}"
    text, error = curl_text(url, timeout)
    if error:
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("common-crawl", "Common Crawl CDX", "unavailable", observed, missing=[url], notes=error)], "transport": {}}
    rows: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    candidates = common_crawl_candidates(rows, pattern)
    status = "available" if candidates else "partial"
    notes = f"{len(candidates)} metadata-only URL candidate(s) returned from remote archive index." if candidates else "Remote archive query returned no matching HTML metadata."
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("common-crawl", "Common Crawl CDX", status, observed, coverage=[url] if candidates else [], missing=[] if candidates else [pattern], notes=notes)], "transport": {"index": COMMON_CRAWL_INDEX}}


def discover_wayback(pattern: str, *, limit: int, timeout: int) -> dict[str, Any]:
    observed = utc_now()
    params = [("url", pattern), ("output", "json"), ("filter", "statuscode:200"), ("filter", "mimetype:text/html"), ("collapse", "urlkey"), ("fl", "timestamp,original,statuscode,mimetype,digest,length"), ("limit", str(limit))]
    url = f"{WAYBACK_CDX}?{urlencode(params)}"
    text, error = curl_text(url, timeout)
    if error:
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("wayback", "Wayback CDX", "unavailable", observed, missing=[url], notes=error)], "transport": {}}
    try:
        rows = json.loads(text or "[]")
    except json.JSONDecodeError as exc:
        rows, error = [], f"Wayback CDX payload could not be parsed: {exc}"
    candidates: list[dict[str, Any]] = []
    if isinstance(rows, list) and rows:
        headers = rows[0] if isinstance(rows[0], list) else []
        for values in rows[1:]:
            if not isinstance(values, list) or len(values) != len(headers):
                continue
            row = dict(zip(headers, values))
            original = str(row.get("original") or "")
            timestamp = str(row.get("timestamp") or "")
            if not original or not timestamp:
                continue
            candidates.append({"url": original, "title": original, "discovery_method": "archive_url_index", "source_url": WAYBACK_CDX, "media_type": str(row.get("mimetype") or None), "external_id": timestamp, "published_at": None, "verification": "discovery_only", "archive": {"provider": "Wayback", "pattern": pattern, "timestamp": timestamp, "digest": row.get("digest"), "length": row.get("length")}})
    status = "available" if candidates else "partial"
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("wayback", "Wayback CDX", status, observed, coverage=[url] if candidates else [], missing=[] if candidates else [pattern], notes=f"{len(candidates)} metadata-only snapshot URL candidate(s) returned." if candidates else error or "Wayback returned no matching snapshot metadata.")], "transport": {}}


def discover_gdelt(query: str, *, days: int, limit: int, timeout: int) -> dict[str, Any]:
    observed = utc_now()
    if not query.strip() or not 1 <= days <= 90:
        raise ValueError("GDELT query must be non-empty and days must be between 1 and 90")
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": min(limit, 250), "timespan": f"{days}d"}
    url = f"{GDELT_DOC_API}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content = read_limited(response, MAX_METADATA_BYTES)
        payload = json.loads(content.decode("utf-8"))
    except Exception as exc:
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("gdelt", "GDELT Doc API", "unavailable", observed, missing=[url], notes=str(exc)[:500])], "transport": {}}
    candidates = []
    seen: set[str] = set()
    for item in payload.get("articles", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("url") or item["url"] in seen:
            continue
        seen.add(item["url"])
        candidates.append({"url": item["url"], "title": item.get("title") or item["url"], "discovery_method": "external_news_index", "source_url": url, "media_type": "text/html", "external_id": item.get("url"), "published_at": item.get("seendate"), "verification": "discovery_only", "publisher": item.get("domain"), "language": item.get("language")})
    status = "available" if candidates else "partial"
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("gdelt", "GDELT Doc API", status, observed, coverage=[url] if candidates else [], missing=[] if candidates else [query], notes=f"{len(candidates)} external-news URL candidate(s) returned; news leads require original-page verification." if candidates else "GDELT returned no article metadata for this query/window.")], "transport": {}}


def write_json(path: str, payload: dict[str, Any]) -> None:
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover remote URL metadata without downloading page bodies.")
    commands = parser.add_subparsers(dest="command", required=True)
    cc = commands.add_parser("common-crawl")
    cc.add_argument("pattern", help="known domain/pattern, e.g. example.com/*")
    cc.add_argument("--limit", type=int, default=1000)
    cc.add_argument("--timeout", type=int, default=45)
    cc.add_argument("--out", required=True)
    wb = commands.add_parser("wayback")
    wb.add_argument("pattern")
    wb.add_argument("--limit", type=int, default=1000)
    wb.add_argument("--timeout", type=int, default=45)
    wb.add_argument("--out", required=True)
    gdelt = commands.add_parser("gdelt")
    gdelt.add_argument("query")
    gdelt.add_argument("--days", type=int, default=90)
    gdelt.add_argument("--limit", type=int, default=250)
    gdelt.add_argument("--timeout", type=int, default=45)
    gdelt.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "common-crawl":
            payload = discover_common_crawl(args.pattern, limit=args.limit, timeout=args.timeout)
        elif args.command == "wayback":
            payload = discover_wayback(args.pattern, limit=args.limit, timeout=args.timeout)
        else:
            payload = discover_gdelt(args.query, days=args.days, limit=args.limit, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    write_json(args.out, payload)
    print(json.dumps({"out": args.out, "candidates": len(payload["candidates"]), "status": payload["source_health"][0]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
