#!/usr/bin/env python3
"""Discover and preserve government-hosted company PDFs with provenance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from collection_common import (
    decode_html,
    detect_challenge,
    fetch,
    parse_links,
    polite_pause,
    save_artifact,
    utc_now,
    write_json,
)


GOV_SUFFIXES = (".gov.cn", ".gov.hk", ".gov.mo")
JUNK_HOSTS = ("wikipedia.org", "instagram.com", "baidu.com", "zhihu.com", "wanmei.com")


def is_government_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme in {"http", "https"} and any(host.endswith(suffix) for suffix in GOV_SUFFIXES)


def is_html_document(content: bytes, content_type: str) -> bool:
    prefix = content[:512].lstrip().lower()
    return "html" in content_type or prefix.startswith((b"<!doctype html", b"<html", b"<?xml"))


def is_query_relevant(item: dict, company: str, keywords: list[str]) -> bool:
    haystack = f"{item.get('title', '')} {item.get('content', '')} {item.get('url', '')}".lower()
    compact_company = re.sub(r"(有限责任公司|股份有限公司|有限公司|集团|公司)$", "", company).strip().lower()
    company_ok = company.lower() in haystack or (len(compact_company) >= 4 and compact_company in haystack)
    keyword_ok = any(keyword.lower() in haystack for keyword in keywords)
    return company_ok and keyword_ok


def searx_search(base_url: str, query: str, timeout: int) -> dict:
    url = f"{base_url.rstrip('/')}/search?q={quote(query)}&format=json&language=zh-CN"
    response = fetch(url, timeout)
    content = response.pop("content", b"")
    response["requested_url"] = url
    if not response.get("ok") or not content:
        return {**response, "results": []}
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {**response, "error": f"invalid search JSON: {exc}", "results": []}
    response["results"] = payload.get("results", [])
    return response


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--address", default="")
    parser.add_argument("--searxng", default="http://127.0.0.1:8080")
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=Path("raw/government-pdf"))
    parser.add_argument("--no-follow-pages", action="store_true")
    parser.add_argument("--url", action="append", default=[], help="Known government page or PDF URL to capture directly")
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    keywords = args.keyword or ["环评", "能评", "排污许可", "项目公示"]
    queries = [f'"{args.company}" {keyword} filetype:pdf' for keyword in keywords]
    if args.address:
        queries.append(f'"{args.address}" 环评 filetype:pdf')

    searches = []
    candidates: list[dict] = []
    seen = set()
    for url in args.url:
        if not is_government_host(url):
            searches.append({"query": "direct_url", "ok": False, "error": "direct URL is not on a government domain", "url": url})
            continue
        seen.add(url)
        candidates.append({"title": args.company, "url": url, "query": "direct_url", "engine": "direct"})
    for query in queries:
        result = searx_search(args.searxng, query, args.timeout)
        searches.append({key: value for key, value in result.items() if key != "results"} | {"query": query})
        raw_results = result.get("results", [])
        government_count = 0
        relevant_count = 0
        junk_count = 0
        for item in raw_results:
            url = item.get("url", "")
            host = (urlparse(url).hostname or "").lower()
            if any(host.endswith(junk) for junk in JUNK_HOSTS):
                junk_count += 1
            if not url or url in seen or not is_government_host(url):
                continue
            government_count += 1
            if not is_query_relevant(item, args.company, keywords):
                continue
            relevant_count += 1
            seen.add(url)
            candidates.append({"title": item.get("title", ""), "url": url, "query": query, "engine": item.get("engine")})
            if len(candidates) >= args.max_results:
                break
        searches[-1].update({
            "raw_result_count": len(raw_results),
            "government_result_count": government_count,
            "relevant_result_count": relevant_count,
            "junk_result_count": junk_count,
        })
        polite_pause(args.delay)

    captures = []
    for candidate in candidates[: args.max_results]:
        response = fetch(candidate["url"], args.timeout, allowed_host_suffixes=GOV_SUFFIXES)
        content = response.pop("content", b"")
        capture = {**candidate, **response, "retrieved_at": utc_now()}
        if not response.get("ok") or not content:
            capture["result"] = "error"
            captures.append(capture)
            continue
        content_type = capture.get("content_type", "").lower()
        is_pdf = content.startswith(b"%PDF")
        if is_pdf:
            capture["artifact"] = save_artifact(out_dir / "pdf", candidate["title"] or args.company, content, ".pdf")
            capture["result"] = "pdf_captured"
        elif is_html_document(content, content_type):
            html = decode_html(content, content_type)
            marker = detect_challenge(html)
            capture["artifact"] = save_artifact(out_dir / "pages", candidate["title"] or args.company, content, ".html.txt")
            if marker:
                capture.update({"result": "manual_required", "challenge_marker": marker})
            elif args.no_follow_pages:
                capture["result"] = "page_captured"
            else:
                pdf_links = []
                for link in parse_links(html):
                    absolute = urljoin(capture.get("url", candidate["url"]), link["url"])
                    if absolute.lower().split("?")[0].endswith(".pdf") and is_government_host(absolute):
                        pdf_links.append({"title": link["title"], "url": absolute})
                capture["pdf_links"] = pdf_links
                capture["result"] = "page_captured"
                for index, link in enumerate(pdf_links[:10], start=1):
                    detail = fetch(link["url"], args.timeout, allowed_host_suffixes=GOV_SUFFIXES)
                    detail_content = detail.pop("content", b"")
                    link["capture"] = detail
                    if detail.get("ok") and detail_content.startswith(b"%PDF"):
                        link["artifact"] = save_artifact(
                            out_dir / "pdf", f"{candidate['title']}-{index}-{link['title']}", detail_content, ".pdf"
                        )
                        link["capture"]["result"] = "pdf_captured"
                    elif detail_content:
                        link["capture"]["result"] = "invalid_pdf_magic"
                    polite_pause(args.delay)
        else:
            capture["result"] = "invalid_document"
            capture["error"] = "response is neither PDF magic bytes nor an HTML page"
        captures.append(capture)
        polite_pause(args.delay)

    has_direct_candidates = any(item.get("engine") == "direct" for item in candidates)
    if not has_direct_candidates and not any(search.get("ok") for search in searches):
        status = "search_unavailable"
    elif not candidates:
        misleading_searches = any(
            item.get("raw_result_count", 0) > 0 and item.get("relevant_result_count", 0) == 0
            for item in searches
        )
        status = "search_degraded" if misleading_searches else "no_government_candidates"
    else:
        captured = any(item.get("result") in {"pdf_captured", "page_captured"} for item in captures)
        manual_required = any(item.get("result") == "manual_required" for item in captures)
        if manual_required and captured:
            status = "partial_manual_required"
        elif manual_required:
            status = "manual_required"
        elif captured:
            status = "captured"
        else:
            status = "capture_failed"
    if candidates and not captures:
        status = "capture_failed"
    payload = {
        "collector": "government_pdf",
        "status": status,
        "subject": {"company": args.company, "address": args.address, "keywords": keywords},
        "generated_at": utc_now(),
        "interpretation_warning": "环评、能评或项目批复中的设备和产能是获批/理论边界，不等于实际投产、利用率或销量。",
        "searches": searches,
        "captures": captures,
    }
    write_json(out_dir / "manifest.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Non-captured states are explicit outputs for workflow routing, not crashes.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
