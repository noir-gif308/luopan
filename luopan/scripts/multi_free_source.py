#!/usr/bin/env python3
"""multi_free_source — 免费多源网页/新闻采集模块（luopan 适配器用）。

独立于 Hermes 侧 topic_collect.py：本模块自带采集逻辑，luopan 调研时
通过 source_discovery.py 的 ``multi-free`` 子命令调用。

信息源（全部免费、实测可用）:
    - Google News RSS        (zh-CN + en-US, when:7d 时效过滤)
    - SearXNG general        (本地 :8080, 多页)
    - SearXNG news           (本地 :8080, news 类目)
    - ddgs                   (DuckDuckGo 免 key 包, 缺失时自动降级)
    - GitHub API             (仓库搜索)
    - HN Algolia             (技术社区)

依赖: 无第三方包（ddgs 可选）；本地 SearXNG 实例(:8080)可选，缺失自动降级。
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Luopan-MultiFree/1.0"}
_TIMEOUT = 15

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_DEFAULT = urllib.request.build_opener()


def _http_get(url: str, timeout: int = _TIMEOUT, direct: bool = False) -> str:
    opener = _DIRECT if direct else _DEFAULT
    req = urllib.request.Request(url, headers=UA)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 变体生成
# ---------------------------------------------------------------------------

def build_variants(topic: str, extra: str = "", companies: str = "") -> List[str]:
    parts = [p.strip() for p in topic.split(",") if p.strip()]
    variants: List[str] = []
    for p in parts:
        variants.append(p)
        if re.search(r"[\u4e00-\u9fff]", p):
            variants.append(p + " 价格")
            variants.append(p + " 市场")
        else:
            variants.append(p + " price")
            variants.append(p + " market")
    for e in (x.strip() for x in extra.split(",")):
        if e:
            variants.append(e)
    for c in (x.strip() for x in companies.split(",")):
        if c:
            variants.append(f"{c} 存储")
            variants.append(f"{c} memory")
    seen: set = set()
    out: List[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# 各源采集
# ---------------------------------------------------------------------------

def _gnews(q: str, max_items: int = 25) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for hl, gl, lang in (("zh-CN", "CN", "zh"), ("en-US", "US", "en")):
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote(f"{q} when:7d")
               + f"&hl={hl}&gl={gl}&ceid={hl}")
        try:
            xml = _http_get(url)
            for it in re.findall(r"<item>(.*?)</item>", xml, re.S)[:max_items]:
                t = re.search(r"<title>(.*?)</title>", it, re.S)
                lk = re.search(r"<link>(.*?)</link>", it, re.S)
                d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
                s = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
                out.append({
                    "title": (t.group(1) if t else "").strip()[:300],
                    "url": (lk.group(1) if lk else "").strip(),
                    "description": (t.group(1) if t else "").strip()[:300],
                    "source": f"gnews-{lang}",
                    "published_at": (d.group(1) if d else "")[:25] or None,
                    "publisher": (s.group(1) if s else "").strip(),
                })
        except Exception:
            pass
    return out


def _searxng(q: str, category: str, pages: int = 2) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, pages + 1):
        params = {"q": q, "format": "json", "pageno": page}
        if category != "general":
            params["categories"] = category
        try:
            data = json.loads(_http_get(
                f"{SEARXNG_URL}/search?{urllib.parse.urlencode(params)}",
                timeout=22, direct=True))
            for r in data.get("results", []):
                out.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("content", ""),
                    "source": r.get("engine", "searxng"),
                    "published_at": None,
                    "publisher": "",
                })
        except Exception:
            break
    return out


def _ddgs(q: str, max_items: int = 30) -> List[Dict[str, Any]]:
    try:
        from ddgs import DDGS  # optional dependency
        items = list(DDGS().text(q, max_results=max_items))
        return [{
            "title": it.get("title", ""),
            "url": it.get("href") or it.get("url", ""),
            "description": it.get("body", ""),
            "source": "ddgs",
            "published_at": None,
            "publisher": "",
        } for it in items]
    except Exception:
        return []


def _github(q: str, max_items: int = 15) -> List[Dict[str, Any]]:
    try:
        data = json.loads(_http_get(
            "https://api.github.com/search/repositories?q="
            + urllib.parse.quote(q) + f"&per_page={max_items}"))
        return [{
            "title": it.get("full_name", ""),
            "url": it.get("html_url", ""),
            "description": (it.get("description") or "")[:200],
            "source": "github",
            "published_at": None,
            "publisher": "",
        } for it in data.get("items", [])]
    except Exception:
        return []


def _hn(q: str, max_items: int = 15) -> List[Dict[str, Any]]:
    try:
        data = json.loads(_http_get(
            "https://hn.algolia.com/api/v1/search?query="
            + urllib.parse.quote(q) + "&tags=story" + f"&hitsPerPage={max_items}"))
        return [{
            "title": it.get("title", ""),
            "url": it.get("url") or f"https://news.ycombinator.com/item?id={it.get('objectID', '')}",
            "description": f"points={it.get('points', 0)} comments={it.get('num_comments', 0)}",
            "source": "hn",
            "published_at": None,
            "publisher": "",
        } for it in data.get("hits", [])]
    except Exception:
        return []


def _weibo(q: str, max_items: int = 20) -> List[Dict[str, Any]]:
    """Weibo keyword search via weibo.com ajax API (needs WEIBO_COOKIES).

    RSSHub's weibo route hits m.weibo.cn (mobile session) and fails with
    desktop cookies; this adapter uses the desktop search API directly.
    Cookie is loaded from rsshub.env (WEIBO_COOKIES) or WEIBO_COOKIE env.
    """
    cookie = os.environ.get("WEIBO_COOKIE", "")
    if not cookie:
        env_path = os.environ.get("RSSHUB_ENV_FILE", "")
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("WEIBO_COOKIES="):
                        cookie = line.strip().split("=", 1)[1]
                        break
        except OSError:
            pass
    if not cookie:
        return []
    try:
        url = ("https://weibo.com/ajax/statuses/search?q="
               + urllib.parse.quote(q) + "&page=1")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
            "Cookie": cookie,
            "Referer": "https://weibo.com/",
            "X-Requested-With": "XMLHttpRequest",
        })
        with _DEFAULT.open(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        out: List[Dict[str, Any]] = []
        for s in data.get("statuses", [])[:max_items]:
            user = s.get("user", {}) or {}
            text = re.sub(r"<[^>]+>", "", s.get("text") or "").strip()
            out.append({
                "title": text[:300],
                "url": f"https://weibo.com/{user.get('id', '')}/{s.get('mblogid', '')}",
                "description": (f"@{user.get('screen_name', '')} "
                                + (s.get("created_at") or "") + " "
                                + text[:200]),
                "source": "weibo",
                "published_at": s.get("created_at"),
                "publisher": user.get("screen_name", ""),
            })
        return out
    except Exception:
        return []


def _twitter(q: str, max_items: int = 10) -> List[Dict[str, Any]]:
    """Twitter/X keyword search via local chromium + cookie (twitter_search.js).

    RSSHub's twitter keyword route fails (GraphQL query ID resolver);
    this uses a real local browser with the user's cookie instead.
    """
    import subprocess
    node = os.environ.get("NODE", "")
    script = os.environ.get("TWITTER_SEARCH_JS", "")
    if not node or not script:
        return []
    env = dict(os.environ)
    node_path = os.environ.get("NODE_PATH", "")
    if node_path:
        env["NODE_PATH"] = node_path
    try:
        proc = subprocess.run(
            [node, script, q, str(max_items)],
            capture_output=True, text=True, timeout=60, env=env,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
        return [{
            "title": t.get("text", "")[:300],
            "url": t.get("url", ""),
            "description": f"{t.get('author', '')} {t.get('time', '')} {t.get('stats', '')}",
            "source": "twitter",
            "published_at": t.get("time", "")[:16] or None,
            "publisher": (t.get("author") or "").split("@")[0].strip()[:40],
        } for t in data.get("tweets", [])]
    except Exception:
        return []


def _xueqiu(q: str, max_items: int = 8) -> List[Dict[str, Any]]:
    """Xueqiu keyword search via local chromium (xueqiu_search.js search mode).

    Aliyun WAF challenge passes in headed chromium; guest session works —
    no cookie required. Headed window pops briefly (~8s) per call.
    """
    import subprocess
    node = os.environ.get("NODE", "")
    script = os.environ.get("XUEQIU_SEARCH_JS", "")
    if not node or not script:
        return []
    env = dict(os.environ)
    node_path = os.environ.get("NODE_PATH", "")
    if node_path:
        env["NODE_PATH"] = node_path
    try:
        proc = subprocess.run(
            [node, script, "search", q, str(max_items)],
            capture_output=True, text=True, timeout=90, env=env,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
        return [{
            "title": t.get("text", "")[:300],
            "url": t.get("url", ""),
            "description": f"{t.get('author', '')} {t.get('time', '')} {t.get('stats', '')}",
            "source": "xueqiu",
            "published_at": (t.get("time") or "")[:16] or None,
            "publisher": t.get("author", ""),
        } for t in data.get("items", [])]
    except Exception:
        return []


_COLLECTORS = [
    ("gnews", _gnews),
    ("searxng-general", lambda q: _searxng(q, "general", 2)),
    ("searxng-news", lambda q: _searxng(q, "news", 1)),
    ("ddgs", _ddgs),
    ("github", _github),
    ("hn", _hn),
    ("weibo", _weibo),
    ("twitter", _twitter),
]


def collect_topic(topic: str, extra: str = "", companies: str = "",
                  limit: int = 500) -> Dict[str, Any]:
    """主题查询族多源采集，返回 luopan candidates + source_health 结构。"""
    variants = build_variants(topic, extra, companies)
    seen_urls: set = set()
    all_rows: List[Dict[str, Any]] = []
    src_counts: Dict[str, int] = {}
    src_failures: Dict[str, str] = {}

    for q in variants:
        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            futs = {name: pool.submit(fn, q) for name, fn in _COLLECTORS}
            for name, fut in futs.items():
                try:
                    rows = fut.result(timeout=30)
                    if rows:
                        src_counts[name] = src_counts.get(name, 0) + len(rows)
                    else:
                        src_failures.setdefault(name, "empty")
                except Exception as exc:  # noqa: BLE001
                    src_failures[name] = f"{type(exc).__name__}: {exc}"
        for name, fut in futs.items():
            try:
                for r in fut.result(timeout=1):
                    u = (r.get("url") or "").strip()
                    if not u or u in seen_urls:
                        continue
                    seen_urls.add(u)
                    all_rows.append(r)
            except Exception:
                pass
        # xueqiu runs once per topic (headed window pops; avoid N popups)
        if q == variants[0]:
            xq_rows = _xueqiu(q)
            if xq_rows:
                src_counts["xueqiu"] = src_counts.get("xueqiu", 0) + len(xq_rows)
                for r in xq_rows:
                    u = (r.get("url") or "").strip()
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        all_rows.append(r)
            else:
                src_failures.setdefault("xueqiu", "empty")

    # → candidates（对齐 source_discovery 结构；按源轮转取，保证各源都有配额）
    by_src: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        by_src.setdefault(r.get("source", "?"), []).append(r)
    candidates: List[Dict[str, Any]] = []
    keys = list(by_src.keys())
    idx = 0
    while len(candidates) < limit and any(by_src[k] for k in keys):
        k = keys[idx % len(keys)]
        idx += 1
        if not by_src[k]:
            continue
        r = by_src[k].pop(0)
        candidates.append({
            "url": r["url"],
            "title": r.get("title", "")[:300],
            "description": r.get("description", "")[:500] or None,
            "discovery_method": "multi_free_web",
            "source_url": r.get("url"),
            "media_type": None,
            "external_id": None,
            "published_at": r.get("published_at"),
            "source_name": r.get("source"),
            "verification": "discovery_only",
        })

    observed = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    health = []
    for name, _fn in _COLLECTORS:
        n = src_counts.get(name, 0)
        status = "available" if n else ("unavailable" if name in src_failures else "partial")
        notes = f"{n} item(s)" if n else (src_failures.get(name) or "no items")
        health.append({
            "name": name, "provider": "multi-free",
            "status": status, "observed_at": observed,
            "notes": notes,
        })
    if "xueqiu" in src_counts or "xueqiu" in src_failures:
        n = src_counts.get("xueqiu", 0)
        health.append({
            "name": "xueqiu", "provider": "multi-free",
            "status": "available" if n else "unavailable",
            "observed_at": observed,
            "notes": f"{n} item(s)" if n else src_failures.get("xueqiu", "no items"),
        })

    return {
        "generated_at": observed,
        "query_family": {"topic": topic, "extra": extra,
                         "companies": companies, "variants": variants},
        "candidates": candidates,
        "source_health": health,
        "transport": {"multi_free_total": len(all_rows),
                      "deduped": len(candidates)},
    }
