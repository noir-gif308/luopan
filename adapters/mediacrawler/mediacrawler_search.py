#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MediaCrawler 社媒垂直来源适配器（罗盘搜索适配器层 / Hermes 采集链共用）。

接口对齐 luopan/references/tool-adapters.md 的适配器约定：
  - CLI 形式，--out 输出候选 JSON
  - 状态分类：available / partial / unavailable / manual_required
  - 原始材料落盘 raw/social/<platform>/ + manifest.json 采集审计
  - 失败必须记录具体原因，不得静默伪装

调用链：本适配器 -> MediaCrawler CLI（uv run main.py，CDP 复用本地 Chrome 登录态）
        -> data/<platform>/search_*.jsonl -> 解析转条目 -> --out JSON + raw/ 落盘

用法:
  python mediacrawler_search.py "关键词1,关键词2" --platform xhs \
      [--limit 20] [--comments no] [--headless yes] [--lt qrcode|cookie] \
      [--out social-xhs.json] [--raw-dir RAW] [--timeout 900]

首次使用：各平台需用户扫码登录一次（--lt qrcode），登录态由 CDP 浏览器或
Playwright user_data_dir 保存，之后 --lt cookie 或 CDP 复用。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# ---- 环境常量 ----
MC_DIR = Path(os.environ.get("MEDIACRAWLER_DIR", ""))
DEFAULT_RAW = Path(os.environ.get("LUOPAN_RAW_DIR", "raw/social"))

PLATFORMS = {
    "xhs": "小红书",
    "dy": "抖音",
    "ks": "快手",
    "bili": "B站",
    "wb": "微博",
    "tieba": "百度贴吧",
    "zhihu": "知乎",
}

# 各平台 jsonl 字段映射（实测 2026-08-22，字段名平台间不一致）
# text: 内容摘要字段；title: 标题字段（wb 无独立标题，用 content 截断）
PLATFORM_FIELDS = {
    "xhs":   dict(url="note_url", title="title", author="user_name", like="liked_count", comment="comment_count", text="desc"),
    "bili":  dict(url="video_url", title="title", author="nickname", like="liked_count", comment="video_comment", text="desc"),
    "zhihu": dict(url="content_url", title="title", author="user_nickname", like="voteup_count", comment="comment_count", text="content_text"),
    "tieba": dict(url="note_url", title="title", author="user_nickname", like=None, comment="total_replay_num", text="desc"),
    "wb":    dict(url="note_url", title="content", author="nickname", like="liked_count", comment="comments_count", text="content"),
    "dy":    dict(url="aweme_url", title="title", author="nickname", like="liked_count", comment="comment_count", text="desc"),
    "ks":    dict(url="video_url", title="title", author="nickname", like="liked_count", comment="viewd_count", text="desc"),
}

# MediaCrawler 主程序参数名以 `uv run main.py --help` 实测为准（2026-08-22）
# 此处 key 为适配器参数，value 为传给 main.py 的 CLI 拼装片段
MC_BIN = ["uv", "run", "main.py"]


