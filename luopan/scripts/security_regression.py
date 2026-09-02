#!/usr/bin/env python3
"""Regression checks for report sanitization and credential boundaries."""

from __future__ import annotations

import json
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

import external_signal_collect
import browser_capture
import collection_common
import firecrawl_search
import render_report
import source_health
import source_intake


_DNS_PATCHER = None


def _public_getaddrinfo(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def setUpModule() -> None:
    global _DNS_PATCHER
    _DNS_PATCHER = patch.object(collection_common.socket, "getaddrinfo", side_effect=_public_getaddrinfo)
    _DNS_PATCHER.start()


def tearDownModule() -> None:
    if _DNS_PATCHER is not None:
        _DNS_PATCHER.stop()


class FakeResponse:
    def __init__(self, body: object = None, url: str = "https://example.test/data", status: int = 200) -> None:
        self.body = json.dumps({} if body is None else body).encode("utf-8")
        self.url = url
        self.status = status

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self.body
        body, self.body = self.body[:size], self.body[size:]
        return body

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def header_value(request: Request, wanted: str) -> str | None:
    wanted = wanted.lower()
    for name, value in request.header_items():
        if name.lower() == wanted:
            return value
    return None


class ReportSecurityTests(unittest.TestCase):
    def test_raw_html_dangerous_urls_and_event_handlers_are_removed(self) -> None:
        markdown_text = """# Security

<script>alert('x')</script>
<img src="x" onerror="alert(1)">
<a href="javascript:alert(1)" onclick="alert(2)">js</a>
<a href="data:text/html,bad">data</a>
<a href="file:///C:/secret.txt">file</a>
<a href="https://safe.example/path?q=1&v=2" title="safe">safe</a>
"""
        rendered = render_report.render_html(markdown_text, "Security")
        lowered = rendered.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<img", lowered)
        self.assertNotIn("onerror", lowered)
        self.assertNotIn("onclick", lowered)
        self.assertNotIn('href="javascript:', lowered)
        self.assertNotIn('href="data:', lowered)
        self.assertNotIn('href="file:', lowered)
        self.assertIn('href="https://safe.example/path?q=1&amp;v=2"', rendered)
        self.assertIn('rel="noopener noreferrer"', rendered)

    def test_report_has_restrictive_csp(self) -> None:
        rendered = render_report.render_html("# Safe", "Safe")
        self.assertIn('http-equiv="Content-Security-Policy"', rendered)
        for directive in (
            "default-src 'none'",
            "script-src 'none'",
            "img-src 'none'",
            "connect-src 'none'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ):
            self.assertIn(directive, rendered)

    def test_valid_research_fixtures_render_in_memory(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in (
            "deep-synthetic.json",
            "manufacturing-minimal.json",
            "private-sparse-minimal.json",
            "investment-synthetic.json",
        ):
            with self.subTest(fixture=name):
                path = root / "examples" / name
                data = render_report.validate_before_render(path)
                rendered = render_report.render_html(
                    render_report.render_markdown(data),
                    data["meta"]["title"],
                )
                self.assertIn('<meta http-equiv="Content-Security-Policy"', rendered)
                self.assertIn("<body>", rendered)


class ExternalSignalSecurityTests(unittest.TestCase):
    def test_public_url_never_receives_environment_secret(self) -> None:
        captured: list[Request] = []

        def fake_open(request: Request, timeout: float):
            captured.append(request)
            return FakeResponse({"signals": []}, request.full_url)

        with patch.dict(os.environ, {"WORLD_MONITOR_KEY": "top-secret"}, clear=False):
            with patch.object(external_signal_collect, "open_request", side_effect=fake_open):
                external_signal_collect.load_payload(
                    None,
                    "https://public.example/feed",
                    "WORLD_MONITOR_KEY",
                    provider="Public Feed",
                )
        self.assertEqual(len(captured), 1)
        self.assertIsNone(header_value(captured[0], "X-WorldMonitor-Key"))

    def test_only_matching_trusted_https_origin_receives_secret(self) -> None:
        captured: list[Request] = []

        def fake_open(request: Request, timeout: float):
            captured.append(request)
            return FakeResponse({"signals": []}, request.full_url)

        with patch.dict(os.environ, {"WORLD_MONITOR_KEY": "top-secret"}, clear=False):
            with patch.object(external_signal_collect, "open_request", side_effect=fake_open):
                external_signal_collect.load_payload(
                    None,
                    "https://trusted.example/feed",
                    "WORLD_MONITOR_KEY",
                    "https://trusted.example",
                )
                with self.assertRaises(ValueError):
                    external_signal_collect.load_payload(
                        None,
                        "https://other.example/feed",
                        "WORLD_MONITOR_KEY",
                        "https://trusted.example",
                    )
                with self.assertRaises(ValueError):
                    external_signal_collect.load_payload(
                        None,
                        "http://trusted.example/feed",
                        "WORLD_MONITOR_KEY",
                        "http://trusted.example",
                    )
        self.assertEqual(header_value(captured[0], "X-WorldMonitor-Key"), "top-secret")

    def test_custom_provider_and_freshness_are_derived(self) -> None:
        health = {
            "status": "available",
            "provider": "Acme Signals",
            "observed_at": "2026-07-24T12:00:00+00:00",
            "freshness_budget_hours": 24,
        }
        payload = {
            "signals": [
                {"id": "recent", "title": "recent", "as_of": "2026-07-24T00:00:00Z"},
                {"id": "old", "title": "old", "date": "2026-07-22"},
                {"id": "invalid", "title": "invalid", "as_of": "not-a-date"},
                {"id": "future", "title": "future", "as_of": "2026-07-25"},
            ]
        }
        result = external_signal_collect.normalize(payload, health, "https://feeds.example/events")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("world monitor", serialized)
        self.assertNotIn("worldmonitor", serialized)
        self.assertEqual(result["sources"][0]["title"], "Acme Signals / external feed")
        freshness = {item["signal"]: item["freshness"] for item in result["external_signals"]}
        self.assertEqual(freshness, {
            "recent": "fresh",
            "old": "stale",
            "invalid": "unknown",
            "future": "unknown",
        })
        self.assertEqual(result["source_health"][0]["freshness_budget_hours"], 24.0)


class SourceHealthSecurityTests(unittest.TestCase):
    def test_public_probe_does_not_receive_environment_secret(self) -> None:
        captured: list[Request] = []

        def fake_open(request: Request, timeout: float):
            captured.append(request)
            return FakeResponse(url=request.full_url)

        with patch.dict(os.environ, {"WORLD_MONITOR_KEY": "top-secret"}, clear=False):
            with patch.object(source_health, "open_request", side_effect=fake_open):
                row = source_health.probe(
                    "public",
                    "https://public.example/health",
                    "WORLD_MONITOR_KEY",
                    "monitoring",
                    24,
                )
        self.assertEqual(row["status"], "available")
        self.assertIsNone(header_value(captured[0], "X-WorldMonitor-Key"))

    def test_trusted_probe_receives_secret_and_mismatch_fails(self) -> None:
        captured: list[Request] = []

        def fake_open(request: Request, timeout: float):
            captured.append(request)
            return FakeResponse(url=request.full_url)

        with patch.dict(os.environ, {"WORLD_MONITOR_KEY": "top-secret"}, clear=False):
            with patch.object(source_health, "open_request", side_effect=fake_open):
                source_health.probe(
                    "trusted",
                    "https://trusted.example/health",
                    "WORLD_MONITOR_KEY",
                    "monitoring",
                    24,
                    "https://trusted.example",
                )
                with self.assertRaises(ValueError):
                    source_health.probe(
                        "trusted",
                        "https://other.example/health",
                        "WORLD_MONITOR_KEY",
                        "monitoring",
                        24,
                        "https://trusted.example",
                    )
        self.assertEqual(header_value(captured[0], "X-WorldMonitor-Key"), "top-secret")


class FirecrawlSecurityTests(unittest.TestCase):
    def test_custom_base_requires_explicit_matching_trust(self) -> None:
        with self.assertRaises(ValueError):
            firecrawl_search.make_search_request(
                "https://firecrawl.internal",
                None,
                "top-secret",
                {"query": "test"},
            )
        with self.assertRaises(ValueError):
            firecrawl_search.make_search_request(
                "https://firecrawl.internal",
                "https://other.internal",
                "top-secret",
                {"query": "test"},
            )
        request = firecrawl_search.make_search_request(
            "https://firecrawl.internal",
            "https://firecrawl.internal",
            "top-secret",
            {"query": "test"},
        )
        self.assertEqual(request.full_url, "https://firecrawl.internal/v2/search")
        self.assertEqual(header_value(request, "Authorization"), "Bearer top-secret")

    def test_official_origin_is_explicitly_trusted_in_code(self) -> None:
        request = firecrawl_search.make_search_request(
            firecrawl_search.DEFAULT_FIRECRAWL_ORIGIN,
            None,
            "top-secret",
            {"query": "test"},
        )
        self.assertEqual(header_value(request, "Authorization"), "Bearer top-secret")


class RedirectSecurityTests(unittest.TestCase):
    def test_cross_origin_redirects_strip_all_sensitive_headers(self) -> None:
        for module in (external_signal_collect, source_health, firecrawl_search):
            with self.subTest(module=module.__name__):
                original = Request(
                    "https://trusted.example/start",
                    headers={
                        "Authorization": "Bearer top-secret",
                        "X-WorldMonitor-Key": "top-secret",
                    },
                )
                redirected = module.CredentialSafeRedirectHandler().redirect_request(
                    original,
                    None,
                    302,
                    "Found",
                    {},
                    "https://other.example/end",
                )
                self.assertIsNotNone(redirected)
                self.assertIsNone(header_value(redirected, "Authorization"))
                self.assertIsNone(header_value(redirected, "X-WorldMonitor-Key"))

    def test_same_origin_redirect_preserves_authorization(self) -> None:
        original = Request(
            "https://trusted.example/start",
            headers={"Authorization": "Bearer top-secret"},
        )
        redirected = firecrawl_search.CredentialSafeRedirectHandler().redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://trusted.example/end",
        )
        self.assertEqual(header_value(redirected, "Authorization"), "Bearer top-secret")


class CaptureNetworkBoundaryTests(unittest.TestCase):
    def test_browser_capture_rejects_private_targets_before_bridge_startup(self) -> None:
        for url in (
            "http://127.0.0.1/internal",
            "http://[::1]/internal",
            "http://localhost/internal",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    browser_capture.safe_public_url(url)

    def test_source_intake_rejects_private_discovery_candidates_before_fetch(self) -> None:
        candidate = {
            "verification": "discovery_only",
            "url": "http://127.0.0.1/document.pdf",
            "source_url": "http://127.0.0.1/discovery",
        }
        with patch.object(source_intake, "fetch") as fetch_mock:
            record = source_intake.capture_candidate(candidate, Path("."), 10)
        fetch_mock.assert_not_called()
        self.assertEqual("rejected_network_target", record["result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
