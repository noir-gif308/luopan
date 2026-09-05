"""ddgs_search.py — DuckDuckGo 元搜索适配器（罗盘/Hermes/Codex 共享）

接口对齐 luopan tool-adapters.md 约定（与 mediacrawler-adapter 同款）：
  - CLI 调用 + --out JSON 落盘 + source_health 状态 + raw manifest 审计
  - 零 API key；依赖 ddgs（MIT, github.com/deedy5/ddgs, 2026-08 活跃）
  - 走系统代理（DDG 在国内网络需代理，Hermes 系统代理 7897 已配）

用法：
  python ddgs_search.py "关键词" --limit 20 --out result.json
  python ddgs_search.py source_health

运行环境：任意已安装 ddgs 的 Python（Hermes venv 已装：
  E:/leidian/hermes/hermes-agent/venv/Scripts/python.exe）
罗盘 runtime 未装 ddgs，不要用罗盘 runtime 跑本脚本。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone


def source_health() -> dict:
    """返回源健康状态 JSON；罗盘采集前先跑这个。"""
    status = {
        "source": "ddgs",
        "url": "https://github.com/deedy5/ddgs",
        "license": "MIT",
        "ok": False,
        "error": None,
        "latency_ms": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from ddgs import DDGS
        t0 = time.time()
        rs = list(DDGS().text("test", max_results=2))
        status["ok"] = True
        status["latency_ms"] = round((time.time() - t0) * 1000)
        status["sample_count"] = len(rs)
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def search(query: str, limit: int = 20) -> list[dict]:
    from ddgs import DDGS
    items = []
    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in query)
    junk = 0
    for r in DDGS().text(query, max_results=limit):
        title = r.get("title", "")
        url = r.get("href") or r.get("url", "")
        # 中文查询的偶发降级：DDG 对代理 IP 间歇性返回英文垃圾（实测"数字人"触发过一次）。
        # 过滤标题无中文且域名不在白名单的结果，保证下游拿到可用的中文召回。
        if has_cjk:
            title_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in title)
            domain_ok = any(d in url for d in
                            ("polyv", "github", "zhihu", "sohu", "163.com", "sina",
                             "csdn", "baidu", "qq.com", "cnki", "gov.cn", "edu.cn"))
            # 实测黑名单："数字人"等词组合会系统性返回英文垃圾站（含中文标题的 FB 帖也垃圾）
            domain_black = any(d in url for d in
                               ("facebook.com", "goodreads.com", "behance.net",
                                "pexels.com", "wolframalpha.com", "dictionary.yahoo"))
            if domain_black or (not title_cjk and not domain_ok):
                junk += 1
                continue
        items.append({
            "title": title,
            "url": url,
            "description": r.get("body", ""),
            "engine": "ddgs",
            "published": "",  # ddgs 文本接口不返回日期；近期信息用 multi-free 的 Google News 源补
        })
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="DDG 元搜索适配器（跨 Agent 共享）")
    ap.add_argument("query", nargs="?", help="搜索词")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", help="JSON 输出路径（缺省只打印 stdout 摘要）")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if args.query == "source_health":
        print(json.dumps(source_health(), ensure_ascii=False, indent=2))
        return 0

    if not args.query:
        ap.print_help()
        return 2

    t0 = time.time()
    try:
        items = search(args.query, args.limit)
        health = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    payload = {
        "meta": {
            "query": args.query,
            "source": "ddgs",
            "count": len(items),
            "elapsed_s": round(time.time() - t0, 2),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "health": health,
        },
        "items": items,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"written: {args.out} ({len(items)} items)")
    else:
        for it in items[:5]:
            print(f" * {it['title'][:60]} | {it['url'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
