#!/usr/bin/env python3
"""Offline release regression suite for Luopan security and semantics."""

from __future__ import annotations

import copy
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import browser_capture
import collection_common
import external_discovery
import external_signal_collect
import firecrawl_search
import government_pdf_collect
import investment_calculate
import merge_fragment
import monitor_evaluate
import procurement_collect
import render_report
import scenario_backtest
import scenario_calculate
import snapshot_diff
import source_health
import source_discovery
import source_intake
import vertical_plan
from validate_research import load_json, schema_validate, semantic_validate


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
    def __init__(
        self,
        payload: bytes = b"{}",
        url: str = "https://example.test/feed",
        status: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self.payload = payload
        self.url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self.payload
        payload, self.payload = self.payload[:size], self.payload[size:]
        return payload

    def geturl(self) -> str:
        return self.url


def validation_messages(data: dict) -> tuple[list[str], list[str]]:
    schema = load_json(SKILL_ROOT / "research.schema.json")
    schema_messages = schema_validate(data, schema)
    errors = [item for item in schema_messages if not item.startswith("WARNING:")]
    warnings = [item for item in schema_messages if item.startswith("WARNING:")]
    semantic_errors, semantic_warnings = semantic_validate(data)
    return errors + semantic_errors, warnings + semantic_warnings


class ResearchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")

    def test_positive_fixtures(self) -> None:
        for name in (
            "deep-synthetic.json", "manufacturing-minimal.json",
            "private-sparse-minimal.json", "investment-synthetic.json",
        ):
            with self.subTest(name=name):
                errors, _ = validation_messages(load_json(SKILL_ROOT / "examples" / name))
                self.assertEqual([], errors)

    def test_investment_mode_fails_closed_on_missing_or_inconsistent_inputs(self) -> None:
        fixture = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")

        missing_context = copy.deepcopy(fixture)
        del missing_context["investment_context"]
        errors, _ = validation_messages(missing_context)
        self.assertTrue(any("requires non-empty investment_context" in item for item in errors))

        missing_price_evidence = copy.deepcopy(fixture)
        missing_price_evidence["investment_context"]["reference_value_evidence_ids"] = []
        errors, _ = validation_messages(missing_price_evidence)
        self.assertTrue(any("requires reference price evidence" in item for item in errors))

        one_sided = copy.deepcopy(fixture)
        one_sided["valuation_scenarios"] = [
            item for item in one_sided["valuation_scenarios"] if item["case"] != "downside"
        ]
        one_sided["investment_conclusion"]["stance"] = "consider_entry"
        errors, _ = validation_messages(one_sided)
        self.assertTrue(any("requires downside, base, and upside cases" in item for item in errors))

        wrong_position = copy.deepcopy(fixture)
        wrong_position["investment_conclusion"]["stance"] = "hold"
        errors, _ = validation_messages(wrong_position)
        self.assertTrue(any("stance hold requires position_status held" in item for item in errors))

        tampered_return = copy.deepcopy(fixture)
        tampered_return["valuation_scenarios"][1]["expected_annual_return"] = 0.99
        errors, _ = validation_messages(tampered_return)
        self.assertTrue(any("expected_annual_return does not match" in item for item in errors))

    def test_investment_sections_cannot_hide_under_intelligence_purpose(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        data["meta"]["research_purpose"] = "intelligence"
        errors, _ = validation_messages(data)
        self.assertTrue(any("investment sections require" in item for item in errors))

    def test_income_unsuitable_can_omit_distribution_scenarios(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        data["income_analysis"]["classification"] = "unsuitable"
        data["income_analysis"]["scenarios"] = []
        errors, _ = validation_messages(data)
        self.assertFalse(any("income lens requires base, adverse, and severe scenarios" in item for item in errors))

    def test_income_distributing_classification_still_requires_all_scenarios(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        data["income_analysis"]["classification"] = "durable_income"
        data["income_analysis"]["scenarios"] = []
        errors, _ = validation_messages(data)
        self.assertTrue(any("income lens requires base, adverse, and severe scenarios" in item for item in errors))

    def test_decimal_investment_calculator_generates_ordered_returns(self) -> None:
        payload = investment_calculate.load_payload(
            SKILL_ROOT / "examples" / "investment-calculator-input.json"
        )
        rows = investment_calculate.calculate(payload)
        self.assertEqual(["downside", "base", "upside"], [row["case"] for row in rows])
        self.assertAlmostEqual(-0.3, rows[0]["expected_total_return"], places=12)
        self.assertAlmostEqual(0.069610375725, rows[1]["expected_annual_return"], places=12)
        self.assertAlmostEqual(0.170804912965, rows[2]["expected_annual_return"], places=12)

    def test_investment_report_renders_context_theses_and_scenarios(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        markdown_text = render_report.render_markdown(data)
        self.assertIn("研究目的：investment", markdown_text)
        self.assertIn("专项镜头：earnings_delta / thesis_drift / management / income / decision_audit", markdown_text)
        self.assertIn("## 投资视角", markdown_text)
        self.assertIn("### 核心投资论点", markdown_text)
        self.assertIn("### 三情景估值", markdown_text)
        self.assertIn("## 财报与经营变化", markdown_text)
        self.assertIn("## 管理层承诺兑现台账", markdown_text)
        self.assertIn("## 资本配置行为", markdown_text)
        self.assertIn("### 投资论文漂移", markdown_text)
        self.assertIn("### 收益投资专项", markdown_text)
        self.assertIn("### 投资决策审计", markdown_text)
        self.assertIn("17.1%", markdown_text)
        for locator in (
            "2026 年度申报收入章节",
            "2025 年度申报收入章节",
            "2025 年度申报管理层指引",
            "2026 年度申报指引复核",
            "2026 年度申报现金流章节",
        ):
            self.assertIn(locator, markdown_text)
        self.assertIn(
            "[合成企业年度申报 · 2026 年度申报收入章节](https://example.com/synthetic-filing)",
            markdown_text,
        )

    def test_optional_lenses_do_not_burden_ordinary_research(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        errors, _ = validation_messages(data)
        self.assertEqual([], errors)
        markdown_text = render_report.render_markdown(data)
        self.assertIn("专项镜头：无", markdown_text)
        self.assertNotIn("财报与经营变化", markdown_text)
        self.assertNotIn("收益投资专项", markdown_text)
        self.assertNotIn("投资决策审计", markdown_text)

        missing_route = copy.deepcopy(data)
        missing_route["meta"].pop("analysis_lenses", None)
        errors, _ = validation_messages(missing_route)
        self.assertTrue(any("analysis_lenses" in item and "required" in item for item in errors))

    def test_routing_fields_unknown_properties_and_compare_fail_closed(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        for field in ("research_purpose", "analysis_lenses", "information_regime"):
            missing = copy.deepcopy(data)
            missing["meta"].pop(field)
            errors, _ = validation_messages(missing)
            self.assertTrue(any(field in item and "required" in item for item in errors))

        compare = copy.deepcopy(data)
        compare["meta"]["mode"] = "compare"
        errors, _ = validation_messages(compare)
        self.assertTrue(any("SCHEMA meta.mode" in item for item in errors))

        typo = copy.deepcopy(data)
        typo["competitor"] = typo.pop("competitors")
        errors, _ = validation_messages(typo)
        self.assertTrue(any("Additional properties are not allowed" in item for item in errors))

    def test_blocked_router_matrix_preserves_purpose_lens_boundaries(self) -> None:
        lens_names = [
            "earnings_delta", "thesis_drift", "management",
            "income", "bottleneck", "decision_audit",
        ]
        for mode in ("quick", "standard", "deep"):
            for purpose in ("intelligence", "investment", "both"):
                for mask in range(1 << len(lens_names)):
                    lenses = [
                        name for index, name in enumerate(lens_names)
                        if mask & (1 << index)
                    ]
                    data = {
                        "meta": {
                            "title": "Router matrix",
                            "generated_at": "2026-07-26T00:00:00+08:00",
                            "mode": mode,
                            "research_purpose": purpose,
                            "analysis_lenses": lenses,
                            "verification_mode": "none",
                            "research_status": "blocked",
                            "information_regime": "unknown",
                        },
                        "scope": {
                            "subject": "Unresolved subject",
                            "geography": "Unknown",
                            "timeframe": "Current",
                            "decision_question": "Resolve routing before research",
                        },
                        "intake": {
                            "interaction_mode": "defaults_disclosed",
                            "assumptions": ["Synthetic router test."],
                            "unresolved_questions": ["Identity is unresolved."],
                        },
                        "sources": [],
                        "evidence": [],
                        "entities": [],
                        "claims": [],
                        "key_unknowns": ["Identity is unresolved."],
                        "limitations": ["Synthetic router test."],
                    }
                    errors, _ = validation_messages(data)
                    illegal = purpose == "intelligence" and bool(
                        {"thesis_drift", "income", "decision_audit"} & set(lenses)
                    )
                    with self.subTest(mode=mode, purpose=purpose, lenses=lenses):
                        if illegal:
                            self.assertTrue(any("requires meta.research_purpose" in item for item in errors))
                        else:
                            self.assertEqual([], errors)

    def test_lens_sections_require_explicit_routing_and_outputs(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        undeclared = copy.deepcopy(data)
        undeclared["meta"]["analysis_lenses"] = []
        errors, _ = validation_messages(undeclared)
        self.assertTrue(any("period_reviews requires analysis_lenses" in item for item in errors))
        self.assertTrue(any("income_analysis requires analysis_lenses" in item for item in errors))

        missing_output = copy.deepcopy(data)
        del missing_output["period_reviews"]
        errors, _ = validation_messages(missing_output)
        self.assertTrue(any("earnings_delta lens requires" in item for item in errors))

    def test_investment_only_lenses_reject_intelligence_routing(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        data["meta"]["research_purpose"] = "intelligence"
        errors, _ = validation_messages(data)
        self.assertTrue(any("thesis_drift lens requires" in item for item in errors))
        self.assertTrue(any("income lens requires" in item for item in errors))
        self.assertTrue(any("decision_audit lens requires" in item for item in errors))

    def test_decision_audit_requires_six_consistent_gates_and_fails_closed(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")

        missing_gate = copy.deepcopy(data)
        missing_gate["decision_audit"]["gates"] = missing_gate["decision_audit"]["gates"][:-1]
        errors, _ = validation_messages(missing_gate)
        self.assertTrue(any("decision_audit.gates missing" in item for item in errors))

        wrong_status = copy.deepcopy(data)
        wrong_status["decision_audit"]["overall_status"] = "ready"
        errors, _ = validation_messages(wrong_status)
        self.assertTrue(any("failed gate requires overall_status blocked" in item for item in errors))

        unsupported_entry = copy.deepcopy(data)
        unsupported_entry["investment_conclusion"]["stance"] = "consider_entry"
        errors, _ = validation_messages(unsupported_entry)
        self.assertTrue(any("must be ready before consider_entry" in item for item in errors))

        no_evidence = copy.deepcopy(data)
        gate = next(item for item in no_evidence["decision_audit"]["gates"] if item["gate"] == "evidence_sufficiency")
        gate["evidence_ids"] = []
        errors, _ = validation_messages(no_evidence)
        self.assertTrue(any("evidence-based pass/fail requires evidence_ids" in item for item in errors))

        conflicting_flags = copy.deepcopy(data)
        conflicting_flags["decision_audit"]["behavioral_flags"] = ["none", "fomo"]
        errors, _ = validation_messages(conflicting_flags)
        self.assertTrue(any("none cannot coexist" in item for item in errors))

        unrelated_answer = copy.deepcopy(data)
        gate = next(item for item in unrelated_answer["decision_audit"]["gates"] if item["gate"] == "downside_survivability")
        gate.update({"status": "pass", "user_answer_indices": [99]})
        errors, _ = validation_messages(unrelated_answer)
        self.assertTrue(any("user_answer_indices must reference" in item for item in errors))

        missing_conditions = copy.deepcopy(data)
        audit = missing_conditions["decision_audit"]
        audit["overall_status"] = "conditional"
        for gate in audit["gates"]:
            gate["status"] = "pass"
            if gate["basis"] == "user_input":
                gate["user_answer_indices"] = [0]
        audit["behavioral_flags"] = ["none"]
        errors, _ = validation_messages(missing_conditions)
        self.assertTrue(any("conditional decision_audit requires" in item for item in errors))

        ready_with_conditions = copy.deepcopy(missing_conditions)
        ready_with_conditions["decision_audit"]["overall_status"] = "ready"
        ready_with_conditions["decision_audit"]["conditions"] = ["等待用户确认机会成本"]
        errors, _ = validation_messages(ready_with_conditions)
        self.assertTrue(any("ready decision_audit cannot retain" in item for item in errors))

        invalid_add = copy.deepcopy(data)
        invalid_add["decision_audit"]["stage"] = "add_position"
        errors, _ = validation_messages(invalid_add)
        self.assertTrue(any("add_position decision_audit requires position_status held" in item for item in errors))

        invalid_initial = copy.deepcopy(data)
        invalid_initial["investment_context"]["position_status"] = "held"
        errors, _ = validation_messages(invalid_initial)
        self.assertTrue(any("initial_entry decision_audit requires position_status not_held" in item for item in errors))

        unknown_initial = copy.deepcopy(data)
        unknown_initial["investment_context"]["position_status"] = "unknown"
        errors, _ = validation_messages(unknown_initial)
        self.assertTrue(any("initial_entry decision_audit requires position_status not_held" in item for item in errors))

    def test_temporal_lenses_fail_closed_on_fake_deltas_and_drift(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        same_evidence = copy.deepcopy(data)
        delta = same_evidence["period_reviews"][0]["metric_deltas"][0]
        delta["comparison_evidence_ids"] = list(delta["current_evidence_ids"])
        errors, _ = validation_messages(same_evidence)
        self.assertTrue(any("substantively distinct evidence" in item for item in errors))

        fake_value = copy.deepcopy(data)
        fake_value["period_reviews"][0]["metric_deltas"][0]["comparison_value"] = 999999
        errors, _ = validation_messages(fake_value)
        self.assertTrue(any("numeric value 999999" in item for item in errors))

        cloned_evidence = copy.deepcopy(data)
        original = next(item for item in cloned_evidence["evidence"] if item["id"] == "evd-revenue-current")
        clone = copy.deepcopy(original)
        clone["id"] = "evd-revenue-current-clone"
        cloned_evidence["evidence"].append(clone)
        cloned_evidence["period_reviews"][0]["metric_deltas"][0]["comparison_evidence_ids"] = [clone["id"]]
        errors, _ = validation_messages(cloned_evidence)
        self.assertTrue(any("substantively distinct evidence" in item for item in errors))

        reused_commitment = copy.deepcopy(data)
        reused_commitment["management_commitments"][0]["outcome_evidence_ids"] = ["evd-promise"]
        errors, _ = validation_messages(reused_commitment)
        self.assertTrue(any("outcome evidence must be substantively distinct" in item for item in errors))

        premature_miss = copy.deepcopy(data)
        commitment = premature_miss["management_commitments"][0]
        commitment["status"] = "missed"
        commitment["due_at"] = "2027-12-31"
        errors, _ = validation_messages(premature_miss)
        self.assertTrue(any("cannot be marked missed before due_at" in item for item in errors))

        no_trigger = copy.deepcopy(data)
        no_trigger["thesis_changes"][0]["trigger_evidence_ids"] = []
        errors, _ = validation_messages(no_trigger)
        self.assertTrue(any("material thesis change requires" in item for item in errors))

        stale_trigger = copy.deepcopy(data)
        stale_trigger["thesis_changes"][0]["trigger_evidence_ids"] = ["evd-revenue-prior"]
        next(item for item in stale_trigger["evidence"] if item["id"] == "evd-revenue-prior")["observed_at"] = "2026-07-01"
        errors, _ = validation_messages(stale_trigger)
        self.assertTrue(any("trigger evidence sources must be published after" in item for item in errors))

        wording_changes_status = copy.deepcopy(data)
        change = wording_changes_status["thesis_changes"][0]
        change["change_type"] = "wording_only"
        change["previous_status"] = "supported"
        errors, _ = validation_messages(wording_changes_status)
        self.assertTrue(any("wording_only cannot change" in item for item in errors))

    def test_income_lens_requires_downside_cases_and_respects_blocking_gates(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        missing_severe = copy.deepcopy(data)
        missing_severe["income_analysis"]["scenarios"] = [
            row for row in missing_severe["income_analysis"]["scenarios"]
            if row["case"] != "severe"
        ]
        errors, _ = validation_messages(missing_severe)
        self.assertTrue(any("base, adverse, and severe" in item for item in errors))

        failed_gate = copy.deepcopy(data)
        failed_gate["income_analysis"]["blocking_gates"][0]["status"] = "fail"
        failed_gate["investment_conclusion"]["stance"] = "consider_entry"
        errors, _ = validation_messages(failed_gate)
        self.assertTrue(any("unresolved or failed income blocking gate" in item for item in errors))

        unknown_gate = copy.deepcopy(data)
        unknown_gate["investment_conclusion"]["stance"] = "consider_entry"
        errors, _ = validation_messages(unknown_gate)
        self.assertTrue(any("unresolved or failed income blocking gate" in item for item in errors))

        rumor_backed = copy.deepcopy(data)
        source = next(item for item in rumor_backed["sources"] if item["id"] == "src-filing-investment")
        source["verification"] = "unverified"
        evidence = next(item for item in rumor_backed["evidence"] if item["id"] == "evd-income-cash")
        evidence["evidence_kind"] = "rumor"
        errors, _ = validation_messages(rumor_backed)
        self.assertTrue(any("rumor evidence cannot support this structured result" in item for item in errors))
        self.assertTrue(any("requires verified or corroborated sources" in item for item in errors))

        fake_coverage = copy.deepcopy(data)
        fake_coverage["income_analysis"]["coverage_metrics"][0]["value"] = 999999
        errors, _ = validation_messages(fake_coverage)
        self.assertTrue(any("numeric value 999999" in item for item in errors))

        fake_scenario = copy.deepcopy(data)
        fake_scenario["income_analysis"]["scenarios"][0]["distributable_cash"] = 999999
        fake_scenario["income_analysis"]["scenarios"][0]["payout_coverage"] = 999999
        errors, _ = validation_messages(fake_scenario)
        self.assertTrue(any("distributable_cash does not equal" in item for item in errors))
        self.assertTrue(any("payout_coverage does not match" in item for item in errors))

        fake_formula = copy.deepcopy(data)
        fake_formula["income_analysis"]["scenarios"][0]["calculation"]["formula"] = "1 + 1 = 999999"
        errors, _ = validation_messages(fake_formula)
        self.assertTrue(any("calculation.formula" in item for item in errors))

        fake_capital = copy.deepcopy(data)
        fake_capital["capital_allocation_events"][0]["amount"] = 999999
        errors, _ = validation_messages(fake_capital)
        self.assertTrue(any("amount is absent from cited evidence" in item for item in errors))

        fake_capital_date = copy.deepcopy(data)
        fake_capital_date["capital_allocation_events"][0]["announced_at"] = "2026-12-31"
        errors, _ = validation_messages(fake_capital_date)
        self.assertTrue(any("exact announced_at date is absent" in item for item in errors))
        self.assertTrue(any("announced_at cannot be later" in item for item in errors))

        unknown_amount_fake_date = copy.deepcopy(data)
        event = unknown_amount_fake_date["capital_allocation_events"][0]
        event["amount"] = None
        event["currency"] = None
        event["announced_at"] = "2026-02-28"
        errors, _ = validation_messages(unknown_amount_fake_date)
        self.assertTrue(any("exact announced_at date is absent" in item for item in errors))

    def test_bottleneck_lens_requires_evidence_depth_for_high_confidence(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        node = data["bottleneck_nodes"][0]
        node["bottleneck_status"] = "confirmed"
        node["confidence"] = "high"
        errors, _ = validation_messages(data)
        self.assertTrue(any("requires two independent supporting sources" in item for item in errors))
        self.assertTrue(any("requires four observed dimensions" in item for item in errors))

        ordinary_fake_values = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        ordinary_node = ordinary_fake_values["bottleneck_nodes"][0]
        ordinary_node.update({
            "supply_concentration": 0.99,
            "expansion_lead_time_months": 999,
            "capacity_utilization": 0.98,
            "demand_growth": 9.99,
        })
        errors, _ = validation_messages(ordinary_fake_values)
        for field in (
            "supply_concentration", "expansion_lead_time_months",
            "capacity_utilization", "demand_growth",
        ):
            self.assertTrue(any(f"{field} value is absent" in item for item in errors))

        clone = copy.deepcopy(next(item for item in data["evidence"] if item["id"] == "evd-filing"))
        clone["id"] = "evd-filing-clone"
        data["evidence"].append(clone)
        node["evidence_ids"] = ["evd-filing", "evd-filing-clone"]
        node["supply_concentration"] = 0.8
        node["capacity_utilization"] = 0.9
        errors, _ = validation_messages(data)
        self.assertTrue(any("requires two independent supporting sources" in item for item in errors))

        independent = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        node = independent["bottleneck_nodes"][0]
        node.update({
            "bottleneck_status": "confirmed",
            "confidence": "high",
            "supply_concentration": 0.8,
            "expansion_lead_time_months": 24,
            "capacity_utilization": 0.9,
            "qualification_lead_time_months": 12,
            "profit_capture": "strong",
            "evidence_ids": ["evd-bn-a", "evd-bn-b"],
        })
        for source_id, publisher, url, excerpt in (
            ("src-bn-a", "Independent Supplier", "https://supplier.example/capacity", "供应商集中度为 80%，有效产能利用率为 90%。"),
            ("src-bn-b", "Independent Customer", "https://customer.example/qualification", "扩产周期为 24 个月，客户认证周期为 12 个月。"),
        ):
            independent["sources"].append({
                "id": source_id,
                "title": publisher + " bottleneck record",
                "url": url,
                "publisher": publisher,
                "published_at": "2026-05-01",
                "retrieved_at": "2026-07-12",
                "authority": "secondary",
                "evidence_type": "research",
                "verification": "verified",
                "excerpt": excerpt,
                "content_hash": None,
            })
            independent["evidence"].append({
                "id": "evd-bn-a" if source_id == "src-bn-a" else "evd-bn-b",
                "source_id": source_id,
                "locator": "bottleneck paragraph",
                "excerpt": excerpt,
                "stance": "supports",
                "evidence_kind": "reported_fact",
                "observed_at": "2026-05-01",
                "subject_ids": ["ent-company"],
            })
        errors, _ = validation_messages(independent)
        self.assertEqual([], errors)
        independent["bottleneck_nodes"][0]["expansion_lead_time_months"] = 999
        errors, _ = validation_messages(independent)
        self.assertTrue(any("expansion_lead_time_months value is absent" in item for item in errors))

    def test_bottleneck_report_is_separate_from_base_supply_chain(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        markdown_text = render_report.render_markdown(data)
        self.assertIn("## 产品上下游链群", markdown_text)
        self.assertIn("年度报告产品章节", markdown_text)
        self.assertIn("## 供应链瓶颈判断", markdown_text)

    def test_declared_negative_fixtures(self) -> None:
        names = (
            "invalid-date-format.json",
            "invalid-discovery-source.json",
            "invalid-external-shortcut.json",
            "invalid-exposure-only-external.json",
        )
        for name in names:
            with self.subTest(name=name):
                errors, _ = validation_messages(load_json(SKILL_ROOT / "examples" / name))
                self.assertTrue(errors)

    def test_untrusted_rumor_cannot_support_high_fact(self) -> None:
        data = copy.deepcopy(self.fixture)
        source = next(item for item in data["sources"] if item["id"] == "src-filing")
        source.update({"authority": "tertiary", "verification": "unverified", "evidence_type": "rumor"})
        evidence = next(item for item in data["evidence"] if item["id"] == "evd-filing")
        evidence["evidence_kind"] = "rumor"
        claim = data["claims"][0]
        claim.update({"claim_type": "fact", "confidence": "high"})
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("fact claim cannot use rumor evidence", joined)
        self.assertIn("high-confidence claim cites unverified sources", joined)

    def test_self_references_are_rejected(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["products"][0]["evidence_ids"] = [data["products"][0]["id"]]
        data["claims"][0]["counter_evidence_ids"] = [data["claims"][0]["id"]]
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("self-reference is forbidden", joined)

    def test_empty_standard_is_rejected_but_blocked_minimal_is_valid(self) -> None:
        empty = {
            "meta": {
                "title": "Empty",
                "generated_at": "2026-07-24T00:00:00+08:00",
                "mode": "standard",
                "research_purpose": "intelligence",
                "analysis_lenses": [],
                "verification_mode": "none",
                "research_status": "partial",
                "information_regime": "unknown",
            },
            "scope": {"subject": "", "geography": "", "timeframe": "", "decision_question": ""},
            "sources": [],
            "evidence": [],
            "entities": [],
            "claims": [],
            "limitations": ["No evidence"],
            "key_unknowns": ["Everything"],
        }
        errors, _ = validation_messages(empty)
        self.assertTrue(any("non-blocked research requires non-empty claims" in item for item in errors))
        self.assertTrue(any("scope.decision_question" in item for item in errors))

        blocked = copy.deepcopy(empty)
        blocked["meta"]["research_status"] = "blocked"
        blocked["scope"] = {
            "subject": "Unknown company",
            "geography": "Unknown",
            "timeframe": "Current",
            "decision_question": "Resolve identity before analysis",
        }
        blocked_errors, _ = validation_messages(blocked)
        self.assertEqual([], blocked_errors)

    def test_nonfinite_json_and_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nan.json"
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(path)
        data = copy.deepcopy(self.fixture)
        data["metrics"] = [{
            "id": "met-nan",
            "name": "bad",
            "value": float("nan"),
            "unit": "units",
            "period": "2026",
            "scope": "fixture",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-filing"],
        }]
        errors, _ = validation_messages(data)
        self.assertTrue(any("non-finite number" in item for item in errors))

    def test_metric_sign_must_match_excerpt(self) -> None:
        data = copy.deepcopy(self.fixture)
        evidence = next(item for item in data["evidence"] if item["id"] == "evd-filing")
        evidence["excerpt"] = "The observed change was 10 units."
        data["metrics"] = [{
            "id": "met-sign",
            "name": "signed change",
            "value": -10,
            "unit": "units",
            "period": "2026",
            "scope": "fixture",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-filing"],
        }]
        errors, _ = validation_messages(data)
        self.assertTrue(any("numeric value -10" in item for item in errors))

    def test_actual_metric_period_and_scope_must_match_excerpt(self) -> None:
        data = copy.deepcopy(self.fixture)
        statement = "Segment A revenue was 30 billion yuan in 2024."
        source = next(item for item in data["sources"] if item["id"] == "src-filing")
        evidence = next(item for item in data["evidence"] if item["id"] == "evd-filing")
        source["excerpt"] = statement
        evidence["excerpt"] = statement
        data["metrics"] = [{
            "id": "met-bound",
            "name": "segment revenue",
            "value": 30,
            "unit": "billion yuan",
            "period": "2030",
            "scope": "Segment Z",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-filing"],
        }]
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("period '2030' is absent", joined)
        self.assertIn("scope 'Segment Z' is absent", joined)

    def test_claim_support_rejects_contradictions_and_direct_sources(self) -> None:
        contradictory = copy.deepcopy(self.fixture)
        contradictory["evidence"][0]["stance"] = "contradicts"
        errors, _ = validation_messages(contradictory)
        self.assertTrue(any("supporting evidence is marked contradicts" in item for item in errors))

        direct_source = copy.deepcopy(self.fixture)
        source = next(item for item in direct_source["sources"] if item["id"] == "src-filing")
        source.update({"authority": "primary", "evidence_type": "rumor", "verification": "verified"})
        direct_source["claims"][0].update({
            "claim_type": "fact",
            "confidence": "high",
            "evidence_ids": ["src-filing"],
        })
        errors, _ = validation_messages(direct_source)
        self.assertTrue(any("not source records" in item for item in errors))

    def test_exposure_rejects_external_metric_wrapper(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["sources"].append({
            "id": "src-external-feed",
            "title": "External feed",
            "url": "https://signals.example/feed",
            "publisher": "Signals Example",
            "published_at": "2026-07-12",
            "retrieved_at": "2026-07-12T12:00:00+08:00",
            "authority": "secondary",
            "evidence_type": "shipping",
            "source_perspective": "behavioral_data",
            "verification": "unverified",
            "excerpt": "External shipping delay index is 1.",
            "content_hash": None,
        })
        data["evidence"].append({
            "id": "evd-external-feed",
            "source_id": "src-external-feed",
            "locator": "record[0]",
            "excerpt": "External shipping delay index is 1.",
            "stance": "context",
            "evidence_kind": "reported_fact",
            "observed_at": "2026-07-12T12:00:00+08:00",
            "subject_ids": [],
            "quality_flags": ["aggregated_feed"],
        })
        data["external_signals"][0]["evidence_ids"] = ["evd-external-feed"]
        data.setdefault("metrics", []).append({
            "id": "met-external-wrapper",
            "name": "external wrapper",
            "value": 1,
            "unit": "index",
            "period": "2026",
            "scope": "external signal only",
            "metric_type": "estimate",
            "source_ids": ["src-external-feed"],
            "evidence_ids": ["evd-external-feed"],
        })
        data["exposure_links"][0]["evidence_ids"] = ["met-external-wrapper"]
        errors, _ = validation_messages(data)
        self.assertTrue(any("lacks usable enterprise evidence" in item for item in errors))

    def test_deep_coverage_and_independent_sources_are_real(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        for row in data["source_coverage"]:
            row["source_ids"] = ["src-company"]
        errors, _ = validation_messages(data)
        self.assertTrue(any("source perspective mismatch" in item for item in errors))

        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        claim = data["claims"][0]
        claim.update({"claim_type": "fact", "confidence": "high"})
        cited_source_ids = {
            next(item for item in data["evidence"] if item["id"] == evidence_id)["source_id"]
            for evidence_id in claim["evidence_ids"]
        }
        for source in data["sources"]:
            if source["id"] in cited_source_ids:
                source.update({
                    "authority": "secondary",
                    "verification": "verified",
                    "publisher": "Same Publisher",
                    "url": "https://same.example/copied",
                    "content_hash": "same-content",
                })
        errors, _ = validation_messages(data)
        self.assertTrue(any("distinct publishers, canonical URLs" in item for item in errors))

    def test_deep_covered_sources_must_be_usable(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        customer = next(item for item in data["sources"] if item["id"] == "src-customer")
        customer.update({"verification": "discovery_only", "excerpt": "   "})
        errors, _ = validation_messages(data)
        self.assertTrue(any("source_coverage[customer]" in item and "non-discovery" in item for item in errors))

    def test_high_fact_requires_distinct_urls_publishers_and_hashes(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        claim = data["claims"][0]
        claim.update({"claim_type": "fact", "confidence": "high"})
        claim["claim_components"][0]["confidence"] = "high"
        for source_id, publisher in (("src-company", "Publisher A"), ("src-customer", "Publisher B")):
            source = next(item for item in data["sources"] if item["id"] == source_id)
            source.update({
                "authority": "secondary",
                "publisher": publisher,
                "url": "https://same.example/report?utm_source=test",
                "content_hash": None,
            })
        errors, _ = validation_messages(data)
        self.assertTrue(any("distinct publishers, canonical URLs" in item for item in errors))

    def test_high_fact_rejects_republished_identical_source_excerpts(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        claim = data["claims"][0]
        claim.update({"claim_type": "fact", "confidence": "high"})
        cited_source_ids = {
            next(item for item in data["evidence"] if item["id"] == evidence_id)["source_id"]
            for evidence_id in claim["evidence_ids"]
        }
        for number, source_id in enumerate(sorted(cited_source_ids), 1):
            source = next(item for item in data["sources"] if item["id"] == source_id)
            source.update({
                "authority": "secondary",
                "verification": "verified",
                "publisher": f"Publisher {number}",
                "url": f"https://publisher-{number}.example/report",
                "content_hash": f"{number:064x}",
                "excerpt": "Identical syndicated statement.",
            })
            for evidence in data["evidence"]:
                if evidence["source_id"] == source_id:
                    evidence["excerpt"] = "Identical syndicated statement."
        errors, _ = validation_messages(data)
        self.assertTrue(any("source excerpts" in item for item in errors))

    def test_whitespace_evidence_and_actual_string_metric_are_rejected(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["evidence"][0]["excerpt"] = " \t "
        data["metrics"] = [{
            "id": "met-string-actual",
            "name": "actual disguised as text",
            "value": "10",
            "unit": "units",
            "period": "2026",
            "scope": "fixture",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-filing"],
        }]
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("excerpt", joined)
        self.assertIn("actual metric value must be numeric", joined)

    def test_high_inference_counter_search_requires_real_contradiction(self) -> None:
        data = copy.deepcopy(self.fixture)
        claim = data["claims"][0]
        claim.update({
            "claim_type": "inference",
            "confidence": "high",
            "counter_search_status": "searched_found",
            "counter_evidence_ids": [],
            "falsifier": "A contrary filing appears.",
        })
        errors, _ = validation_messages(data)
        self.assertTrue(any("searched_found requires counter_evidence_ids" in item for item in errors))

        claim["counter_evidence_ids"] = ["evd-filing"]
        errors, _ = validation_messages(data)
        self.assertTrue(any("counter evidence must use contradicts stance" in item for item in errors))

    def test_complete_private_sparse_cannot_mark_material_footprints_not_applicable(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "private-sparse-minimal.json")
        data["meta"]["research_status"] = "complete"
        for row in data["footprint_coverage"]:
            row["status"] = "not_applicable"
        errors, _ = validation_messages(data)
        self.assertTrue(any("complete private_sparse research has material footprint gaps" in item for item in errors))

    def test_dates_and_source_userinfo_are_validated(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["sources"][0]["published_at"] = "not-a-date"
        data["sources"][0]["retrieved_at"] = "tomorrow-ish"
        data["sources"][0]["url"] = "https://user:secret@example.com/report"
        data["evidence"][0]["observed_at"] = "32/99/never"
        data["external_signals"][0]["as_of"] = "soon"
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("published_at", joined)
        self.assertIn("retrieved_at", joined)
        self.assertIn("observed_at", joined)
        self.assertIn("as_of", joined)
        self.assertIn("invalid source URL", joined)

    def test_atomic_excerpt_must_be_present_in_source_excerpt(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["sources"][0]["excerpt"] = "The filing does not disclose revenue."
        data["evidence"][0]["excerpt"] = "Revenue is 999 billion yuan."
        data["claims"][0].update({"claim_type": "fact", "confidence": "high"})
        errors, _ = validation_messages(data)
        self.assertTrue(any("evidence excerpt is not present in its source excerpt" in item for item in errors))

    def test_discovery_only_cannot_support_claim_through_evidence(self) -> None:
        data = copy.deepcopy(self.fixture)
        source = next(item for item in data["sources"] if item["id"] == "src-filing")
        source["verification"] = "discovery_only"
        errors, _ = validation_messages(data)
        self.assertTrue(any("discovery-only sources cannot support claims through atomic evidence" in item for item in errors))

    def test_complete_deep_requires_trusted_sources_for_covered_perspectives(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        data["meta"]["research_status"] = "complete"
        for source in data["sources"]:
            source["verification"] = "unverified"
        errors, _ = validation_messages(data)
        self.assertTrue(any("complete deep research requires trusted excerpted sources" in item for item in errors))

    def test_atomic_evidence_requires_locator_and_observed_date(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["evidence"][0]["locator"] = "   "
        data["evidence"][0].pop("observed_at", None)
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("locator", joined)
        self.assertIn("observed_at", joined)

    def test_competitor_and_metric_source_lineage_must_match_evidence(self) -> None:
        deep = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        deep["competitors"][0]["evidence_ids"] = ["evd-company"]
        errors, _ = validation_messages(deep)
        self.assertTrue(any("evidence sources must be declared in competitor_source_ids" in item for item in errors))

        metric = copy.deepcopy(self.fixture)
        metric["metrics"] = [{
            "id": "met-lineage",
            "name": "mismatched lineage",
            "value": 30,
            "unit": "天",
            "period": "2026",
            "scope": "fixture",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-ux"],
        }]
        errors, _ = validation_messages(metric)
        self.assertTrue(any("source_ids must exactly match the sources behind evidence_ids" in item for item in errors))

    def test_complete_research_requires_limitations(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        data["meta"]["research_status"] = "complete"
        data["limitations"] = []
        errors, _ = validation_messages(data)
        self.assertTrue(any("limitations" in item for item in errors))

    def test_complete_research_cannot_skip_verification(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        data["meta"]["research_status"] = "complete"
        data["meta"]["verification_mode"] = "none"
        errors, _ = validation_messages(data)
        self.assertTrue(any("complete research requires self_review or independent" in item for item in errors))

    def test_high_components_inherit_source_trust(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        data["claims"][0]["claim_components"][0]["confidence"] = "high"
        source = next(item for item in data["sources"] if item["id"] == "src-company")
        source["verification"] = "unverified"
        errors, _ = validation_messages(data)
        self.assertTrue(any("high-confidence component requires only verified" in item for item in errors))

        source["verification"] = "discovery_only"
        errors, _ = validation_messages(data)
        self.assertTrue(any("discovery-only sources cannot support claim components" in item for item in errors))

    def test_exposure_rejects_discovery_only_enterprise_wrapper(self) -> None:
        data = copy.deepcopy(self.fixture)
        source = next(item for item in data["sources"] if item["id"] == "src-filing")
        source["verification"] = "discovery_only"
        data["exposure_links"][0]["evidence_ids"] = ["evd-filing"]
        errors, _ = validation_messages(data)
        self.assertTrue(any("lacks usable enterprise evidence" in item for item in errors))

    def test_complete_private_sparse_requires_resolved_identity_and_distinct_footprint_evidence(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "private-sparse-minimal.json")
        data["meta"]["research_status"] = "complete"
        for row in data["footprint_coverage"]:
            row.update({
                "status": "covered",
                "source_ids": ["src-registry-example"],
                "evidence_ids": ["evd-example-identity"],
                "gap_reason": None,
            })
        errors, _ = validation_messages(data)
        joined = "\n".join(errors)
        self.assertIn("requires resolved identity", joined)
        self.assertIn("require distinct atomic evidence", joined)

    def test_private_sparse_rejects_cloned_evidence_with_different_ids(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "private-sparse-minimal.json")
        data["meta"]["research_status"] = "complete"
        data["identity_resolution"]["resolution_status"] = "resolved"
        template = next(item for item in data["evidence"] if item["id"] == "evd-example-identity")
        for number, row in enumerate(data["footprint_coverage"], 1):
            clone = copy.deepcopy(template)
            clone["id"] = f"evd-clone-{number}"
            data["evidence"].append(clone)
            row.update({
                "status": "covered",
                "source_ids": [template["source_id"]],
                "evidence_ids": [clone["id"]],
                "gap_reason": None,
            })
        errors, _ = validation_messages(data)
        self.assertTrue(any("substantively distinct evidence" in item for item in errors))

    def test_structured_facts_inherit_source_trust(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        market = data["product_markets"][0]
        market["confidence"] = "high"
        source = next(item for item in data["sources"] if item["id"] == "src-company")
        source["verification"] = "unverified"
        errors, _ = validation_messages(data)
        self.assertTrue(any("high-confidence structured fact" in item for item in errors))

        source["verification"] = "discovery_only"
        market["confidence"] = "low"
        errors, _ = validation_messages(data)
        self.assertTrue(any("discovery-only sources cannot support structured facts" in item for item in errors))

        source["verification"] = "verified"
        market["confidence"] = "high"
        next(item for item in data["evidence"] if item["id"] == "evd-company")["stance"] = "context"
        next(item for item in data["evidence"] if item["id"] == "evd-customer")["stance"] = "context"
        errors, _ = validation_messages(data)
        self.assertTrue(any("high-confidence structured fact requires supporting atomic evidence" in item for item in errors))

    def test_missing_jsonschema_fails_closed(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                str(SCRIPT_DIR / "validate_research.py"),
                str(SKILL_ROOT / "examples" / "deep-synthetic.json"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("jsonschema is required", result.stdout + result.stderr)

    def test_primary_authority_cannot_be_self_declared_by_media(self) -> None:
        data = copy.deepcopy(self.fixture)
        source = next(item for item in data["sources"] if item["id"] == "src-filing")
        source.update({"authority": "primary", "evidence_type": "media"})
        data["claims"][0].update({"claim_type": "fact", "confidence": "high"})
        errors, _ = validation_messages(data)
        self.assertTrue(any("primary authority conflicts with media" in item for item in errors))

    def test_hashes_metric_units_and_market_share_are_bound_to_evidence(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        data["claims"][0].update({"claim_type": "fact", "confidence": "high"})
        for source_id, publisher, url, digest in (
            ("src-company", "Publisher A", "https://a.example/report", "a"),
            ("src-customer", "Publisher B", "https://b.example/report", "b"),
        ):
            source = next(item for item in data["sources"] if item["id"] == source_id)
            source.update({"authority": "secondary", "publisher": publisher, "url": url, "content_hash": digest})
        errors, _ = validation_messages(data)
        self.assertTrue(any("content_hash" in item for item in errors))

        metric = copy.deepcopy(self.fixture)
        metric["metrics"] = [{
            "id": "met-wrong-unit",
            "name": "wrong unit",
            "value": 30,
            "unit": "billion yuan",
            "period": "2026",
            "scope": "revenue",
            "metric_type": "actual",
            "source_ids": ["src-ux"],
            "evidence_ids": ["evd-ux"],
        }]
        errors, _ = validation_messages(metric)
        self.assertTrue(any("unit 'billion yuan' is absent" in item for item in errors))

        market = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        market["product_markets"][0].update({
            "market_share": 99.9,
            "share_unit": "%",
            "share_period": "2026",
            "share_basis": "revenue",
        })
        errors, _ = validation_messages(market)
        self.assertTrue(any("market_share 99.9 is absent" in item for item in errors))

    def test_exposure_evidence_must_bind_to_exposed_entity_or_product(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["sources"].append({
            "id": "src-unrelated",
            "title": "Unrelated verified source",
            "url": "https://unrelated.example/report",
            "publisher": "Unrelated",
            "published_at": "2026-07-01",
            "retrieved_at": "2026-07-12",
            "authority": "secondary",
            "evidence_type": "media",
            "source_perspective": "media",
            "verification": "verified",
            "excerpt": "An unrelated executive appointment was announced.",
            "content_hash": None,
        })
        data["evidence"].append({
            "id": "evd-unrelated",
            "source_id": "src-unrelated",
            "locator": "paragraph 1",
            "excerpt": "An unrelated executive appointment was announced.",
            "stance": "context",
            "evidence_kind": "reported_fact",
            "observed_at": "2026-07-01",
            "subject_ids": [],
            "quality_flags": [],
        })
        data["exposure_links"][0]["evidence_ids"] = ["evd-unrelated"]
        errors, _ = validation_messages(data)
        self.assertTrue(any("lacks usable enterprise evidence" in item for item in errors))

    def test_malformed_collection_types_return_errors_instead_of_crashing(self) -> None:
        data = copy.deepcopy(self.fixture)
        data["sources"] = "not-an-array"
        errors, _ = validation_messages(data)
        self.assertTrue(any("sources: must be an array" in item for item in errors))


class ReportSecurityTests(unittest.TestCase):
    def test_markdown_and_html_neutralize_active_content(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        data["evidence"][0]["excerpt"] = (
            '<script id="from-evidence">alert(1)</script>'
            '<iframe src="https://attacker.invalid"></iframe>'
            '<img src=x onerror="alert(2)">[click](javascript:alert(3))'
        )
        markdown_text = render_report.render_markdown(data)
        self.assertNotIn("<script", markdown_text.lower())
        self.assertNotIn("<iframe", markdown_text.lower())
        self.assertIn('&lt;script id="from-evidence"&gt;', markdown_text.lower())
        html_text = render_report.render_html(markdown_text, "Fixture")
        lowered = html_text.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<iframe", lowered)
        self.assertNotRegex(lowered, r"<[^>]+\bonerror\s*=")
        self.assertNotIn('href="javascript:', lowered)
        self.assertIn("content-security-policy", lowered)

    def test_sanitizer_removes_raw_dangerous_tags_and_urls(self) -> None:
        raw = '<p>ok</p><script>alert(1)</script><a href="javascript:alert(2)" onclick="x">bad</a>'
        sanitized = render_report.sanitize_report_html(raw).lower()
        self.assertEqual('<p>ok</p><a rel="noopener noreferrer">bad</a>', sanitized)

    def test_markdown_links_and_newlines_cannot_inject_structure(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        data["sources"][0]["url"] = "https://good.example/)[Injected](https://evil.example/"
        data["claims"][0]["statement"] = "Legitimate claim\n\n## Forged section"
        markdown_text = render_report.render_markdown(data)
        self.assertNotIn("\n## Forged section", markdown_text)
        html_text = render_report.render_html(markdown_text, "Fixture")
        self.assertNotIn("<h2>Forged section</h2>", html_text)
        self.assertGreaterEqual(len(re.findall(r"<a\s", html_text)), len(data["sources"]))

    def test_all_dynamic_table_cells_escape_column_delimiters(self) -> None:
        data = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        data["supply_chain_nodes"][0]["name"] = "Injected | column"
        data["metrics"] = [{
            "id": "met-table",
            "name": "Metric | injected",
            "value": 1,
            "unit": "u|nit",
            "period": "2026|Q1",
            "scope": "scope|extra",
            "metric_type": "actual",
            "source_ids": ["src-filing"],
            "evidence_ids": ["evd-filing"],
        }]
        markdown_text = render_report.render_markdown(data)
        self.assertIn("Injected \\| column", markdown_text)
        self.assertIn("Metric \\| injected", markdown_text)
        self.assertIn("u\\|nit", markdown_text)


class CredentialAndSignalTests(unittest.TestCase):
    @staticmethod
    def header_names(request) -> set[str]:
        return {name.lower() for name in request.headers} | {name.lower() for name in request.unredirected_hdrs}

    def test_domain_resolution_to_private_is_rejected(self) -> None:
        private_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(collection_common.socket, "getaddrinfo", return_value=private_answer):
            with self.assertRaises(ValueError):
                collection_common.require_public_network_url("https://attacker.example/feed")

    def test_external_public_url_never_receives_environment_secret(self) -> None:
        captured = []

        def fake_open(request, timeout):
            captured.append(request)
            return FakeResponse(b'{"signals": []}', request.full_url)

        with patch.dict(os.environ, {"AUDIT_SECRET": "secret"}, clear=False), patch.object(
            external_signal_collect, "open_request", side_effect=fake_open
        ):
            external_signal_collect.load_payload(
                None, "https://public.example/feed", "AUDIT_SECRET", None, "public-feed", 24
            )
        self.assertNotIn("x-worldmonitor-key", self.header_names(captured[0]))

    def test_external_secret_requires_matching_https_origin(self) -> None:
        with patch.dict(os.environ, {"AUDIT_SECRET": "secret"}, clear=False):
            with self.assertRaises(ValueError):
                external_signal_collect.load_payload(
                    None,
                    "https://attacker.invalid/feed",
                    "AUDIT_SECRET",
                    "https://trusted.example",
                    "feed",
                    24,
                )
            with self.assertRaises(ValueError):
                external_signal_collect.load_payload(
                    None,
                    "http://trusted.example/feed",
                    "AUDIT_SECRET",
                    "http://trusted.example",
                    "feed",
                    24,
                )

    def test_cross_origin_redirect_strips_external_secret(self) -> None:
        request = external_signal_collect.Request(
            "https://trusted.example/feed", headers={"X-WorldMonitor-Key": "secret"}
        )
        redirected = external_signal_collect.CredentialSafeRedirectHandler().redirect_request(
            request, io.BytesIO(), 302, "Found", Message(), "https://other.example/feed"
        )
        self.assertIsNotNone(redirected)
        self.assertNotIn("x-worldmonitor-key", self.header_names(redirected))

    def test_trusted_external_redirect_content_is_rejected(self) -> None:
        def fake_open(request, timeout):
            return FakeResponse(b'{"signals": []}', "https://other.example/feed")

        with patch.dict(os.environ, {"AUDIT_SECRET": "secret"}, clear=False), patch.object(
            external_signal_collect, "open_request", side_effect=fake_open
        ):
            with self.assertRaises(ValueError):
                external_signal_collect.load_payload(
                    None,
                    "https://trusted.example/feed",
                    "AUDIT_SECRET",
                    "https://trusted.example",
                    "trusted-feed",
                    24,
                )

    def test_public_redirect_uses_final_provider_and_feed_size_is_bounded(self) -> None:
        def redirected(request, timeout):
            return FakeResponse(b'{"signals": []}', "https://final.example/feed")

        with patch.object(external_signal_collect, "open_request", side_effect=redirected):
            _, health = external_signal_collect.load_payload(
                None, "https://initial.example/feed", "", None, None, 24
            )
        self.assertEqual("final.example", health["provider"])
        self.assertEqual("https://final.example/feed", health["url"])

        def oversized(request, timeout):
            return FakeResponse(b"x" * (external_signal_collect.MAX_FEED_BYTES + 1), request.full_url)

        with patch.object(external_signal_collect, "open_request", side_effect=oversized):
            with self.assertRaises(ValueError):
                external_signal_collect.load_payload(
                    None, "https://public.example/feed", "", None, None, 24
                )

    def test_private_redirects_and_business_error_envelopes_are_rejected(self) -> None:
        with patch.object(
            external_signal_collect,
            "open_request",
            return_value=FakeResponse(b'{"signals": []}', "http://127.0.0.1/feed"),
        ):
            with self.assertRaises(ValueError):
                external_signal_collect.load_payload(
                    None, "https://public.example/feed", "", None, None, 24
                )

        with patch.object(
            external_signal_collect,
            "open_request",
            return_value=FakeResponse(b'{"error": "unauthorized"}', "https://public.example/feed"),
        ):
            payload, health = external_signal_collect.load_payload(
                None, "https://public.example/feed", "", None, None, 24
            )
        self.assertIsNone(payload)
        self.assertEqual("not_configured", health["status"])

        for payload in (b"Unauthorized", b'{"success": false, "error": "invalid api key"}'):
            content_type = "text/plain" if payload == b"Unauthorized" else "application/json"
            with self.subTest(payload=payload), patch.object(
                source_health,
                "open_request",
                return_value=FakeResponse(payload, "https://public.example/status", content_type=content_type),
            ):
                row = source_health.probe("fixture", "https://public.example/status", None, "monitoring", 24)
                self.assertEqual("not_configured", row["status"])

        with patch.object(
            source_health,
            "open_request",
            return_value=FakeResponse(b"{}", "http://[::1]/status"),
        ):
            row = source_health.probe("fixture", "https://public.example/status", None, "monitoring", 24)
        self.assertEqual("unavailable", row["status"])

    def test_firecrawl_monthly_credit_ledger_blocks_quota_and_records_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            usage = root / "firecrawl-usage.json"
            month = firecrawl_search.utc_month()
            usage.write_text(json.dumps({
                "version": 1,
                "month": month,
                "entries": [{"at": f"{month}-01T00:00:00+00:00", "credits": 1000, "request_id": "prior"}],
            }), encoding="utf-8")
            argv = ["firecrawl_search.py", "fixture", "--usage-file", str(usage)]
            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "secret"}, clear=False), patch.object(
                sys, "argv", argv
            ), patch.object(firecrawl_search, "open_request") as request_mock, patch("sys.stdout", new=io.StringIO()) as stdout:
                self.assertEqual(2, firecrawl_search.main())
            request_mock.assert_not_called()
            blocked = json.loads(stdout.getvalue())
            self.assertEqual("quota_exhausted", blocked["status"])
            self.assertEqual(0, blocked["usage"]["remaining_credits"])

            success = FakeResponse(
                b'{"success": true, "data": {"web": []}, "creditsUsed": 12, "id": "job-12"}',
                "https://api.firecrawl.dev/v2/search",
            )
            usage.unlink()
            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "secret"}, clear=False), patch.object(
                sys, "argv", argv
            ), patch.object(firecrawl_search, "open_request", return_value=success), patch("sys.stdout", new=io.StringIO()) as stdout:
                self.assertEqual(0, firecrawl_search.main())
            recorded = json.loads(stdout.getvalue())
            self.assertEqual(12, recorded["usage"]["used_credits"])
            self.assertEqual(988, recorded["usage"]["remaining_credits"])
            persisted = json.loads(usage.read_text(encoding="utf-8"))
            self.assertEqual(12, persisted["entries"][0]["credits"])
            self.assertEqual("job-12", persisted["entries"][0]["request_id"])

    def test_firecrawl_business_failure_and_https_downgrade_are_rejected(self) -> None:
        argv = ["firecrawl_search.py", "fixture"]
        response = FakeResponse(
            b'{"success": false, "error": "quota exceeded"}',
            "https://api.firecrawl.dev/v2/search",
        )
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "secret"}, clear=False), patch.object(
            firecrawl_search, "open_request", return_value=response
        ), patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(1, firecrawl_search.main())

        handler = collection_common.RestrictedRedirectHandler(("gov.cn",))
        request = collection_common.Request("https://agency.gov.cn/report")
        with self.assertRaises(HTTPError):
            handler.redirect_request(
                request,
                io.BytesIO(),
                302,
                "Found",
                Message(),
                "http://agency.gov.cn/report",
            )

    def test_trusted_private_firecrawl_works_end_to_end(self) -> None:
        argv = [
            "firecrawl_search.py",
            "fixture",
            "--base-url",
            "https://firecrawl.internal",
            "--trusted-origin",
            "https://firecrawl.internal",
        ]
        response = FakeResponse(
            b'{"success": true, "data": []}',
            "https://firecrawl.internal/v2/search",
        )
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "secret"}, clear=False), patch.object(
            firecrawl_search, "open_request", return_value=response
        ), patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(0, firecrawl_search.main())

    def test_source_health_does_not_send_key_without_trusted_origin(self) -> None:
        captured = []

        def fake_open(request, timeout):
            captured.append(request)
            return FakeResponse(b"{}", request.full_url)

        with patch.dict(os.environ, {"AUDIT_SECRET": "secret"}, clear=False), patch.object(
            source_health, "open_request", side_effect=fake_open
        ):
            source_health.probe("public", "https://public.example/status", "AUDIT_SECRET", "monitoring", 24)
        self.assertNotIn("x-worldmonitor-key", self.header_names(captured[0]))

    def test_trusted_health_and_firecrawl_reject_cross_origin_response(self) -> None:
        def redirected(request, timeout):
            return FakeResponse(b"{}", "https://other.example/result")

        with patch.dict(os.environ, {"AUDIT_SECRET": "secret"}, clear=False), patch.object(
            source_health, "open_request", side_effect=redirected
        ):
            row = source_health.probe(
                "trusted",
                "https://trusted.example/status",
                "AUDIT_SECRET",
                "monitoring",
                24,
                "https://trusted.example",
            )
        self.assertEqual("unavailable", row["status"])

        argv = ["firecrawl_search.py", "fixture"]
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "secret"}, clear=False), patch.object(
            firecrawl_search, "open_request", side_effect=redirected
        ), patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(1, firecrawl_search.main())

    def test_firecrawl_rejects_http_and_unapproved_custom_origins(self) -> None:
        with self.assertRaises(ValueError):
            firecrawl_search.make_search_request("http://api.firecrawl.dev", None, "secret", {})
        with self.assertRaises(ValueError):
            firecrawl_search.make_search_request("https://custom.example", None, "secret", {})
        request = firecrawl_search.make_search_request(
            "https://custom.example", "https://custom.example", "secret", {}
        )
        self.assertIn("authorization", self.header_names(request))

    def test_freshness_and_provider_are_not_fabricated(self) -> None:
        self.assertEqual(
            "stale",
            external_signal_collect.signal_freshness(
                "2000-01-01", "2026-07-24T00:00:00+00:00", 24
            ),
        )
        self.assertEqual(
            "unknown",
            external_signal_collect.signal_freshness("not-a-date", "2026-07-24T00:00:00+00:00", 24),
        )
        health = {
            "status": "available",
            "provider": "custom.example",
            "observed_at": "2026-07-24T00:00:00+00:00",
            "freshness_budget_hours": 24,
        }
        result = external_signal_collect.normalize(
            {"signals": [{"id": "1", "title": "Old event", "as_of": "2000-01-01"}]},
            health,
            "https://custom.example/feed",
        )
        self.assertEqual("custom.example", result["external_signals"][0]["provider"])
        self.assertEqual("stale", result["external_signals"][0]["freshness"])
        self.assertNotIn("World Monitor", result["sources"][0]["title"])
        evidence = result["evidence"][0]
        source = next(item for item in result["sources"] if item["id"] == evidence["source_id"])
        self.assertIn(evidence["excerpt"], source["excerpt"])


class DiffMergeAndCollectorTests(unittest.TestCase):
    def test_snapshot_diff_covers_every_id_collection_and_competitors(self) -> None:
        old = load_json(SKILL_ROOT / "examples" / "deep-synthetic.json")
        new = copy.deepcopy(old)
        new["competitors"][0]["threat_level"] = "high"
        result = snapshot_diff.compare(old, new)
        self.assertTrue(set(snapshot_diff.ID_COLLECTIONS).issubset(result["collections"]))
        self.assertEqual(["threat_level"], result["collections"]["competitors"]["changed"][0]["changed_fields"])

    def test_snapshot_treats_evidence_time_as_material_and_rejects_duplicate_ids(self) -> None:
        old = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        new = copy.deepcopy(old)
        new["evidence"][0]["observed_at"] = "2099-01-01T00:00:00Z"
        result = snapshot_diff.compare(old, new)
        self.assertEqual(["observed_at"], result["collections"]["evidence"]["changed"][0]["changed_fields"])
        duplicate = copy.deepcopy(old)
        duplicate["evidence"].append(copy.deepcopy(duplicate["evidence"][0]))
        with self.assertRaises(ValueError):
            snapshot_diff.compare(old, duplicate)

    def test_snapshot_rejects_invalid_documents_and_separates_generated_at(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_diff.compare({}, {})
        old = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")
        new = copy.deepcopy(old)
        new["meta"]["generated_at"] = "2026-07-25T00:00:00+08:00"
        result = snapshot_diff.compare(old, new)
        self.assertEqual([], result["meta_changed_fields"])
        self.assertEqual(["generated_at"], result["meta_metadata_only_changed_fields"])

        extended = copy.deepcopy(new)
        extended["extension_state"] = {"status": "changed"}
        with self.assertRaises(ValueError):
            snapshot_diff.compare(new, extended)

    def test_snapshot_tracks_decision_audit_as_a_known_top_level_object(self) -> None:
        old = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
        new = copy.deepcopy(old)
        new["decision_audit"]["summary"] += " Updated."
        result = snapshot_diff.compare(old, new)
        self.assertTrue(result["top_level_changed"]["decision_audit"])
        self.assertNotIn("decision_audit", result["extension_top_level_changed"])

    def test_merge_contract_covers_all_schema_arrays_and_analysis_singletons(self) -> None:
        schema = load_json(SKILL_ROOT / "research.schema.json")
        schema_arrays = {
            name for name, definition in schema["properties"].items()
            if definition.get("type") == "array"
        }
        self.assertEqual(
            schema_arrays,
            set(merge_fragment.COLLECTION_KEYS) | merge_fragment.STRING_COLLECTIONS,
        )
        self.assertEqual(
            {
                "identity_resolution", "investment_context", "investment_conclusion",
                "income_analysis", "decision_audit",
            },
            merge_fragment.SINGLETONS,
        )

    def test_merge_supports_previously_omitted_investment_collection_and_singleton(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = load_json(SKILL_ROOT / "examples" / "investment-synthetic.json")
            fragment_payload = {
                "investment_theses": source.pop("investment_theses"),
                "decision_audit": source.pop("decision_audit"),
            }
            research = root / "research.json"
            fragment = root / "fragment.json"
            merged = root / "merged.json"
            research.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            fragment.write_text(json.dumps(fragment_payload, ensure_ascii=False), encoding="utf-8")
            argv = ["merge_fragment.py", str(research), str(fragment), "--out", str(merged)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, merge_fragment.main())
            result = load_json(merged)
            self.assertEqual(3, len(result["investment_theses"]))
            self.assertEqual("blocked", result["decision_audit"]["overall_status"])

    def test_merge_rejects_unknown_collection_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            fragment = temp_path / "fragment.json"
            fragment.write_text('{"external_signal": []}', encoding="utf-8")
            output = temp_path / "out.json"
            argv = [
                "merge_fragment.py",
                str(SKILL_ROOT / "examples" / "manufacturing-minimal.json"),
                str(fragment),
                "--out",
                str(output),
            ]
            with patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                merge_fragment.main()
            self.assertFalse(output.exists())

    def test_merge_rejects_duplicate_fragment_ids_even_with_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            item = load_json(SKILL_ROOT / "examples" / "manufacturing-minimal.json")["external_signals"][0]
            fragment = temp_path / "fragment.json"
            fragment.write_text(
                json.dumps({"external_signals": [item, copy.deepcopy(item)]}, ensure_ascii=False),
                encoding="utf-8",
            )
            output = temp_path / "out.json"
            argv = [
                "merge_fragment.py",
                str(SKILL_ROOT / "examples" / "manufacturing-minimal.json"),
                str(fragment),
                "--out",
                str(output),
                "--replace",
            ]
            with patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                merge_fragment.main()
            self.assertFalse(output.exists())

    def test_collection_boundaries_and_size_limit(self) -> None:
        self.assertTrue(procurement_collect.is_ccgp_host("https://search.ccgp.gov.cn/a"))
        self.assertFalse(procurement_collect.is_ccgp_host("https://ccgp.gov.cn.attacker.invalid/a"))
        self.assertFalse(government_pdf_collect.is_government_host("https://gov.cn.attacker.invalid/a.pdf"))
        with self.assertRaises(ValueError):
            collection_common.read_limited(io.BytesIO(b"x" * 11), 10)

    def test_procurement_all_failures_are_unavailable(self) -> None:
        failed = {"ok": False, "status": None, "url": "https://search.ccgp.gov.cn", "error": "offline", "content": b""}
        with tempfile.TemporaryDirectory() as temp, patch.object(
            procurement_collect, "fetch", return_value=failed
        ), patch.object(procurement_collect, "polite_pause"):
            argv = [
                "procurement_collect.py", "Fixture Co", "--max-queries", "1", "--pages", "1",
                "--delay", "0", "--out-dir", temp,
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, procurement_collect.main())
            manifest = json.loads((Path(temp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("unavailable", manifest["status"])

    def test_procurement_empty_and_candidate_free_pages_are_not_captured(self) -> None:
        cases = (
            (b"   ", "empty"),
            (b"<html><body>Search completed with no listed notices.</body></html>", "partial"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp, patch.object(
                procurement_collect,
                "fetch",
                return_value={
                    "ok": True,
                    "status": 200,
                    "url": "https://search.ccgp.gov.cn/result",
                    "content_type": "text/html; charset=utf-8",
                    "content": payload,
                },
            ), patch.object(procurement_collect, "polite_pause"):
                argv = [
                    "procurement_collect.py", "Fixture Co", "--max-queries", "1", "--pages", "1",
                    "--delay", "0", "--out-dir", temp,
                ]
                with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                    self.assertEqual(0, procurement_collect.main())
                manifest = json.loads((Path(temp) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(expected, manifest["status"])
                self.assertNotEqual("captured", manifest["records"][0]["result"])

    def test_source_health_rejects_login_html_and_downgrades_normal_html(self) -> None:
        cases = (
            (b'<html><form><input type="password"></form></html>', "not_configured"),
            (b"<html><body>Service landing page</body></html>", "partial"),
            (b"captcha", "not_configured"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), patch.object(
                source_health,
                "open_request",
                return_value=FakeResponse(
                    payload,
                    content_type="text/plain" if payload == b"captcha" else "text/html",
                ),
            ):
                row = source_health.probe(
                    "fixture", "https://public.example/status", None, "monitoring", 24
                )
                self.assertEqual(expected, row["status"])
                self.assertIsNone(row["last_success_at"])

    def test_government_pdf_failure_and_false_pdf(self) -> None:
        failed = {"ok": False, "status": None, "url": "https://agency.gov.cn/a.pdf", "error": "offline", "content": b""}
        with tempfile.TemporaryDirectory() as temp, patch.object(
            government_pdf_collect, "fetch", return_value=failed
        ), patch.object(government_pdf_collect, "searx_search", return_value={"ok": False, "results": []}), patch.object(
            government_pdf_collect, "polite_pause"
        ):
            argv = [
                "government_pdf_collect.py", "Fixture Co", "--url", "https://agency.gov.cn/a.pdf",
                "--delay", "0", "--out-dir", temp,
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, government_pdf_collect.main())
            manifest = json.loads((Path(temp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("capture_failed", manifest["status"])

        html_response = {
            "ok": True,
            "status": 200,
            "url": "https://agency.gov.cn/a.pdf",
            "content_type": "application/pdf",
            "content": b"<html><body>not a PDF</body></html>",
        }
        with tempfile.TemporaryDirectory() as temp, patch.object(
            government_pdf_collect, "fetch", return_value=html_response
        ), patch.object(government_pdf_collect, "searx_search", return_value={"ok": False, "results": []}), patch.object(
            government_pdf_collect, "polite_pause"
        ):
            argv = [
                "government_pdf_collect.py", "Fixture Co", "--url", "https://agency.gov.cn/a.pdf",
                "--no-follow-pages", "--delay", "0", "--out-dir", temp,
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, government_pdf_collect.main())
            manifest = json.loads((Path(temp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("page_captured", manifest["captures"][0]["result"])
            self.assertNotIn("pdf", manifest["captures"][0].get("artifact", {}).get("path", "").lower())


class UtilityWorkflowTests(unittest.TestCase):
    def test_source_discovery_finds_declared_feed_and_preserves_provenance(self) -> None:
        html = b'''<html><head>
        <link rel="alternate" type="application/rss+xml" title="News" href="/news.xml">
        </head></html>'''

        with patch.object(
            source_discovery,
            "fetch_url",
            return_value={
                "ok": True,
                "status": 200,
                "final_url": "https://example.com/",
                "content_type": "text/html",
                "headers": {"ETag": "abc", "Last-Modified": "Tue, 28 Jul 2026 00:00:00 GMT"},
                "content": html,
            },
        ):
            result = source_discovery.discover_site_feeds("https://example.com/")

        self.assertEqual("available", result["source_health"][0]["status"])
        self.assertEqual("https://example.com/news.xml", result["candidates"][0]["url"])
        self.assertEqual("html_link", result["candidates"][0]["discovery_method"])
        self.assertEqual("abc", result["transport"]["etag"])
        self.assertNotIn("etag", result["source_health"][0])

    def test_source_discovery_rejects_cross_origin_feed_and_marks_partial(self) -> None:
        html = b'''<html><head>
        <link rel="alternate" type="application/atom+xml" href="https://other.example/feed.xml">
        </head></html>'''
        with patch.object(
            source_discovery,
            "fetch_url",
            return_value={
                "ok": True,
                "status": 200,
                "final_url": "https://example.com/",
                "content_type": "text/html",
                "headers": {},
                "content": html,
            },
        ):
            result = source_discovery.discover_site_feeds("https://example.com/")

        self.assertEqual([], result["candidates"])
        self.assertEqual("partial", result["source_health"][0]["status"])
        self.assertIn("outside", result["source_health"][0]["notes"])

    def test_sec_submission_discovery_uses_accession_as_incremental_id(self) -> None:
        payload = {
            "name": "Example Corp",
            "filings": {"recent": {
                "accessionNumber": ["0000123456-26-000001"],
                "form": ["10-K"],
                "filingDate": ["2026-07-27"],
                "primaryDocument": ["annual.htm"],
            }},
        }
        with patch.object(
            source_discovery,
            "sec_fetch_url",
            return_value={
                "ok": True,
                "status": 200,
                "final_url": "https://data.sec.gov/submissions/CIK0000123456.json",
                "content_type": "application/json",
                "headers": {"ETag": "sec-etag"},
                "content": json.dumps(payload).encode("utf-8"),
            },
        ):
            result = source_discovery.discover_sec_filings("123456", limit=1)

        self.assertEqual("available", result["source_health"][0]["status"])
        self.assertEqual("0000123456-26-000001", result["candidates"][0]["external_id"])
        self.assertTrue(result["candidates"][0]["url"].endswith("/annual.htm"))

    def test_sec_ticker_resolution_uses_official_exchange_mapping_before_discovery(self) -> None:
        mapping = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]}
        with patch.object(source_discovery, "sec_fetch_url", return_value={
            "ok": True, "status": 200, "final_url": source_discovery.SEC_TICKERS_EXCHANGE_URL,
            "content_type": "application/json", "headers": {}, "content": json.dumps(mapping).encode("utf-8"),
        }):
            resolved = source_discovery.resolve_sec_ticker("aapl")
        self.assertEqual("0000320193", resolved["cik"])
        self.assertEqual("AAPL", resolved["ticker"])
        self.assertEqual("Nasdaq", resolved["exchange"])

    def test_hkex_discovery_resolves_stock_id_and_preserves_news_id(self) -> None:
        stocks = [{"i": 190371, "c": "01810", "n": "EXAMPLE-W", "s": 17534}]
        result_payload = [{
            "NEWS_ID": "11503798",
            "FILE_LINK": "/listedco/listconews/sehk/2025/0131/2025013100010.pdf",
            "TITLE": "MONTHLY RETURN",
            "DATE_TIME": "31/01/2025 16:30",
        }]
        with patch.object(
            source_discovery,
            "fetch_url",
            side_effect=[
                {"ok": True, "status": 200, "final_url": source_discovery.HKEX_STOCKS_URL, "headers": {}, "content": json.dumps(stocks).encode("utf-8")},
                {"ok": True, "status": 200, "final_url": source_discovery.HKEX_SEARCH_URL, "headers": {}, "content": json.dumps({"result": json.dumps(result_payload), "recordCnt": 1}).encode("utf-8")},
            ],
        ):
            result = source_discovery.discover_hkex_filings("1810", "20250101", "20250131", limit=5)

        self.assertEqual("available", result["source_health"][0]["status"])
        self.assertEqual("11503798", result["candidates"][0]["external_id"])
        self.assertEqual("official_exchange_search", result["candidates"][0]["discovery_method"])
        self.assertTrue(result["candidates"][0]["url"].startswith("https://www1.hkexnews.hk/"))

    def test_cninfo_discovery_uses_announcement_id_and_official_pdf_url(self) -> None:
        payload = {"totalAnnouncement": 1, "announcements": [{
            "secCode": "000001", "secName": "平安银行", "orgId": "gssz0000001",
            "announcementId": "1225406051", "announcementTitle": "董事会决议公告",
            "announcementTime": 1783008000000, "adjunctUrl": "finalpage/2026-07-03/1225406051.PDF",
        }]}
        with patch.object(
            source_discovery,
            "post_form_url",
            return_value={"ok": True, "status": 200, "final_url": source_discovery.CNINFO_QUERY_URL, "headers": {}, "content": json.dumps(payload).encode("utf-8")},
        ):
            result = source_discovery.discover_cninfo_announcements("000001", "gssz0000001", "20260701", "20260729", limit=5)

        self.assertEqual("available", result["source_health"][0]["status"])
        self.assertEqual("1225406051", result["candidates"][0]["external_id"])
        self.assertEqual("2026-07-03T00:00:00+08:00", result["candidates"][0]["published_at"])
        self.assertEqual("official_disclosure_query", result["candidates"][0]["discovery_method"])
        self.assertEqual("https://static.cninfo.com.cn/finalpage/2026-07-03/1225406051.PDF", result["candidates"][0]["url"])

    def test_source_intake_captures_candidate_as_discovery_only_without_polluting_sources(self) -> None:
        payload = {
            "generated_at": "2026-07-29T00:00:00+00:00",
            "candidates": [{
                "url": "https://example.test/filing.pdf", "title": "Example filing",
                "discovery_method": "official_exchange_search", "source_url": "https://example.test/search",
                "media_type": "application/pdf", "external_id": "n-1", "published_at": "2026-07-28",
                "verification": "discovery_only",
            }],
            "source_health": [{
                "id": "sh-fixture", "source_group": "fixture", "provider": "fixture", "layer": "discovery",
                "status": "available", "observed_at": "2026-07-29T00:00:00+00:00", "last_success_at": "2026-07-29T00:00:00+00:00",
                "freshness_budget_hours": 24, "coverage": ["https://example.test/search"], "missing_coverage": [], "fallback_used": False, "notes": "one item", "source_ids": [],
            }],
            "transport": {"etag": "x", "last_modified": None},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            discovery = root / "discovery.json"
            out_dir = root / "raw" / "official-disclosures"
            discovery.write_text(json.dumps(payload), encoding="utf-8")
            argv = ["source_intake.py", str(discovery), "--out-dir", str(out_dir), "--max-items", "1"]
            with patch.object(sys, "argv", argv), patch.object(source_intake, "fetch", return_value={
                "ok": True, "status": 200, "url": "https://example.test/filing.pdf", "content_type": "application/pdf", "content": b"%PDF-fixture",
            }), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, source_intake.main())
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("captured", manifest["status"])
            self.assertEqual("pdf_captured", manifest["captures"][0]["result"])
            self.assertEqual("discovery_only", manifest["captures"][0]["verification"])
            self.assertNotIn("sources", manifest)
            self.assertEqual([], manifest["source_health"][0]["source_ids"])

    def test_source_intake_rejects_candidate_outside_declared_source_host(self) -> None:
        payload = {
            "generated_at": "2026-07-29T00:00:00+00:00",
            "candidates": [{
                "url": "https://attacker.test/filing.pdf", "title": "Bad filing",
                "discovery_method": "official_exchange_search", "source_url": "https://example.test/search",
                "media_type": "application/pdf", "external_id": "n-2", "published_at": None, "verification": "discovery_only",
            }],
            "source_health": [], "transport": {},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            discovery = root / "discovery.json"
            out_dir = root / "raw" / "official-disclosures"
            discovery.write_text(json.dumps(payload), encoding="utf-8")
            argv = ["source_intake.py", str(discovery), "--out-dir", str(out_dir)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, source_intake.main())
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("partial", manifest["status"])
            self.assertEqual("rejected_host_boundary", manifest["captures"][0]["result"])

    def test_source_intake_allows_known_sec_archive_split_without_general_cross_origin_bypass(self) -> None:
        candidate = {
            "url": "https://www.sec.gov/Archives/edgar/data/1/example.htm",
            "source_url": "https://data.sec.gov/submissions/CIK0000000001.json",
            "verification": "discovery_only",
        }
        self.assertEqual(("www.sec.gov",), source_intake.allowed_document_hosts(candidate))
        self.assertIn("research-contact", source_intake.document_headers(candidate)["User-Agent"])
        unknown = {**candidate, "url": "https://attacker.test/example.htm"}
        self.assertEqual((), source_intake.allowed_document_hosts(unknown))
        self.assertEqual({}, source_intake.document_headers(unknown))

    def test_collection_fetch_rejects_non_string_custom_headers(self) -> None:
        result = collection_common.fetch(
            "https://public.example/", allowed_host_suffixes=("example",), headers={"X-Test": 1}
        )
        self.assertFalse(result["ok"])
        self.assertIn("headers must be", result["error"])

    def test_procurement_challenge_uses_dynamic_fallback_before_manual_required(self) -> None:
        challenge_html = "<html>访问过于频繁</html>".encode("utf-8")
        dynamic_html = "<html><a href='/cggg/notice.html'>Example procurement</a></html>"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv = ["procurement_collect.py", "Example Holdings", "--max-queries", "1", "--delay", "0", "--out-dir", str(root)]
            with patch.object(sys, "argv", argv), patch.object(procurement_collect, "fetch", return_value={
                "ok": True, "status": 200, "url": "https://search.ccgp.gov.cn/bxsearch", "content_type": "text/html", "content": challenge_html,
            }), patch.object(procurement_collect, "browser_capture_url", return_value={
                "status": "captured", "captures": [{"html_artifact": {"path": str(root / "dynamic.html")}}],
            }), patch("sys.stdout", new=io.StringIO()):
                (root / "dynamic.html").write_text(dynamic_html, encoding="utf-8")
                self.assertEqual(0, procurement_collect.main())
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("captured", manifest["status"])
            self.assertEqual(1, manifest["records"][0]["candidate_count"])

    def test_external_discovery_normalizes_archive_and_news_metadata_without_bodies(self) -> None:
        rows = [
            {"urlkey": "com,example)/a", "timestamp": "20260701010203", "url": "https://example.com/a", "status": "200", "mime": "text/html", "digest": "abc", "length": "123"},
            {"urlkey": "com,example)/b", "timestamp": "20260702010203", "original": "https://example.com/b", "status": "404", "mime": "text/html", "digest": "def", "length": "456"},
        ]
        candidates = external_discovery.common_crawl_candidates(rows, "https://example.com/*")
        self.assertEqual(1, len(candidates))
        self.assertEqual("20260701010203", candidates[0]["external_id"])
        self.assertEqual("archive_url_index", candidates[0]["discovery_method"])
        self.assertEqual("discovery_only", candidates[0]["verification"])

    def test_vertical_plan_expands_company_queries_with_aliases_without_list_literals(self) -> None:
        values = {"company": "Example Holdings", "brand": "Example", "alias": ["Example Subsidiary"], "founder": "", "domain": "example.com", "product": "Example Device", "address": ""}
        queries = vertical_plan.route_queries({"queries": ['"{company}" 客户']}, values)
        self.assertEqual(['"Example Holdings" 客户', '"Example Subsidiary" 客户'], queries)

    def test_browser_capture_rejects_stealth_mode_and_unapproved_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "capture.json"
            argv = [
                "browser_capture.py", "https://example.test/page", "--mode", "stealthy",
                "--out", str(output),
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(2, browser_capture.main())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("manual_required", payload["status"])
            self.assertIn("not permitted", payload["reason"])

    def test_paused_monitor_is_never_evaluated_or_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.json"
            observations = root / "observations.json"
            out = root / "events.json"
            plan.write_text(json.dumps({"monitoring_plan": [{
                "id": "mon-paused",
                "indicator": "orders",
                "status": "paused",
                "evaluation": {"observation_key": "orders", "operator": "gt", "threshold": 10},
                "action_if_triggered": "act",
            }]}), encoding="utf-8")
            observations.write_text(json.dumps({"orders": 20}), encoding="utf-8")
            argv = ["monitor_evaluate.py", str(plan), str(observations), "--out", str(out)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, monitor_evaluate.main())
            event = json.loads(out.read_text(encoding="utf-8"))["events"][0]
            self.assertEqual("skipped", event["status"])
            self.assertIsNone(event["triggered"])

    def test_scenario_rejects_unknown_direction_and_nonfinite_results(self) -> None:
        with self.assertRaises(ValueError):
            scenario_calculate.calc({
                "metric": "revenue", "baseline": 100,
                "shock": {"lower": -0.1, "base": 0, "upper": 0.1},
                "direction": "sideways",
            })
        with self.assertRaises(ValueError):
            scenario_calculate.calc({
                "metric": "revenue", "baseline": 1e308,
                "shock": {"lower": 10, "base": 10, "upper": 10},
                "direction": "relative",
            })
        with self.assertRaises(ValueError):
            scenario_calculate.calc({
                "metric": "revenue", "baseline": "100",
                "shock": {"lower": -0.1, "base": 0, "upper": 0.1},
                "direction": "relative",
            })

    def test_scenario_fragment_can_merge_and_backtest_rejects_nan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            research = SKILL_ROOT / "examples" / "deep-synthetic.json"
            scenario_input = root / "scenario-input.json"
            fragment = root / "fragment.json"
            merged = root / "merged.json"
            scenario_input.write_text(json.dumps({
                "scenario_id": "scn-test",
                "evidence_ids": ["evd-company"],
                "assumptions": [{
                    "metric": "revenue",
                    "baseline": 100,
                    "shock": {"lower": -0.2, "base": -0.1, "upper": 0.1},
                    "unit": "index",
                    "direction": "relative",
                }],
            }), encoding="utf-8")
            argv = ["scenario_calculate.py", str(scenario_input), "--out", str(fragment)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, scenario_calculate.main())
            self.assertEqual(
                {"scenario_results", "limitations"},
                set(json.loads(fragment.read_text(encoding="utf-8"))),
            )
            argv = ["merge_fragment.py", str(research), str(fragment), "--out", str(merged)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, merge_fragment.main())
            self.assertTrue(merged.is_file())

            actuals = root / "actuals.json"
            backtest = root / "backtest.json"
            actuals.write_text('{"sres-test-001": "NaN"}', encoding="utf-8")
            argv = ["scenario_backtest.py", str(fragment), str(actuals), "--out", str(backtest)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, scenario_backtest.main())
            score = json.loads(backtest.read_text(encoding="utf-8"))["scores"][0]
            self.assertEqual("invalid_actual", score["status"])

            invalid_fragment = root / "invalid-fragment.json"
            invalid_fragment.write_text(json.dumps({"scenario_results": [{
                **json.loads(fragment.read_text(encoding="utf-8"))["scenario_results"][0],
                "lower_bound": 200,
                "upper_bound": 100,
            }]}), encoding="utf-8")
            argv = ["scenario_backtest.py", str(invalid_fragment), str(actuals), "--out", str(backtest)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(0, scenario_backtest.main())
            score = json.loads(backtest.read_text(encoding="utf-8"))["scores"][0]
            self.assertEqual("invalid_actual", score["status"])


def run_suite(verbosity: int = 2, stream=None) -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=verbosity, stream=stream).run(suite)
    return result.wasSuccessful()


def main() -> int:
    return 0 if run_suite() else 1


if __name__ == "__main__":
    raise SystemExit(main())
