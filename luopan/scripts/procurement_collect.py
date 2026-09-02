#!/usr/bin/env python3
"""Capture low-frequency China Government Procurement search artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import browser_capture
from collection_common import (
    decode_html,
    detect_challenge,
    fetch,
    html_to_text,
    parse_links,
    polite_pause,
    save_artifact,
    utc_now,
    write_json,
)


SEARCH_TEMPLATE = (
    "https://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index={page}"
    "&bidSort=0&buyerName=&projectId=&pinMu=0&bidType=0&dbselect=bidx&kw={query}"
)


def build_queries(company: str, aliases: list[str], products: list[str]) -> list[str]:
    names = [company, *aliases]
    candidates = [*names]
    for name in names:
        candidates.extend([f"{name} 中标", f"{name} 合同", f"{name} 验收"])
    for product in products:
        candidates.extend([f"{company} {product}", f"{product} 中标", f"{product} 验收"])
    return list(dict.fromkeys(item.strip() for item in candidates if item.strip()))


def is_ccgp_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme in {"http", "https"} and (host == "ccgp.gov.cn" or host.endswith(".ccgp.gov.cn"))


def browser_capture_url(url: str, out_dir: Path, timeout: int, *, allow_browser: bool) -> dict:
    """Use the approved dynamic-only fallback; never attempt CAPTCHA solving."""
    return browser_capture.capture(
        url,
        requested_mode="dynamic",
        timeout_ms=timeout * 1000,
        out_dir=out_dir / "browser",
        max_output_bytes=browser_capture.DEFAULT_MAX_OUTPUT_BYTES,
        allow_browser=allow_browser,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--max-queries", type=int, default=8)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=Path("raw/procurement"))
    parser.add_argument("--download-details", action="store_true")
    parser.add_argument("--allow-browser", action="store_true", help="allow the isolated no-cookie dynamic fallback after a public-page challenge")
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    queries = build_queries(args.company, args.alias, args.product)[: max(args.max_queries, 1)]
    records = []
    stop_for_challenge = False

    for query in queries:
        if stop_for_challenge:
            break
        for page in range(1, max(args.pages, 1) + 1):
            url = SEARCH_TEMPLATE.format(page=page, query=quote(query))
            response = fetch(url, args.timeout, allowed_host_suffixes=("ccgp.gov.cn",))
            record = {"query": query, "page": page, "requested_url": url, "retrieved_at": utc_now()}
            content = response.pop("content", b"")
            record.update(response)
            if response.get("ok") and content:
                artifact = save_artifact(out_dir / "search", f"{query}-p{page}", content, ".html.txt")
                record["artifact"] = artifact
                html = decode_html(content, record.get("content_type", ""))
                marker = detect_challenge(html)
                if marker:
                    browser = browser_capture_url(url, out_dir, args.timeout, allow_browser=args.allow_browser)
                    record["browser_fallback"] = browser
                    if browser.get("status") == "captured" and browser.get("captures"):
                        html_artifact = browser["captures"][0].get("html_artifact") or {}
                        artifact_path = html_artifact.get("path")
                        if artifact_path:
                            html = Path(artifact_path).read_text(encoding="utf-8", errors="replace")
                            marker = None
                    if marker:
                        record.update({"result": "manual_required", "challenge_marker": marker, "candidates": []})
                        stop_for_challenge = True
                if not marker:
                    candidates = []
                    seen = set()
                    for link in parse_links(html):
                        absolute = urljoin(record.get("url", url), link["url"])
                        if not is_ccgp_host(absolute) or absolute in seen:
                            continue
                        if not any(token in absolute for token in ("cggg", "ggzy", "notice", "article")):
                            continue
                        seen.add(absolute)
                        candidates.append({"title": link["title"], "url": absolute})
                    text_preview = html_to_text(html)[:500]
                    if candidates:
                        result = "captured"
                    elif text_preview:
                        result = "partial"
                    else:
                        result = "empty"
                    record.update({"result": result, "candidate_count": len(candidates), "candidates": candidates})
                    record["text_preview"] = text_preview
                    if args.download_details:
                        for index, candidate in enumerate(candidates[:20], start=1):
                            detail = fetch(candidate["url"], args.timeout, allowed_host_suffixes=("ccgp.gov.cn",))
                            detail_content = detail.pop("content", b"")
                            candidate["capture"] = detail
                            if detail.get("ok") and detail_content:
                                candidate["artifact"] = save_artifact(
                                    out_dir / "details", f"{query}-{index}-{candidate['title']}", detail_content, ".html.txt"
                                )
                            polite_pause(args.delay)
            else:
                record["result"] = "error"
            records.append(record)
            polite_pause(args.delay)

    if stop_for_challenge:
        status = "manual_required"
    elif any(record.get("result") == "captured" for record in records):
        status = "captured"
    elif any(record.get("result") == "partial" for record in records):
        status = "partial"
    elif any(record.get("result") == "empty" for record in records):
        status = "empty"
    elif records:
        status = "unavailable"
    else:
        status = "no_queries"
    payload = {
        "collector": "government_procurement",
        "status": status,
        "subject": {"company": args.company, "aliases": args.alias, "products": args.product},
        "generated_at": utc_now(),
        "interpretation_warning": "搜索命中、中标或合同公告不等于收入确认、回款或持续复购。",
        "records": records,
    }
    write_json(out_dir / "manifest.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # manual_required is a handled research state, not a collector crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
