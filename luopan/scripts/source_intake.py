#!/usr/bin/env python3
"""Capture approved discovery candidates as auditable raw artifacts.

This bridges source_discovery.py and the existing raw-material workflow. It
never writes research.json, sources[], evidence[], or source_health.source_ids.
A human/research step must extract a locatable original excerpt before a
candidate can become a verified source.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from collection_common import fetch, require_public_network_url, save_artifact, utc_now, write_json


MAX_ITEMS = 100
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


def source_host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().rstrip(".")


def same_or_subdomain(candidate: str, root: str) -> bool:
    return bool(candidate and root and (candidate == root or candidate.endswith(f".{root}")))


def allowed_document_hosts(candidate: dict) -> tuple[str, ...]:
    """Keep captures within the origin disclosed by the discovery adapter.

    CNINFO is the only current official flow whose metadata endpoint and
    document CDN are intentionally split. SEC EDGAR similarly separates
    submissions metadata (data.sec.gov) from document archives (www.sec.gov).
    Both receive explicit narrow allowlists rather than generic cross-origin
    exceptions.
    """
    source = str(candidate.get("source_url") or "")
    document = str(candidate.get("url") or "")
    source_root, document_root = source_host(source), source_host(document)
    if source_root == "data.sec.gov" and document_root == "www.sec.gov":
        return ("www.sec.gov",)
    if source_root == "www.cninfo.com.cn" and document_root == "static.cninfo.com.cn":
        return ("static.cninfo.com.cn",)
    if same_or_subdomain(document_root, source_root):
        return (source_root,)
    return ()


def document_headers(candidate: dict) -> dict[str, str]:
    source_root = source_host(str(candidate.get("source_url") or ""))
    document_root = source_host(str(candidate.get("url") or ""))
    if source_root == "data.sec.gov" and document_root == "www.sec.gov":
        return {"User-Agent": "LuopanResearch/3.7.1 research-contact: local-only", "Accept": "text/html,application/xml,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.1"}
    return {}


def artifact_suffix(content: bytes, content_type: str, candidate_url: str) -> tuple[str, str]:
    if content.startswith(b"%PDF"):
        return ".pdf", "pdf_captured"
    lowered = content_type.casefold()
    path = urlparse(candidate_url).path.casefold()
    if "html" in lowered or path.endswith((".htm", ".html")):
        return ".html.txt", "page_captured"
    if "json" in lowered or path.endswith(".json"):
        return ".json", "json_captured"
    return ".bin", "unknown_document_type"


def load_discovery(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("discovery root must be an object")
    if not isinstance(payload.get("candidates"), list):
        raise ValueError("discovery candidates must be an array")
    if not isinstance(payload.get("source_health", []), list):
        raise ValueError("discovery source_health must be an array")
    return payload


def capture_candidate(candidate: dict, out_dir: Path, timeout: int) -> dict:
    url = str(candidate.get("url") or "")
    source_url = str(candidate.get("source_url") or "")
    allowed_hosts = allowed_document_hosts(candidate)
    record = {
        "candidate": candidate,
        "requested_url": url,
        "source_url": source_url,
        "retrieved_at": utc_now(),
        "verification": "discovery_only",
    }
    if candidate.get("verification") != "discovery_only":
        record.update({"result": "rejected_non_discovery_candidate", "error": "intake accepts discovery_only candidates only"})
        return record
    if not url or not source_url or not allowed_hosts:
        record.update({"result": "rejected_host_boundary", "error": "candidate document URL is outside the declared source host boundary"})
        return record
    try:
        require_public_network_url(source_url)
        require_public_network_url(url)
    except ValueError as exc:
        record.update({"result": "rejected_network_target", "error": str(exc)})
        return record
    response = fetch(
        url,
        timeout=timeout,
        max_bytes=MAX_DOCUMENT_BYTES,
        allowed_host_suffixes=allowed_hosts,
        headers=document_headers(candidate),
    )
    content = response.pop("content", b"")
    record.update(response)
    if not response.get("ok") or not content:
        record["result"] = "error"
        return record
    suffix, result = artifact_suffix(content, str(response.get("content_type") or ""), url)
    record["artifact"] = save_artifact(out_dir / "documents", str(candidate.get("external_id") or candidate.get("title") or "candidate"), content, suffix)
    record["result"] = result
    return record


def overall_status(captures: list[dict]) -> str:
    successful = {"pdf_captured", "page_captured", "json_captured", "unknown_document_type"}
    if any(item.get("result") in successful for item in captures):
        return "captured" if all(item.get("result") in successful for item in captures) else "partial"
    if any(str(item.get("result", "")).startswith("rejected_") for item in captures):
        return "partial"
    return "unavailable" if captures else "empty"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Capture discovery-only candidates into raw artifacts without modifying research.json.")
    parser.add_argument("discovery", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if args.max_items < 1 or args.max_items > MAX_ITEMS:
        parser.error(f"--max-items must be between 1 and {MAX_ITEMS}")
    if args.timeout < 1 or args.timeout > 120:
        parser.error("--timeout must be between 1 and 120")
    try:
        discovery = load_discovery(args.discovery)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    out_dir = args.out_dir.resolve()
    captures = [capture_candidate(item, out_dir, args.timeout) for item in discovery["candidates"][: args.max_items] if isinstance(item, dict)]
    payload = {
        "collector": "official_disclosure_intake",
        "status": overall_status(captures),
        "generated_at": utc_now(),
        "discovery_input": str(args.discovery.resolve()),
        "source_health": discovery.get("source_health", []),
        "transport": discovery.get("transport", {}),
        "captures": captures,
        "interpretation_warning": "已保存原始文件仅证明候选文件可获取；在提取可定位原文、建立 source 与 atomic evidence 并通过 research.json 校验前，任何候选不得支撑论断、指标或覆盖状态。",
    }
    write_json(out_dir / "manifest.json", payload)
    print(json.dumps({"out": str((out_dir / 'manifest.json').resolve()), "status": payload["status"], "captures": len(captures)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
