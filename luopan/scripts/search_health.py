#!/usr/bin/env python3
"""Probe a SearXNG instance before company deep research."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from urllib.parse import quote, urlparse
from urllib.request import urlopen

from collection_common import read_limited


NOISY_DOMAINS = {
    "baike.baidu.com", "baijiahao.baidu.com", "zhidao.baidu.com",
    "wenku.baidu.com", "csdn.net", "www.csdn.net", "sohu.com",
    "www.sohu.com", "163.com", "www.163.com", "toutiao.com",
    "www.toutiao.com",
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def fetch_json(base_url: str, query: str, engine: str, language: str) -> dict:
    url = (
        f"{base_url.rstrip('/')}/search?q={quote(query)}&format=json"
        f"&language={quote(language)}&engines={quote(engine)}"
    )
    with urlopen(url, timeout=30) as response:
        return json.loads(read_limited(response, MAX_RESPONSE_BYTES).decode("utf-8"))


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("m.")


def inspect_results(results: list[dict], expected_domain: str | None) -> dict:
    urls = [item.get("url", "") for item in results if item.get("url")]
    domains = [domain(url) for url in urls]
    expected = expected_domain.lower().removeprefix("www.") if expected_domain else None
    on_domain = sum(
        item == expected or item.endswith(f".{expected}") for item in domains
    ) if expected else None
    return {
        "result_count": len(results),
        "unique_url_ratio": round(len(set(urls)) / len(urls), 3) if urls else 0,
        "noisy_domain_ratio": round(sum(item in NOISY_DOMAINS for item in domains) / len(domains), 3) if domains else 0,
        "expected_domain_ratio": round(on_domain / len(domains), 3) if domains and expected else None,
        "top_domains": Counter(domains).most_common(5),
        "top_results": [{"title": item.get("title"), "url": item.get("url")} for item in results[:5]],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("company", help="Legal name or best-known company name")
    parser.add_argument("--official-domain")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--engines", default="google,bing,baidu")
    parser.add_argument("--language", default="zh-CN")
    args = parser.parse_args()

    probes = {
        "exact_name": f'"{args.company}"',
        "footprints": f'"{args.company}" 招标 中标 专利 招聘 环评 客户 供应商',
    }
    if args.official_domain:
        probes["site_constraint"] = f'site:{args.official_domain} "{args.company}"'

    report = {"company": args.company, "base_url": args.base_url, "engines": {}, "interpretation": []}
    for engine in [item.strip() for item in args.engines.split(",") if item.strip()]:
        engine_result = {}
        for probe_name, query in probes.items():
            try:
                payload = fetch_json(args.base_url, query, engine, args.language)
                details = inspect_results(payload.get("results", []), args.official_domain if probe_name == "site_constraint" else None)
                details["unresponsive_engines"] = payload.get("unresponsive_engines", [])
                engine_result[probe_name] = details
            except Exception as exc:
                engine_result[probe_name] = {"error": str(exc)}
        report["engines"][engine] = engine_result

    usable = 0
    for engine, probes_result in report["engines"].items():
        exact = probes_result.get("exact_name", {})
        if exact.get("result_count", 0) > 0 and not exact.get("error"):
            usable += 1
        if exact.get("noisy_domain_ratio", 0) >= 0.5:
            report["interpretation"].append(f"{engine}: exact-name results are dominated by noisy domains")
        site = probes_result.get("site_constraint", {})
        if site.get("result_count", 0) and (site.get("expected_domain_ratio") or 0) < 0.8:
            report["interpretation"].append(f"{engine}: site constraint is unreliable")

    if usable < 2:
        report["interpretation"].append("Fewer than two general engines are usable; deep research discovery is degraded")
        report["recommended_status"] = "degraded"
    else:
        report["recommended_status"] = "usable_with_vertical_sources"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
