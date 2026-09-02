#!/usr/bin/env python3
"""Check whether core Chinese company-intelligence sources are reachable."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.request import Request, urlopen


SOURCES = [
    ("corporate_registry", "https://www.gsxt.gov.cn/index.html", "browser_manual_likely"),
    ("government_procurement", "https://www.ccgp.gov.cn/", "http_then_rate_limited_search"),
    ("patent", "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch", "browser_manual_likely"),
    ("icp", "https://beian.miit.gov.cn/", "browser_manual_likely"),
    ("certification", "https://cx.cnca.cn/CertECloud/index/index/page", "browser_manual_likely"),
    ("recall", "https://www.samrdprc.org.cn/", "http_search_available"),
    ("court_documents", "https://wenshu.court.gov.cn/", "browser_search_likely"),
    ("enforcement", "https://zxgk.court.gov.cn/", "http_or_browser"),
    ("recruitment", "https://www.zhipin.com/", "scrapling_or_browser"),
]


def probe(name: str, url: str, expected_access: str, timeout: int) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 LuopanHealth/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(300_000)
            status = response.status
            final_url = response.geturl()
        result = "reachable" if status == 200 else "unexpected_status"
        if any(marker in body for marker in ("验证码".encode(), "访问过于频繁".encode(), b"captcha")):
            result = "challenge_or_rate_limited"
        return {
            "dimension": name,
            "url": url,
            "result": result,
            "http_status": status,
            "bytes_sampled": len(body),
            "final_url": final_url,
            "expected_access": expected_access,
        }
    except Exception as exc:
        return {
            "dimension": name,
            "url": url,
            "result": "blocked_or_unreachable",
            "error": str(exc),
            "expected_access": expected_access,
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    results = [probe(*source, args.timeout) for source in SOURCES]
    summary = {
        "reachable": sum(item["result"] == "reachable" for item in results),
        "challenged_or_blocked": sum(item["result"] != "reachable" for item in results),
        "manual_or_browser_expected": sum("browser" in item["expected_access"] or "manual" in item["expected_access"] for item in results),
    }
    print(json.dumps({"summary": summary, "sources": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