def _log(msg: str) -> None:
    print(f"[mediacrawler-adapter] {msg}", file=sys.stderr, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_env() -> dict:
    """清除 PYTHONPATH 等污染变量。

    Hermes 会话的 PYTHONPATH 指向 hermes-agent venv，会污染 uv run 子进程
    （实测 2026-08-22：zhihu/ks 加载了 hermes venv 的 tenacity/playwright 导致
    平台代码路径报错，xhs/tieba 恰好不踩）。与罗盘 `PYTHONPATH= ./run.cmd`
    同款坑，适配器内建修复。
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def check_env() -> str | None:
    """返回不可用原因；None 表示环境可用。"""
    if not os.environ.get("MEDIACRAWLER_DIR"):
        return "MEDIACRAWLER_DIR 环境变量未设置（应指向 MediaCrawler 项目目录）"
    if not MC_DIR.is_dir():
        return f"MediaCrawler 目录不存在: {MC_DIR}"
    if not (MC_DIR / "main.py").is_file():
        return f"MediaCrawler 主程序缺失: {MC_DIR / 'main.py'}"
    if not (MC_DIR / ".venv").is_dir():
        return "MediaCrawler .venv 未创建（需在项目目录执行 uv sync）"
    r = subprocess.run(["uv", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        return "uv 不可用: " + (r.stderr.strip()[:120] or "exit non-zero")
    return None


LOGIN_FAIL_MARKERS = [
    "扫码", "二维码", "qrcode", "登录", "login", "验证", "verify",
    "captcha", "slider", "滑块", "cookie失效", "cookie expired",
]


def classify_failure(stdout: str, stderr: str) -> str:
    """把 CLI 失败归类为 manual_required（登录/验证码）或 unavailable（其他）。"""
    blob = (stdout + stderr).lower()
    for m in LOGIN_FAIL_MARKERS:
        if m in blob:
            return "manual_required"
    return "unavailable"


def build_cmd(platform: str, lt: str, keywords: str, limit: int,
              comments: bool, headless: bool, save_data_path: str) -> list[str]:
    """构造 MediaCrawler CLI 调用（参数名与 main.py --help 实测一致，2026-08-22）。

    --save_data_path 直接把输出重定向到 raw 目录：MediaCrawler 会写到
    <save_data_path>/<platform>/search_contents_<date>.jsonl（原始材料直写，无损）。
    """
    cmd = MC_BIN + [
        "--platform", platform,
        "--lt", lt,
        "--type", "search",
        "--keywords", keywords,
        "--crawler_max_notes_count", str(limit),
        "--save_data_option", "jsonl",
        "--save_data_path", save_data_path,
        "--get_comment", "yes" if comments else "no",
        "--headless", "yes" if headless else "no",
    ]
    return cmd


def parse_jsonl(path: Path, platform: str, query: str, limit: int,
                start_offset: int = 0) -> list[dict]:
    """把 MediaCrawler jsonl 行转成罗盘候选条目（保数字/日期/原文，不归纳）。

    start_offset: 本次运行前文件的字节大小；append 模式下只解析本次新增行。
    字段按 PLATFORM_FIELDS 映射（各平台字段名不一致，实测校准）。
    """
    fld = PLATFORM_FIELDS.get(platform, {})
    items: list[dict] = []
    seen_urls: set[str] = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        if start_offset > 0:
            f.seek(start_offset)
            f.readline()  # 丢弃可能被截断的首行
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = str(row.get(fld.get("url", "")) or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title_src = row.get(fld.get("title", "")) or row.get(fld.get("text", "")) or ""
            title = str(title_src)[:80]
            def pick(key: str):
                v = row.get(fld.get(key) or "")
                return v if v not in (None, "") else None
            items.append({
                "platform": platform,
                "platform_name": PLATFORMS.get(platform, platform),
                "query": query,
                "title": title,
                "url": url,
                "author": str(row.get(fld.get("author", "")) or ""),
                "liked_count": pick("like"),
                "comment_count": pick("comment"),
                "publish_time": row.get("publish_time") or row.get("create_time")
                                or row.get("create_date_time") or row.get("created_time") or "",
                "raw": {k: v for k, v in row.items()
                        if k in (fld.get("text"), fld.get("title"), "ip_location",
                                 "video_id", "note_id", "aweme_id", "content_id", "question_id")},
            })
            if len(items) >= limit:
                break
    return items


def write_manifest(raw_dir: Path, platform: str, source_jsonl: Path,
                   query: str, items: list[dict], status: str) -> dict:
    """写 manifest.json 采集审计（原始 jsonl 由 MediaCrawler 直写 raw 目录，无损）。"""
    manifest_path = raw_dir / platform / "manifest.json"
    entry = {
        "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "adapter": "mediacrawler_search",
        "platform": platform,
        "query": query,
        "status": status,
        "item_count": len(items),
        "file": str(source_jsonl),
        "sha256": sha256_file(source_jsonl),
    }
    if manifest_path.is_file():
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            man = {"entries": []}
    else:
        man = {"entries": []}
    man.setdefault("entries", []).append(entry)
    manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def _dir_size(p: Path) -> int:
    if not p.is_dir():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def login_state_ready(platform: str, lt: str) -> tuple[bool, str]:
    """登录态预检：避免无登录态时 CLI 长时间挂起等扫码。

    检查 browser_data 下平台 user_data_dir 的实际体积。CLI 启动时会自建
    空目录（0 字节），不能作为登录证据；登录态保存后 Chrome profile
    （Cookies 等）至少几百 KB，故以 100KB 为门槛。所有登录方式统一预检，
    调用方在 headless=no（用户可扫码）时跳过本预检。
    """
    candidates = [
        MC_DIR / "browser_data" / f"{platform}_user_data_dir",
        MC_DIR / "browser_data" / f"cdp_{platform}_user_data_dir",
    ]
    total = sum(_dir_size(d) for d in candidates)
    if total >= 100 * 1024:
        return True, ""
    guide = (
        f"平台 {platform}（{PLATFORMS.get(platform, platform)}）无登录态缓存。\n"
        f"首次使用请扫码登录一次（登录态将保存，之后 --lt cookie 复用）：\n"
        f"  cd {MC_DIR}\n"
        f'  uv run main.py --platform {platform} --lt qrcode --type search --keywords "任意词" --crawler_max_notes_count 1 --headless no\n'
        f"扫码完成后重跑本适配器即可。"
    )
    return False, guide


def clean_stale_sessions(platform: str) -> None:
    """清掉受控 Chrome 的标签恢复快照（Sessions/Tabs_*）。

    根因：Chrome 启动会恢复 user_data_dir 里 Sessions/ 下的 Tabs 文件，
    MediaCrawler 每次 run 开的空白/搜索标签会累积进快照，下次启动全部
    恢复 → 用户看到空白搜索页持续积累（实测）。登录态
    （Cookies）在 Network/Cookies，不受影响；Sessions 只存窗口标签。
    运行前清理防恢复，运行后清理防本次标签写入快照。
    """
    for profile_dir in (MC_DIR / "browser_data").glob(f"{platform}_user_data_dir"):
        for sess in [profile_dir / "Sessions", profile_dir / "Default" / "Sessions"]:
            if sess.is_dir():
                for f in sess.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass


def kill_process_tree(pid: int) -> None:
    """Windows 下杀整个进程树（uv → main.py → Chrome 孙进程）。

    subprocess.run 超时只杀直接子进程，Chrome 孙进程会残留成孤儿窗口。
    taskkill /T 沿父子链清理。仅 Windows 有效（本机部署平台）。
    """
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=20)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="MediaCrawler 社媒搜索适配器（罗盘/Hermes 共用）")
    ap.add_argument("keywords", help="关键词，英文逗号分隔多个")
    ap.add_argument("--platform", default="xhs", choices=sorted(PLATFORMS),
                    help="平台: xhs|dy|ks|bili|wb|tieba|zhihu (默认 xhs)")
    ap.add_argument("--limit", type=int, default=20, help="最大笔记/帖子数 (默认 20)")
    ap.add_argument("--comments", default="no", choices=["yes", "no"],
                    help="是否抓一级评论 (默认 no，省时)")
    ap.add_argument("--headless", default="yes", choices=["yes", "no"],
                    help="无头模式 (默认 yes；登录/过验证码时用 no)")
    ap.add_argument("--lt", default="qrcode", choices=["qrcode", "phone", "cookie"],
                    help="登录方式 (默认 qrcode：已存登录态时 pong 直接复用、不弹码；"
                         "cookie 模式仅 xhs/tieba 等从浏览器上下文取 cookie 的平台可用，"
                         "其余平台用 cookie 会因 config.COOKIES 为空而失败)")
    ap.add_argument("--out", default="social-search.json",
                    help="候选 JSON 输出路径（罗盘 --out 约定）")
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW),
                    help="原始材料目录 (默认 luopan raw/social)")
    ap.add_argument("--timeout", type=int, default=900, help="CLI 超时秒数 (默认 900)")
    ap.add_argument("--skip-login-check", action="store_true",
                    help="跳过登录态预检，直接运行 CLI（用户确认已有登录态时用）")
    args = ap.parse_args()

    platform = args.platform
    keywords = args.keywords.strip()
    if not keywords:
        print("FAIL keywords 不能为空", file=sys.stderr)
        return 2

    result: dict = {
        "adapter": "mediacrawler_search",
        "platform": platform,
        "platform_name": PLATFORMS.get(platform, platform),
        "query": keywords,
        "status": "unknown",
        "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "item_count": 0,
        "items": [],
        "raw_dir": str(args.raw_dir),
    }

    # 1. 环境检查
    env_err = check_env()
    if env_err:
        result["status"] = "unavailable"
        result["reason"] = env_err
        _log(env_err)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"unavailable: {env_err}")
        return 2

    # 2. 登录态预检（无人值守 headless 模式必须预检；headless=no 用户可扫码，放行）
    if not args.skip_login_check and args.headless == "yes":
        ready, guide = login_state_ready(platform, args.lt)
        if not ready:
            result["status"] = "manual_required"
            result["reason"] = guide
            _log(guide)
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"manual_required: {platform} 需先扫码登录")
            return 5

    # 3. 运行 MediaCrawler CLI（输出重定向到 raw 目录，MediaCrawler 直写 jsonl）
    raw_dir = Path(args.raw_dir)
    plat_dir = raw_dir / platform
    plat_dir.mkdir(parents=True, exist_ok=True)
    # 输出扫描根：save_data_path 指向的 raw_dir，以及 MediaCrawler 默认 data/。
    # 实测 wb/dy/ks 三个平台的 store 不读 save_data_path、仍写 data/<platform>/，
    # 故双根扫描 + (mtime, size) 变化检测（同日 append 不产生新文件名）。
    scan_roots = [raw_dir, MC_DIR / "data"]

    def snapshot() -> dict:
        return {p: (p.stat().st_mtime, p.stat().st_size)
                for root in scan_roots
                for p in root.rglob("*.jsonl")}
    before = snapshot()
    cmd = build_cmd(platform, args.lt, keywords, args.limit,
                    args.comments == "yes", args.headless == "yes", str(raw_dir))
    # 运行前清标签恢复快照：斩断空白搜索页跨运行积累
    clean_stale_sessions(platform)
    _log("RUN " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, cwd=str(MC_DIR),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=clean_env(),
    )
    try:
        stdout_s, stderr_s = proc.communicate(timeout=args.timeout)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        # 杀整个进程树，防 Chrome 孤儿窗口残留（taskkill /T 沿父子链）
        kill_process_tree(proc.pid)
        proc.kill()
        proc.communicate()
        clean_stale_sessions(platform)
        result["status"] = "unavailable"
        result["reason"] = f"CLI 超时 ({args.timeout}s)，已清理进程树"
        _log(result["reason"])
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"unavailable: {result['reason']}")
        return 3

    if returncode != 0:
        clean_stale_sessions(platform)
        status = classify_failure(stdout_s or "", stderr_s or "")
        tail = (stderr_s or stdout_s or "")[-600:]
        result["status"] = status
        result["reason"] = f"CLI exit {returncode}: {tail}"
        _log(result["reason"])
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{status}: CLI exit {returncode}")
        return 4

    # 4. 找本次产出：双根内新增文件 或 (mtime, size) 变化的已有文件
    candidates = []
    for root in scan_roots:
        for p in root.rglob("*.jsonl"):
            key = (p.stat().st_mtime, p.stat().st_size)
            if p not in before or before[p] != key:
                candidates.append(p)
    if not candidates:
        candidates = [p for root in scan_roots for p in root.rglob("*.jsonl") if p not in before]
    if not candidates:
        result["status"] = "partial"
        result["reason"] = "CLI 成功但未发现新 jsonl（可能无结果或输出格式变化）"
        _log(result["reason"])
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"partial: {result['reason']}")
        return 0
    contents_cands = [p for p in candidates if "contents" in p.stem]
    source = max(contents_cands or candidates, key=lambda p: p.stat().st_mtime)
    start_offset = before[source][1] if source in before else 0

    # 5. 解析 + manifest 审计
    items = parse_jsonl(source, platform, keywords, args.limit, start_offset)
    clean_stale_sessions(platform)
    manifest_entry = write_manifest(raw_dir, platform, source, keywords, items,
                                    "available" if items else "partial")
    result["status"] = "available" if items else "partial"
    result["item_count"] = len(items)
    result["items"] = items
    result["source_jsonl"] = str(source)
    result["manifest_entry"] = manifest_entry
    if not items:
        result["reason"] = "搜索无结果（关键词或平台内容为空，非适配器故障）"
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{result['status']}: {len(items)} items -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
