#!/usr/bin/env python3
"""Discover official feeds and SEC filing metadata without creating a content corpus.

This is an intake tool: every returned candidate remains discovery-only until a
research run retrieves the original item and creates atomic evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collection_common import USER_AGENT, read_limited, require_public_network_url


FEED_MIME_MARKERS = ("rss", "atom", "jsonfeed", "feed+json")
FEED_REL_MARKERS = {"alternate", "feed"}
MAX_DISCOVERY_BYTES = 2 * 1024 * 1024
HKEX_HOST = "www1.hkexnews.hk"
HKEX_STOCKS_URL = f"https://{HKEX_HOST}/ncms/script/eds/activestock_sehk_e.json"
HKEX_SEARCH_URL = f"https://{HKEX_HOST}/search/titleSearchServlet.do"
CNINFO_HOST = "www.cninfo.com.cn"
CNINFO_QUERY_URL = f"https://{CNINFO_HOST}/new/hisAnnouncement/query"
CNINFO_STATIC_HOST = "https://static.cninfo.com.cn"
SEC_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


class FeedLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        row = {str(key).lower(): str(value or "") for key, value in attrs}
        href = row.get("href", "").strip()
        rel = {part.casefold() for part in row.get("rel", "").split()}
        media_type = row.get("type", "").casefold()
        if href and (rel & FEED_REL_MARKERS) and any(marker in media_type for marker in FEED_MIME_MARKERS):
            self.links.append({"href": href, "title": row.get("title", ""), "type": media_type})


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def host(value: str) -> str:
    return (urlsplit(value).hostname or "").casefold().rstrip(".")


def same_or_subdomain(candidate: str, root: str) -> bool:
    return candidate == root or candidate.endswith(f".{root}")


def safe_site_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("site URL must be an absolute HTTP(S) URL without user information")
    require_public_network_url(value)
    return value


class SiteRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_host: str) -> None:
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        old_scheme = urlsplit(req.full_url).scheme.casefold()
        new_scheme = urlsplit(newurl).scheme.casefold()
        if old_scheme == "https" and new_scheme != "https":
            raise HTTPError(newurl, 403, "HTTPS downgrade redirect is forbidden", headers, fp)
        if not same_or_subdomain(host(newurl), self.allowed_host):
            raise HTTPError(newurl, 403, "redirect left the source host boundary", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, *, allowed_host: str, timeout: int = 20, max_bytes: int = MAX_DISCOVERY_BYTES) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,application/rss+xml,application/atom+xml,text/html;q=0.9,*/*;q=0.1"})
    opener = build_opener(SiteRedirectHandler(allowed_host))
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not same_or_subdomain(host(final_url), allowed_host):
                return {"ok": False, "status": response.status, "final_url": final_url, "error": "response left the source host boundary", "content": b""}
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return {"ok": False, "status": response.status, "final_url": final_url, "error": f"response exceeds {max_bytes} byte limit", "content": b""}
            return {
                "ok": True,
                "status": response.status,
                "final_url": final_url,
                "content_type": response.headers.get("Content-Type", ""),
                "headers": {"ETag": response.headers.get("ETag", ""), "Last-Modified": response.headers.get("Last-Modified", "")},
                "content": read_limited(response, max_bytes),
            }
    except HTTPError as exc:
        return {"ok": False, "status": exc.code, "final_url": getattr(exc, "url", url), "error": f"HTTP {exc.code}", "content": b""}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "status": None, "final_url": url, "error": str(exc), "content": b""}


def health_row(name: str, provider: str, status: str, observed_at: str, *, coverage: list[str] | None = None, missing: list[str] | None = None, notes: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"sh-{name}",
        "source_group": name,
        "provider": provider,
        "layer": "discovery",
        "status": status,
        "observed_at": observed_at,
        "last_success_at": observed_at if status == "available" else None,
        "freshness_budget_hours": 24,
        "coverage": coverage or [],
        "missing_coverage": missing or [],
        "fallback_used": False,
        "notes": notes,
        "source_ids": [],
    }
    return row


def discover_site_feeds(site_url: str, *, include_common_paths: bool = True) -> dict[str, Any]:
    site_url = safe_site_url(site_url)
    root_host = host(site_url)
    observed = now()
    response = fetch_url(site_url, allowed_host=root_host)
    if not response.get("ok"):
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("official-feed", root_host, "unavailable", observed, missing=[site_url], notes=str(response.get("error")))], "transport": {"etag": None, "last_modified": None}}

    final_url = str(response["final_url"])
    parser = FeedLinkParser()
    parser.feed(response["content"].decode("utf-8", errors="replace"))
    candidates: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for item in parser.links:
        resolved = urljoin(final_url, item["href"])
        if not same_or_subdomain(host(resolved), root_host):
            rejected.append(resolved)
            continue
        if resolved not in seen:
            seen.add(resolved)
            candidates.append({"url": resolved, "title": item["title"] or f"{root_host} declared feed", "discovery_method": "html_link", "source_url": final_url, "media_type": item["type"], "external_id": None, "published_at": None, "verification": "discovery_only"})

    # A declared but off-domain feed is an explicit provenance boundary failure.
    # Do not mask it with guessed paths; require review or an approved resolver.
    if not candidates and include_common_paths and not rejected:
        for path in ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/feed.xml"):
            resolved = urljoin(final_url, path)
            if resolved not in seen:
                seen.add(resolved)
                candidates.append({"url": resolved, "title": f"{root_host} conventional feed candidate", "discovery_method": "conventional_path", "source_url": final_url, "media_type": None, "external_id": None, "published_at": None, "verification": "discovery_only"})

    status = "available" if any(item["discovery_method"] == "html_link" for item in candidates) else "partial"
    notes = None
    if rejected:
        notes = f"{len(rejected)} declared feed URL(s) outside the source host boundary were rejected."
    if status == "partial" and not notes:
        notes = "No declared RSS/Atom/JSON Feed link found; conventional paths are discovery candidates only."
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("official-feed", root_host, status, observed, coverage=[final_url] if status == "available" else [], missing=[] if status == "available" else ["declared feed"], notes=notes)], "transport": {"etag": response["headers"].get("ETag") or None, "last_modified": response["headers"].get("Last-Modified") or None}}


def post_form_url(url: str, data: dict[str, str], *, allowed_host: str, timeout: int = 20, max_bytes: int = MAX_DISCOVERY_BYTES) -> dict[str, Any]:
    """POST a bounded form request while enforcing the declared source host."""
    from urllib.parse import urlencode

    request = Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json,text/plain,*/*;q=0.1",
        },
    )
    opener = build_opener(SiteRedirectHandler(allowed_host))
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not same_or_subdomain(host(final_url), allowed_host):
                return {"ok": False, "status": response.status, "final_url": final_url, "error": "response left the source host boundary", "content": b""}
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return {"ok": False, "status": response.status, "final_url": final_url, "error": f"response exceeds {max_bytes} byte limit", "content": b""}
            return {"ok": True, "status": response.status, "final_url": final_url, "content_type": response.headers.get("Content-Type", ""), "headers": {"ETag": response.headers.get("ETag", ""), "Last-Modified": response.headers.get("Last-Modified", "")}, "content": read_limited(response, max_bytes)}
    except HTTPError as exc:
        return {"ok": False, "status": exc.code, "final_url": getattr(exc, "url", url), "error": f"HTTP {exc.code}", "content": b""}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "status": None, "final_url": url, "error": str(exc), "content": b""}


def exchange_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("date must be a valid YYYYMMDD calendar date") from exc
    return value


def hkex_code(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if not digits or len(digits) > 5:
        raise ValueError("HKEX code must contain 1-5 digits")
    return digits.zfill(5)


def parse_json_response(response: dict[str, Any], label: str) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    if not response.get("ok"):
        return None, str(response.get("error"))
    try:
        return json.loads(response["content"].decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{label} payload could not be parsed: {exc}"


def discover_hkex_filings(code: str, from_date: str, to_date: str, *, limit: int = 100) -> dict[str, Any]:
    """Discover HKEX filing metadata; never download documents or store their bodies."""
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    code, from_date, to_date = hkex_code(code), exchange_date(from_date), exchange_date(to_date)
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    observed = now()
    stocks_response = fetch_url(HKEX_STOCKS_URL, allowed_host=HKEX_HOST)
    stocks, error = parse_json_response(stocks_response, "HKEX stock list")
    if not isinstance(stocks, list):
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("hkex-filings", "HKEX listed-company search", "unavailable", observed, missing=[HKEX_STOCKS_URL], notes=error)], "transport": {"etag": None, "last_modified": None}}
    stock_id = next((str(item.get("i")) for item in stocks if isinstance(item, dict) and str(item.get("c", "")).zfill(5) == code), None)
    if not stock_id:
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("hkex-filings", "HKEX listed-company search", "partial", observed, missing=[f"listed code {code}"], notes="Stock code was not present in HKEX active-stock metadata.")], "transport": {"etag": stocks_response.get("headers", {}).get("ETag") or None, "last_modified": stocks_response.get("headers", {}).get("Last-Modified") or None}}
    params = {"sortDir": "1", "sortByOptions": "DateTime", "category": "0", "market": "SEHK", "stockId": stock_id, "documentType": "-1", "fromDate": from_date, "toDate": to_date, "title": "", "searchType": "0", "t1code": "", "t2Gcode": "", "t2code": "", "rowRange": str(limit), "lang": "E"}
    query = "&".join(f"{key}={value}" for key, value in params.items())
    search_response = fetch_url(f"{HKEX_SEARCH_URL}?{query}", allowed_host=HKEX_HOST)
    payload, error = parse_json_response(search_response, "HKEX filing search")
    if not isinstance(payload, dict):
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("hkex-filings", "HKEX listed-company search", "unavailable", observed, missing=[HKEX_SEARCH_URL], notes=error)], "transport": {"etag": search_response.get("headers", {}).get("ETag") or None, "last_modified": search_response.get("headers", {}).get("Last-Modified") or None}}
    try:
        rows = json.loads(payload.get("result", "[]"))
    except (TypeError, json.JSONDecodeError) as exc:
        rows, error = [], f"HKEX result field could not be parsed: {exc}"
    candidates = []
    for item in rows[:limit]:
        if not isinstance(item, dict) or not item.get("FILE_LINK") or not item.get("NEWS_ID"):
            continue
        url = urljoin(f"https://{HKEX_HOST}/", str(item["FILE_LINK"]))
        candidates.append({"url": url, "title": str(item.get("TITLE") or item.get("SHORT_TEXT") or f"HKEX filing {item['NEWS_ID']}"), "discovery_method": "official_exchange_search", "source_url": HKEX_SEARCH_URL, "media_type": "application/pdf" if url.casefold().endswith(".pdf") else None, "external_id": str(item["NEWS_ID"]), "published_at": str(item.get("DATE_TIME") or "") or None, "verification": "discovery_only"})
    status = "available" if candidates else "partial"
    notes = f"{len(candidates)} filing metadata item(s) returned; HKEX NEWS_ID is the incremental identifier." if candidates else (error or "HKEX query returned no filing metadata for this code/date window.")
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("hkex-filings", "HKEX listed-company search", status, observed, coverage=[HKEX_SEARCH_URL] if candidates else [], missing=[] if candidates else [f"filings for {code} {from_date}-{to_date}"], notes=notes)], "transport": {"etag": search_response.get("headers", {}).get("ETag") or None, "last_modified": search_response.get("headers", {}).get("Last-Modified") or None}}


def discover_cninfo_announcements(code: str, org_id: str, from_date: str, to_date: str, *, limit: int = 30) -> dict[str, Any]:
    """Discover CNINFO disclosure metadata for a known official code/orgId pair."""
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("CNINFO code must contain exactly 6 digits")
    if not org_id or any(char.isspace() for char in org_id):
        raise ValueError("CNINFO org_id must be non-empty and contain no whitespace")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    from_date, to_date = exchange_date(from_date), exchange_date(to_date)
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    observed = now()
    dates = f"{from_date[:4]}-{from_date[4:6]}-{from_date[6:]}~{to_date[:4]}-{to_date[4:6]}-{to_date[6:]}"
    data = {"pageNum": "1", "pageSize": str(limit), "column": "szse", "tabName": "fulltext", "plate": "", "stock": f"{code},{org_id}", "searchkey": "", "secid": "", "category": "", "trade": "", "seDate": dates, "sortName": "", "sortType": "", "isHLtitle": "true"}
    response = post_form_url(CNINFO_QUERY_URL, data, allowed_host=CNINFO_HOST)
    payload, error = parse_json_response(response, "CNINFO announcement search")
    if not isinstance(payload, dict):
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("cninfo-filings", "CNINFO disclosure search", "unavailable", observed, missing=[CNINFO_QUERY_URL], notes=error)], "transport": {"etag": None, "last_modified": None}}
    candidates = []
    for item in payload.get("announcements") or []:
        if not isinstance(item, dict) or not item.get("announcementId") or not item.get("adjunctUrl"):
            continue
        path = str(item["adjunctUrl"]).lstrip("/")
        url = f"{CNINFO_STATIC_HOST}/{path}"
        published_at = None
        if item.get("announcementTime"):
            published_at = datetime.fromtimestamp(float(item["announcementTime"]) / 1000, tz=ZoneInfo("Asia/Shanghai")).isoformat()
        candidates.append({"url": url, "title": str(item.get("announcementTitle") or f"CNINFO announcement {item['announcementId']}"), "discovery_method": "official_disclosure_query", "source_url": CNINFO_QUERY_URL, "media_type": "application/pdf" if path.casefold().endswith(".pdf") else None, "external_id": str(item["announcementId"]), "published_at": published_at, "verification": "discovery_only"})
    status = "available" if candidates else "partial"
    notes = f"{len(candidates)} announcement metadata item(s) returned; announcementId is the incremental identifier." if candidates else "CNINFO query returned no announcement metadata for this code/date window."
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("cninfo-filings", "CNINFO disclosure search", status, observed, coverage=[CNINFO_QUERY_URL] if candidates else [], missing=[] if candidates else [f"announcements for {code} {from_date}-{to_date}"], notes=notes)], "transport": {"etag": response.get("headers", {}).get("ETag") or None, "last_modified": response.get("headers", {}).get("Last-Modified") or None}}


def sec_fetch_url(url: str, *, allowed_host: str, timeout: int = 20, max_bytes: int = MAX_DISCOVERY_BYTES) -> dict[str, Any]:
    """Fetch SEC data with a distinct descriptive User-Agent as SEC requires."""
    request = Request(
        url,
        headers={
            "User-Agent": f"{USER_AGENT} research-contact: local-only",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        },
    )
    opener = build_opener(SiteRedirectHandler(allowed_host))
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not same_or_subdomain(host(final_url), allowed_host):
                return {"ok": False, "status": response.status, "final_url": final_url, "error": "response left the SEC host boundary", "content": b""}
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return {"ok": False, "status": response.status, "final_url": final_url, "error": f"response exceeds {max_bytes} byte limit", "content": b""}
            return {"ok": True, "status": response.status, "final_url": final_url, "content_type": response.headers.get("Content-Type", ""), "headers": {"ETag": response.headers.get("ETag", ""), "Last-Modified": response.headers.get("Last-Modified", "")}, "content": read_limited(response, max_bytes)}
    except HTTPError as exc:
        return {"ok": False, "status": exc.code, "final_url": getattr(exc, "url", url), "error": f"HTTP {exc.code}", "content": b""}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "status": None, "final_url": url, "error": str(exc), "content": b""}


def sec_cik(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if not digits or len(digits) > 10:
        raise ValueError("CIK must contain 1-10 digits")
    return digits.zfill(10)


def resolve_sec_ticker(ticker: str) -> dict[str, str]:
    """Resolve a US-listed ticker through SEC's official exchange mapping.

    This is entity resolution only. It avoids accepting a guessed CIK, which
    previously produced a false Xiaomi-to-SEC linkage. The mapping is fetched
    on demand and is never treated as a research fact or a filing source.
    """
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z.\-]{1,12}", normalized):
        raise ValueError("SEC ticker must contain 1-12 letters, dots, or hyphens")
    response = sec_fetch_url(SEC_TICKERS_EXCHANGE_URL, allowed_host="www.sec.gov")
    if not response.get("ok"):
        raise ValueError(f"SEC ticker mapping is unavailable: {response.get('error')}")
    try:
        payload = json.loads(response["content"].decode("utf-8"))
        fields = payload["fields"]
        rows = payload["data"]
        indices = {str(name): index for index, name in enumerate(fields)}
        match = next(
            row for row in rows
            if isinstance(row, list)
            and len(row) > indices["ticker"]
            and str(row[indices["ticker"]]).upper() == normalized
        )
        cik_value = str(match[indices["cik"]])
        return {
            "ticker": str(match[indices["ticker"]]).upper(),
            "cik": sec_cik(cik_value),
            "name": str(match[indices["name"]]),
            "exchange": str(match[indices["exchange"]]),
            "source_url": SEC_TICKERS_EXCHANGE_URL,
        }
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, StopIteration, TypeError, IndexError) as exc:
        raise ValueError(f"SEC ticker {normalized!r} could not be resolved from official mapping") from exc


def discover_sec_filings(cik: str, *, limit: int = 50) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    cik = sec_cik(cik)
    observed = now()
    endpoint = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = sec_fetch_url(endpoint, allowed_host="data.sec.gov")
    if not response.get("ok"):
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("sec-filings", "SEC EDGAR submissions", "unavailable", observed, missing=[endpoint], notes=str(response.get("error")))], "transport": {"etag": None, "last_modified": None}}
    try:
        payload = json.loads(response["content"].decode("utf-8"))
        recent = payload["filings"]["recent"]
        accessions = recent["accessionNumber"]
        forms = recent["form"]
        dates = recent["filingDate"]
        documents = recent.get("primaryDocument", [])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"generated_at": observed, "candidates": [], "source_health": [health_row("sec-filings", "SEC EDGAR submissions", "partial", observed, missing=["parseable recent filings"], notes=f"SEC payload could not be parsed: {exc}")], "transport": {"etag": response["headers"].get("ETag") or None, "last_modified": response["headers"].get("Last-Modified") or None}}

    candidates: list[dict[str, Any]] = []
    for index, accession in enumerate(accessions[:limit]):
        accession_id = str(accession)
        accession_compact = accession_id.replace("-", "")
        document = str(documents[index]) if index < len(documents) and documents[index] else ""
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{document}" if document else f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/"
        candidates.append({"url": url, "title": f"{payload.get('name') or 'SEC issuer'} {forms[index] if index < len(forms) else 'filing'} {accession_id}", "discovery_method": "official_submission_api", "source_url": endpoint, "media_type": "application/edgar", "external_id": accession_id, "published_at": str(dates[index]) if index < len(dates) else None, "verification": "discovery_only"})
    return {"generated_at": observed, "candidates": candidates, "source_health": [health_row("sec-filings", "SEC EDGAR submissions", "available", observed, coverage=[endpoint], notes=f"{len(candidates)} filing metadata item(s) returned; accessionNumber is the incremental identifier.")], "transport": {"etag": response["headers"].get("ETag") or None, "last_modified": response["headers"].get("Last-Modified") or None}}


def discover_multi_free(topic: str, *, extra: str = "", companies: str = "", limit: int = 500) -> dict[str, Any]:
    """Free multi-source web/news discovery (Google News RSS, SearXNG, ddgs, GitHub, HN)."""
    from multi_free_source import collect_topic
    return collect_topic(topic, extra=extra, companies=companies, limit=limit)


def write_json(path: str, payload: dict[str, Any]) -> None:
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover official feeds or SEC filing metadata without storing article bodies.")
    commands = parser.add_subparsers(dest="command", required=True)
    site = commands.add_parser("site-feed")
    site.add_argument("url")
    site.add_argument("--no-common-paths", action="store_true")
    site.add_argument("--out", required=True)
    sec = commands.add_parser("sec-filings")
    sec.add_argument("cik")
    sec.add_argument("--limit", type=int, default=50)
    sec.add_argument("--out", required=True)
    sec_ticker = commands.add_parser("sec-ticker")
    sec_ticker.add_argument("ticker")
    sec_ticker.add_argument("--out", required=True)
    hkex = commands.add_parser("hkex-filings")
    hkex.add_argument("code", help="HKEX ticker, with or without leading zeroes / .HK")
    hkex.add_argument("from_date", help="YYYYMMDD")
    hkex.add_argument("to_date", help="YYYYMMDD")
    hkex.add_argument("--limit", type=int, default=100)
    hkex.add_argument("--out", required=True)
    cninfo = commands.add_parser("cninfo-filings")
    cninfo.add_argument("code", help="six-digit A-share code")
    cninfo.add_argument("org_id", help="CNINFO official orgId, obtained from its stock metadata")
    cninfo.add_argument("from_date", help="YYYYMMDD")
    cninfo.add_argument("to_date", help="YYYYMMDD")
    cninfo.add_argument("--limit", type=int, default=30)
    cninfo.add_argument("--out", required=True)
    multi = commands.add_parser("multi-free", help="Free multi-source web/news discovery (Google News RSS, SearXNG, ddgs, GitHub, HN)")
    multi.add_argument("topic", help="topic keywords, comma-separated")
    multi.add_argument("--extra", default="", help="extra variant keywords, comma-separated")
    multi.add_argument("--companies", default="", help="company names, comma-separated (auto appends storage/memory)")
    multi.add_argument("--limit", type=int, default=500)
    multi.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "site-feed":
            payload = discover_site_feeds(args.url, include_common_paths=not args.no_common_paths)
        elif args.command == "sec-filings":
            payload = discover_sec_filings(args.cik, limit=args.limit)
        elif args.command == "sec-ticker":
            resolved = resolve_sec_ticker(args.ticker)
            payload = {"generated_at": now(), "entity_resolution": resolved, "candidates": [], "source_health": [health_row("sec-ticker-map", "SEC ticker/exchange mapping", "available", now(), coverage=[SEC_TICKERS_EXCHANGE_URL], notes="Official mapping resolved ticker before filing discovery.")], "transport": {}}
        elif args.command == "hkex-filings":
            payload = discover_hkex_filings(args.code, args.from_date, args.to_date, limit=args.limit)
        elif args.command == "multi-free":
            payload = discover_multi_free(args.topic, extra=args.extra, companies=args.companies, limit=args.limit)
        else:
            payload = discover_cninfo_announcements(args.code, args.org_id, args.from_date, args.to_date, limit=args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    write_json(args.out, payload)
    print(json.dumps({"out": args.out, "candidates": len(payload["candidates"]), "status": payload["source_health"][0]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
