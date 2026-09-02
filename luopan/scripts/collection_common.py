#!/usr/bin/env python3
"""Shared low-frequency capture helpers for public research artifacts."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


SKILL_VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
USER_AGENT = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) LuopanResearch/{SKILL_VERSION}"
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
CHALLENGE_MARKERS = (
    "访问过于频繁",
    "频繁访问",
    "验证码",
    "安全验证",
    "captcha",
    "verify you are human",
    "访问受限",
    "请登录",
    "登录后",
    "登陆后",
    "会员订阅",
    "付费阅读",
    "登录查看",
    "login",
    "log in",
    "sign in",
    "subscribe to continue",
    "paywall",
    "premium content",
    "members only",
    "access denied",
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = normalize_space(" ".join(self._parts))
            if text and self._href:
                self.links.append({"title": text, "url": self._href})
            self._href = None
            self._parts = []


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return normalize_space(value)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def slug(value: str, limit: int = 70) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value).strip("-._")
    return (cleaned or "artifact")[:limit]


def detect_challenge(text: str) -> str | None:
    lowered = text.lower()
    return next((marker for marker in CHALLENGE_MARKERS if marker.lower() in lowered), None)


def host_matches(url: str, allowed_host_suffixes: tuple[str, ...] | None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if not allowed_host_suffixes:
        return True
    host = parsed.hostname.lower().rstrip(".")
    for suffix in allowed_host_suffixes:
        root = suffix.lower().lstrip(".").rstrip(".")
        if host == root or host.endswith(f".{root}"):
            return True
    return False


def require_public_network_url(value: str) -> None:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL has no hostname")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError(f"private network target is forbidden: {host}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValueError(f"hostname could not be resolved safely: {host}") from exc
        addresses = {
            ipaddress.ip_address(item[4][0].split("%", 1)[0])
            for item in resolved
        }
        if not addresses:
            raise ValueError(f"hostname resolved to no usable addresses: {host}")
    else:
        addresses = {address}
    unsafe = sorted(str(item) for item in addresses if not item.is_global)
    if unsafe:
        raise ValueError(
            f"private network target is forbidden: {host} resolved to {', '.join(unsafe)}"
        )


class RestrictedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_host_suffixes: tuple[str, ...] | None) -> None:
        super().__init__()
        self.allowed_host_suffixes = allowed_host_suffixes

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        old_scheme = urlparse(req.full_url).scheme.lower()
        new_scheme = urlparse(newurl).scheme.lower()
        if old_scheme == "https" and new_scheme != "https":
            raise HTTPError(newurl, 403, "HTTPS downgrade redirect is forbidden", headers, fp)
        if not host_matches(newurl, self.allowed_host_suffixes):
            raise HTTPError(newurl, 403, "redirect left the allowed host boundary", headers, fp)
        try:
            require_public_network_url(newurl)
        except ValueError as exc:
            raise HTTPError(newurl, 403, str(exc), headers, fp) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_limited(stream, max_bytes: int) -> bytes:  # type: ignore[no-untyped-def]
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch(
    url: str,
    timeout: int = 30,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allowed_host_suffixes: tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    if max_bytes < 1:
        return {"ok": False, "status": None, "url": url, "error": "max_bytes must be positive", "content": b""}
    if not host_matches(url, allowed_host_suffixes):
        return {"ok": False, "status": None, "url": url, "error": "URL is outside the allowed host boundary", "content": b""}
    try:
        require_public_network_url(url)
    except ValueError as exc:
        return {"ok": False, "status": None, "url": url, "error": str(exc), "content": b""}
    request_headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}
    if headers:
        if not isinstance(headers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in headers.items()
        ):
            return {"ok": False, "status": None, "url": url, "error": "headers must be a string-to-string mapping", "content": b""}
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    opener = build_opener(RestrictedRedirectHandler(allowed_host_suffixes))
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not host_matches(final_url, allowed_host_suffixes):
                return {"ok": False, "status": response.status, "url": final_url, "error": "redirect left the allowed host boundary", "content": b""}
            try:
                require_public_network_url(final_url)
            except ValueError as exc:
                return {"ok": False, "status": response.status, "url": final_url, "error": str(exc), "content": b""}
            declared_length = response.headers.get("Content-Length")
            if declared_length and declared_length.isdigit() and int(declared_length) > max_bytes:
                return {"ok": False, "status": response.status, "url": final_url, "error": f"response exceeds {max_bytes} byte limit", "content": b""}
            content = read_limited(response, max_bytes)
            return {
                "ok": True,
                "status": response.status,
                "url": final_url,
                "content_type": response.headers.get("Content-Type", ""),
                "content": content,
            }
    except HTTPError as exc:
        try:
            content = read_limited(exc, max_bytes)
        except ValueError:
            content = b""
        return {"ok": False, "status": exc.code, "url": getattr(exc, "url", url), "error": str(exc), "content": content}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "status": None, "url": url, "error": str(exc), "content": b""}


def decode_html(content: bytes, content_type: str = "") -> str:
    candidates = []
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        candidates.append(match.group(1))
    prefix = content[:2000].decode("ascii", errors="ignore")
    match = re.search(r"charset=[\"']?([\w-]+)", prefix, re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(["utf-8", "gb18030"])
    for encoding in candidates:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def parse_links(html: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(html)
    return parser.links


def save_artifact(out_dir: Path, stem: str, content: bytes, suffix: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(content)
    path = out_dir / f"{slug(stem)}-{digest[:12]}{suffix}"
    if not path.exists():
        path.write_bytes(content)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": len(content)}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def polite_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
