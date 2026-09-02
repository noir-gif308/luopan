#!/usr/bin/env python3
"""Render Markdown and HTML reports from validated Luopan research JSON."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit

from validate_research import load_json, schema_validate, semantic_validate


SAFE_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th", "thead",
    "tr", "ul",
}
VOID_HTML_TAGS = {"br", "hr"}
DROP_CONTENT_TAGS = {"embed", "iframe", "math", "object", "script", "style", "svg", "template"}
URL_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]+")


def safe_report_url(value: str) -> str | None:
    candidate = URL_CONTROL_OR_SPACE.sub("", html.unescape(value).strip())
    if re.fullmatch(r"#[A-Za-z0-9_.:-]*", candidate):
        return candidate
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return candidate


class ReportHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.blocked_tags:
            if tag in DROP_CONTENT_TAGS:
                self.blocked_tags.append(tag)
            return
        if tag in DROP_CONTENT_TAGS:
            self.blocked_tags.append(tag)
            return
        if tag not in SAFE_HTML_TAGS:
            return
        rendered_attrs = []
        if tag == "a":
            for name, value in attrs:
                name = name.lower()
                if name == "href" and value is not None:
                    safe_url = safe_report_url(value)
                    if safe_url is not None:
                        rendered_attrs.append(f'href="{html.escape(safe_url, quote=True)}"')
                elif name == "title" and value is not None:
                    rendered_attrs.append(f'title="{html.escape(value, quote=True)}"')
            rendered_attrs.append('rel="noopener noreferrer"')
        suffix = f" {' '.join(rendered_attrs)}" if rendered_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.blocked_tags or tag in DROP_CONTENT_TAGS or tag not in SAFE_HTML_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.blocked_tags:
            if tag == self.blocked_tags[-1]:
                self.blocked_tags.pop()
            return
        if tag in SAFE_HTML_TAGS:
            if tag not in VOID_HTML_TAGS:
                self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_tags:
            self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self.blocked_tags:
            self.parts.append(html.escape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if not self.blocked_tags:
            self.parts.append(html.escape(f"&#{name};"))

    def get_html(self) -> str:
        return "".join(self.parts)


def sanitize_report_html(value: str) -> str:
    sanitizer = ReportHTMLSanitizer()
    sanitizer.feed(value)
    sanitizer.close()
    return sanitizer.get_html()


def escape_markdown_text(value: str) -> str:
    flattened = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    escaped = flattened.replace("\\", "\\\\").replace("&", "&amp;")
    for character in ("<", ">", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}" if character in "[]" else html.escape(character))
    return escaped


def markdown_report_url(value: str) -> str:
    safe_url = safe_report_url(value)
    if safe_url is None:
        return ""
    return quote(safe_url, safe=":/?#@!$&'*+,;=%")


def markdown_safe_data(value: object, field: str | None = None) -> object:
    if isinstance(value, dict):
        return {key: markdown_safe_data(nested, key) for key, nested in value.items()}
    if isinstance(value, list):
        return [markdown_safe_data(nested, field) for nested in value]
    if isinstance(value, str):
        if field == "url":
            return markdown_report_url(value)
        return escape_markdown_text(value)
    return value


def validate_before_render(path: Path) -> dict:
    data = load_json(path)
    schema_path = Path(__file__).resolve().parent.parent / "research.schema.json"
    schema = load_json(schema_path)
    schema_messages = schema_validate(data, schema)
    errors = [item for item in schema_messages if not item.startswith("WARNING:")]
    warnings = [item for item in schema_messages if item.startswith("WARNING:")]
    semantic_errors, semantic_warnings = semantic_validate(data)
    errors.extend(semantic_errors)
    warnings.extend(semantic_warnings)
    for warning in warnings:
        print(f"WARNING: {warning.removeprefix('WARNING: ')}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise ValueError(f"research validation failed with {len(errors)} error(s)")
    return data


def evidence_labels(ids: list[str], index: dict[str, dict]) -> str:
    labels = []
    for item_id in ids:
        item = index.get(item_id, {})
        source = index.get(item.get("source_id"), {})
        if source:
            source_title = source.get("title") or source.get("publisher") or item.get("source_id")
            locator = item.get("locator") or item_id
            label = f"{source_title} · {locator}"
            url = source.get("url") or ""
            labels.append(f"[{label}]({url})" if url else label)
        else:
            labels.append(item.get("title") or item.get("name") or item.get("signal") or item.get("locator") or item_id)
    return "、".join(labels)


def md_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def evidence_audit(ids: list[str], index: dict[str, dict]) -> list[str]:
    rows = []
    for item_id in ids:
        item = index.get(item_id, {})
        label = item.get("title") or item.get("name") or item.get("locator") or item_id
        excerpt = item.get("excerpt")
        if excerpt:
            locator = f"（{item['locator']}）" if item.get("locator") else ""
            stance = f"[{item['stance']}] " if item.get("stance") else ""
            rows.append(f"- **{label}**{locator}：{stance}{excerpt}")
        elif "value" in item:
            rows.append(f"- **{label}**：{format_metric_value(item['value'])} {item.get('unit', '')}（{item.get('period', '周期未知')}；{item.get('scope', '口径未知')}）")
        elif item.get("signal"):
            rows.append(f"- **{label}**：{item['signal']}")
        else:
            rows.append(f"- **{label}**：派生证据 `{item_id}`")
    return rows


def format_metric_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def format_percent(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.1%}"
    return "—"


def render_markdown(data: dict) -> str:
    data = markdown_safe_data(data)
    assert isinstance(data, dict)
    index = {item["id"]: item for key in (
        "sources", "evidence", "entities", "products", "supply_chain_nodes", "metrics",
        "source_health", "external_signals", "exposure_links", "monitoring_plan", "scenario_results",
        "experience_signals", "rd_signals", "product_markets", "customer_segments",
        "competitors", "business_model_links", "organization_signals", "observations",
        "narrative_risks", "intelligence_items", "investment_theses", "valuation_scenarios",
        "period_reviews", "management_commitments", "capital_allocation_events",
        "thesis_changes", "bottleneck_nodes", "scenarios", "claims", "opportunities"
    ) for item in data.get(key, [])}
    meta = data["meta"]
    scope = data["scope"]
    lines = [
        f"# {meta['title']}",
        "",
        f"> 深度：{meta['mode']} | 研究目的：{meta.get('research_purpose', 'intelligence')} | 专项镜头：{' / '.join(meta.get('analysis_lenses', [])) or '无'} | 信息环境：{meta.get('information_regime', '未声明')} | 完成状态：{meta.get('research_status', '未声明')} | 验证：{meta['verification_mode']} | 生成：{meta['generated_at']}",
        "",
        "## 研究边界",
        "",
        f"- 对象：{scope['subject']}",
        f"- 地理：{scope['geography']}",
        f"- 时间：{scope['timeframe']}",
        f"- 决策问题：{scope['decision_question']}",
        "",
    ]

    intake = data.get("intake")
    if intake:
        lines.extend(["## 调研前提", "", f"- 交互模式：{intake.get('interaction_mode', 'unknown')}"])
        for item in intake.get("assumptions", []):
            lines.append(f"- 默认假设：{item}")
        for item in intake.get("unresolved_questions", []):
            lines.append(f"- 未解决问题：{item}")
        lines.append("")

    lines.extend(["## 核心判断", ""])

    if data.get("identity_resolution"):
        identity = data["identity_resolution"]
        identifier_text = "；".join(
            f"{item['identifier_type']}={item['value']}"
            for item in identity.get("identifiers", [])
        ) or "无"
        lines.extend([
            "## 主体消歧",
            "",
            f"- 法定名称：{identity['legal_name']}",
            f"- 别名/品牌：{'；'.join(identity.get('aliases', [])) or '无'}",
            f"- 解析状态：{identity['resolution_status']}",
            f"- 标识符：{identifier_text}",
        ])
        if identity.get("ambiguities"):
            lines.append(f"- 剩余歧义：{'；'.join(identity['ambiguities'])}")
        lines.append("")

    if data.get("footprint_coverage"):
        lines.extend(["## 垂直足迹覆盖", "", "| 维度 | 状态 | 当前发现 | 缺口/下一步 |", "|---|---|---|---|"])
        for row in data["footprint_coverage"]:
            gap = row.get("gap_reason") or row.get("next_action") or "—"
            lines.append(f"| {row['dimension']} | {row['status']} | {md_cell(row.get('finding') or '—')} | {md_cell(gap)} |")
        lines.append("")
    for claim in data.get("claims", []):
        lines.extend([
            f"### {claim['statement']}",
            "",
            f"- 类型：{claim['claim_type']} | 置信度：{claim['confidence']}",
            f"- 证据：{evidence_labels(claim['evidence_ids'], index)}",
            f"- 所以呢：{claim['implication']}",
        ])
        if claim.get("confidence_reason"):
            lines.append(f"- 置信度理由：{claim['confidence_reason']}")
        if claim.get("counter_search_status"):
            lines.append(f"- 反证搜索：{claim['counter_search_status']}")
        if claim.get("counter_evidence_ids"):
            lines.append(f"- 反方证据：{evidence_labels(claim['counter_evidence_ids'], index)}")
        if claim.get("falsifier"):
            lines.append(f"- 反证条件：{claim['falsifier']}")
        if claim.get("claim_components"):
            lines.extend(["", "子判断拆解：", ""])
            for component in claim["claim_components"]:
                unknown = f"；未知：{component['unknown']}" if component.get("unknown") else ""
                lines.append(f"- [{component['confidence']}] {component['statement']}（证据：{evidence_labels(component['evidence_ids'], index)}{unknown}）")
        lines.extend(["", "证据审计：", ""])
        lines.extend(evidence_audit(claim["evidence_ids"], index))
        if claim.get("counter_evidence_ids"):
            lines.extend(["", "反方证据审计：", ""])
            lines.extend(evidence_audit(claim["counter_evidence_ids"], index))
        lines.append("")

    if data.get("key_unknowns"):
        lines.extend(["## 最大未知项", ""])
        lines.extend(f"- {item}" for item in data["key_unknowns"])
        lines.append("")

    if data.get("entities"):
        lines.extend(["## 企业与权力", "", "| 企业 | 价值链位置 | 权力 | 证据覆盖 | 置信度 |", "|---|---|---|---:|---|"])
        for entity in data["entities"]:
            coverage = entity.get("evidence_coverage")
            coverage_text = "未知" if coverage is None else f"{coverage:.0%}"
            lines.append(f"| {md_cell(entity['name'])} | {md_cell(' / '.join(entity['value_chain_position']))} | {entity['power_tier']} | {coverage_text} | {entity['confidence']} |")
        lines.append("")

    if data.get("products"):
        lines.extend(["## 产品组合", "", "| 产品 | 企业 | 角色 | 客户任务 | 置信度 |", "|---|---|---|---|---|"])
        for product in data["products"]:
            entity = index.get(product["entity_id"], {}).get("name", product["entity_id"])
            roles = " / ".join([product["role"], *product.get("secondary_roles", [])])
            lines.append(f"| {md_cell(product['name'])} | {md_cell(entity)} | {roles} | {md_cell(product.get('customer_job', ''))} | {product['confidence']} |")
        lines.append("")
        profit_products = [
            item for item in data["products"]
            if "profit_engine" in {item.get("role"), *item.get("secondary_roles", [])}
        ]
        if profit_products:
            lines.extend(["### 利润产品口径审计", ""])
            for product in profit_products:
                lines.append(f"- **{product['name']}**：范围={product.get('economic_scope')}；利润口径={product.get('profit_measure')}；口径污染={product.get('scope_contamination')}。")
            lines.append("")

    if data.get("product_markets"):
        lines.extend(["## 产品—市场矩阵", "", "| 产品 | 市场 | 地理 | 份额/口径 | 价格带 | 生命周期 | 趋势 |", "|---|---|---|---|---|---|---|"])
        for market in data["product_markets"]:
            product = index.get(market["product_id"], {}).get("name", market["product_id"])
            share = "未知"
            if market.get("market_share") is not None:
                share = f"{format_metric_value(market['market_share'])}{market.get('share_unit') or ''} / {market.get('share_basis') or '未注明'} / {market.get('share_period') or '未注明'}"
            lines.append(f"| {md_cell(product)} | {md_cell(market['market_name'])} | {md_cell(market['geography'])} | {md_cell(share)} | {md_cell(market.get('price_band') or '未知')} | {market.get('lifecycle', 'unknown')} | {market.get('share_direction', 'unknown')} |")
        lines.append("")

    if data.get("customer_segments"):
        lines.extend(["## 客户群与购买决策", "", "| 客户群 | 要完成的任务 | 付费者 | 使用者 | 价格敏感度 | 购买驱动 | 流失驱动 |", "|---|---|---|---|---|---|---|"])
        for customer in data["customer_segments"]:
            lines.append(f"| {md_cell(customer['name'])} | {md_cell(customer['customer_job'])} | {md_cell(customer['payer'])} | {md_cell(customer['user'])} | {customer.get('price_sensitivity', 'unknown')} | {md_cell('；'.join(customer.get('purchase_drivers', [])))} | {md_cell('；'.join(customer.get('churn_drivers', [])))} |")
        lines.append("")

    if data.get("business_model_links"):
        lines.extend(["## 商业结构与飞轮", ""])
        for link in data["business_model_links"]:
            source = index.get(link["from_id"], {}).get("name", link["from_id"])
            target = index.get(link["to_id"], {}).get("name", link["to_id"])
            lines.append(f"- **{source} → {target}**（{link['link_type']}，置信度 {link['confidence']}）：{link['mechanism']}")
        lines.append("")

    if data.get("relationship_edges"):
        lines.extend(["## 企业关系与外部足迹", "", "| 起点 | 关系 | 终点 | 状态 | 置信度 |", "|---|---|---|---|---|"])
        for edge in data["relationship_edges"]:
            lines.append(f"| {md_cell(edge['from_label'])} | {edge['relationship_type']} | {md_cell(edge['to_label'])} | {edge['status']} | {edge['confidence']} |")
        lines.append("")

    if data.get("proxy_estimates"):
        lines.extend(["## 区间估算与反推", "", "> 以下为代理估算，不是企业披露事实。", ""])
        for estimate in data["proxy_estimates"]:
            lines.extend([
                f"### {estimate['name']}",
                "",
                f"- 区间：{format_metric_value(estimate['lower_bound'])}–{format_metric_value(estimate['upper_bound'])} {estimate['unit']}；基准：{format_metric_value(estimate['base_case'])}",
                f"- 周期：{estimate['period']} | 置信度：{estimate['confidence']}",
                f"- 公式：{estimate['formula']}",
                f"- 假设：{'；'.join(estimate['assumptions'])}",
                f"- 交叉检查：{'；'.join(estimate.get('cross_checks', [])) or '无'}",
                f"- 敏感项：{'；'.join(estimate.get('sensitivity', [])) or '无'}",
                "",
            ])

    if data.get("competitors"):
        lines.extend(["## 竞争与替代图谱", "", "| 竞争者/替代项 | 类型 | 威胁 | 目标客户 | 优势 | 弱点 |", "|---|---|---|---|---|---|"])
        for competitor in data["competitors"]:
            lines.append(f"| {md_cell(competitor['name'])} | {competitor['competition_type']} | {competitor['threat_level']} | {md_cell(competitor.get('target_customers', ''))} | {md_cell('；'.join(competitor.get('advantages', [])))} | {md_cell('；'.join(competitor.get('weaknesses', [])))} |")
        lines.append("")

    if data.get("metrics"):
        lines.extend(["## 关键指标", "", "| 指标 | 数值 | 周期 | 口径 | 类型 |", "|---|---:|---|---|---|"])
        for metric in data["metrics"]:
            value = f"{format_metric_value(metric['value'])} {metric['unit']}".strip()
            lines.append(f"| {md_cell(metric['name'])} | {md_cell(value)} | {md_cell(metric['period'])} | {md_cell(metric['scope'])} | {md_cell(metric['metric_type'])} |")
        lines.append("")

    if data.get("period_reviews"):
        lines.extend(["## 财报与经营变化", "", "> 本节比较同口径期间证据，不把措辞变化当经营变化。", ""])
        for review in data["period_reviews"]:
            lines.extend([
                f"### {review['current_period']} 对比 {review['comparison_period']}",
                "",
                f"- 截止：{review['as_of']} | 总体影响：{review['overall_effect']} | 置信度：{review['confidence']}",
                f"- 结论：{review['summary']}",
                "",
                "| 指标 | 当前期 | 对比期 | 解释 | 当前证据 | 对比证据 |",
                "|---|---:|---:|---|---|---|",
            ])
            for delta in review["metric_deltas"]:
                lines.append(
                    f"| {md_cell(delta['metric'])} | {format_metric_value(delta['current_value'])} {md_cell(delta['unit'])} | "
                    f"{format_metric_value(delta['comparison_value'])} {md_cell(delta['unit'])} | {md_cell(delta['interpretation'])} | "
                    f"{md_cell(evidence_labels(delta['current_evidence_ids'], index))} | "
                    f"{md_cell(evidence_labels(delta['comparison_evidence_ids'], index))} |"
                )
            if review.get("accounting_signals"):
                lines.extend(["", "会计与口径信号：", ""])
                for signal in review["accounting_signals"]:
                    lines.append(
                        f"- **{signal['status']}**：{signal['description']}；影响：{signal['impact']}"
                    )
            if review.get("commitment_ids"):
                labels = [index.get(item_id, {}).get("statement", item_id) for item_id in review["commitment_ids"]]
                lines.append(f"- 关联承诺：{'；'.join(labels)}")
            lines.append("")

    if data.get("supply_chain_nodes"):
        lines.extend(["## 产品上下游链群", "", "| 节点 | 环节 | 风险 | 原因 |", "|---|---|---|---|"])
        for node in data["supply_chain_nodes"]:
            lines.append(f"| {md_cell(node['name'])} | {md_cell(node['stage'])} | {md_cell(node['risk_level'])} | {md_cell(node.get('risk_reason', ''))} |")
        lines.append("")

    if data.get("bottleneck_nodes"):
        lines.extend([
            "## 供应链瓶颈判断",
            "",
            "> 供应紧张不自动等于企业获利；评级同时检查利润捕获与解除条件。",
            "",
            "| 节点 | 判断 | 集中度 | 扩产/月 | 替代 | 利用率 | 需求增速 | 验证/月 | 利润捕获 | 置信度 | 证据 |",
            "|---|---|---:|---:|---|---:|---:|---:|---|---|---|",
        ])
        for node in data["bottleneck_nodes"]:
            supply_name = index.get(node["supply_chain_node_id"], {}).get("name", node["supply_chain_node_id"])
            concentration = "未知" if node.get("supply_concentration") is None else format_percent(node["supply_concentration"])
            utilization = "未知" if node.get("capacity_utilization") is None else format_percent(node["capacity_utilization"])
            growth = "未知" if node.get("demand_growth") is None else format_percent(node["demand_growth"])
            expansion = "未知" if node.get("expansion_lead_time_months") is None else format_metric_value(node["expansion_lead_time_months"])
            qualification = "未知" if node.get("qualification_lead_time_months") is None else format_metric_value(node["qualification_lead_time_months"])
            lines.append(
                f"| {md_cell(supply_name)} | {node['bottleneck_status']} | {concentration} | {expansion} | "
                f"{node['substitution_difficulty']} | {utilization} | {growth} | {qualification} | "
                f"{node['profit_capture']} | {node['confidence']} | {md_cell(evidence_labels(node['evidence_ids'], index))} |"
            )
            lines.append(
                f"| 解除条件 |  |  |  |  |  |  |  | {md_cell('；'.join(node['relief_conditions']))} |  |  |"
            )
        lines.append("")

    if data.get("external_signals"):
        lines.extend(["## 外部环境信号", "", "> 外部事件不直接等于企业影响；必须结合下一节的企业暴露关系解释。", "", "| 领域 | 信号 | 地理/时间 | 方向 | 严重度 | 状态/新鲜度 | 原子证据 |", "|---|---|---|---|---|---|---|"])
        for signal in data["external_signals"]:
            lines.append(
                f"| {signal['domain']} | {md_cell(signal['signal'])} | {md_cell(signal['geography'])} / {signal['as_of']} | "
                f"{signal['direction']} | {signal['severity']} | {signal['status']} / {signal['freshness']} | {md_cell(evidence_labels(signal['evidence_ids'], index))} |"
            )
        lines.append("")

    if data.get("exposure_links"):
        lines.extend(["## 企业外部风险暴露与传导", ""])
        for link in data["exposure_links"]:
            entity = index.get(link["entity_id"], {}).get("name", link["entity_id"])
            signals = evidence_labels(link["external_signal_ids"], index)
            anchors = [index.get(item_id, {}).get("name", item_id) for item_id in [*link.get("product_ids", []), *link.get("supply_chain_node_ids", [])]]
            lines.extend([
                f"### {entity}：{link['exposure_type']} / 敏感度 {link['sensitivity']}",
                "",
                f"- 外部信号：{signals}",
                f"- 企业锚点：{'；'.join(anchors) or '未定位到具体产品/节点'}",
                f"- 传导机制：{link['mechanism']}",
                f"- 时间范围：{link['time_horizon']}",
                f"- 缓冲因素：{'；'.join(link.get('mitigants', [])) or '未发现'}",
                f"- 关键未知：{'；'.join(link.get('unknowns', [])) or '未声明'}",
                f"- 传导证据：{evidence_labels(link.get('evidence_ids', []), index)}",
                "",
            ])

    for key, title in (("experience_signals", "真实用户体验信号"), ("rd_signals", "研发转化信号")):
        if data.get(key):
            lines.extend([f"## {title}", ""])
            for signal in data[key]:
                scope_text = f"；样本：{signal['sample_scope']}" if signal.get("sample_scope") else ""
                lines.append(f"- {signal['signal']}（置信度：{signal['confidence']}{scope_text}）")
            lines.append("")

    if data.get("organization_signals"):
        lines.extend(["## 组织、人员与执行能力", ""])
        for signal in data["organization_signals"]:
            alternatives = "；其他解释：" + " / ".join(signal.get("alternative_explanations", [])) if signal.get("alternative_explanations") else ""
            lines.append(f"- **{signal['signal_type']} / {signal['direction']}**：{signal['description']}（{signal['period']}，置信度 {signal['confidence']}{alternatives}）")
        lines.append("")

    if data.get("management_commitments"):
        lines.extend(["## 管理层承诺兑现台账", "", "| 日期 | 承诺 | 目标日 | 状态 | 评价 | 置信度 | 原始证据 | 结果证据 |", "|---|---|---|---|---|---|---|---|"])
        for item in data["management_commitments"]:
            lines.append(
                f"| {item['made_at']} | {md_cell(item['statement'])} | {item.get('due_at') or '未明确'} | "
                f"{item['status']} | {md_cell(item['assessment'])} | {item['confidence']} | "
                f"{md_cell(evidence_labels(item['original_evidence_ids'], index))} | "
                f"{md_cell(evidence_labels(item['outcome_evidence_ids'], index)) or '无'} |"
            )
        lines.append("")

    if data.get("capital_allocation_events"):
        lines.extend(["## 资本配置行为", "", "| 日期 | 类型 | 金额 | 状态 | 原因 | 事后结果 | 评价 | 证据 |", "|---|---|---:|---|---|---|---|---|"])
        for event in data["capital_allocation_events"]:
            amount = "未知" if event.get("amount") is None else f"{format_metric_value(event['amount'])} {event.get('currency') or ''}".strip()
            lines.append(
                f"| {event['announced_at']} | {event['event_type']} | {md_cell(amount)} | {event['status']} | "
                f"{md_cell(event['rationale'])} | {md_cell(event['outcome'])} | {md_cell(event['assessment'])} | "
                f"{md_cell(evidence_labels(event['evidence_ids'], index))} |"
            )
        lines.append("")

    if data.get("observations"):
        lines.extend(["## 外部行为与领先指标", ""])
        for observation in data["observations"]:
            lines.extend([
                f"### {observation['description']}",
                "",
                f"- 类型：{observation['observation_type']} | 截止：{observation['as_of']} | 置信度：{observation['confidence']}",
                f"- 可能意味着：{'；'.join(observation['possible_implications'])}",
                f"- 其他解释：{'；'.join(observation['alternative_explanations'])}",
            ])
            if observation.get("leading_for"):
                lines.append(f"- 可能领先：{observation['leading_for']}（假设提前期：{observation.get('lead_time_hypothesis') or '未知'}）")
            lines.append("")

    if data.get("narrative_risks"):
        lines.extend(["## 官方叙事、遗漏与信息操纵风险", ""])
        for risk in data["narrative_risks"]:
            lines.extend([
                f"### {risk['narrative']}",
                "",
                f"- 风险类型：{risk['risk_type']} | 等级：{risk['risk_level']} | 受益方：{risk['beneficiary']}",
                f"- 被遗漏的背景：{risk['omitted_context']}",
                f"- 善意解释：{risk.get('benign_explanation', '')}",
                f"- 风险解释：{risk.get('risk_explanation', '')}",
                "",
            ])

    if data.get("intelligence_items"):
        lines.extend(["## 未证实情报簿", "", "> 本节不是事实结论。保留它是为了防止重要线索因尚未证实而消失。", ""])
        for item in data["intelligence_items"]:
            lines.extend([
                f"### [{item['intelligence_type']} / {item['status']}] {item['raw_claim']}",
                "",
                f"- 可信度：{item['confidence']}",
                f"- 来源关系：{item['source_relationship']}",
                f"- 来源动机：{item['source_motivation']}",
                f"- 支持信号：{'；'.join(item.get('supporting_signals', [])) or '无'}",
                f"- 反对信号：{'；'.join(item.get('opposing_signals', [])) or '无'}",
                f"- 若为真的影响：{item['impact_if_true']}",
                f"- 下一验证：{item['next_verification']}",
                f"- 原始说法证据：{evidence_labels(item.get('raw_source_evidence_ids', []), index)}",
                "",
            ])

    investment_present = any(
        data.get(field)
        for field in (
            "investment_context", "investment_conclusion", "decision_audit",
            "investment_theses", "valuation_scenarios", "income_analysis",
            "thesis_changes",
        )
    )
    if investment_present:
        lines.extend(["## 投资视角", ""])

    if data.get("investment_context"):
        context = data["investment_context"]
        reference = "未知" if context.get("reference_value") is None else f"{format_metric_value(context['reference_value'])} {context['currency']}"
        lines.extend([
            "### 投资上下文",
            "",
            f"- 标的：{context['instrument_name']} | 类型：{context['asset_type']}",
            f"- 代码/市场：{context.get('ticker') or '未提供'} / {context.get('exchange') or '未提供'}",
            f"- 估值日：{context['valuation_as_of']} | 持有期：{format_metric_value(context['holding_period_years'])} 年",
            f"- 参考值：{reference}（{context['reference_value_type']}；新鲜度 {context['freshness']}）",
            f"- 持仓：{context['position_status']} | 进入路径：{context['access_path']} | 资本结构：{context['capital_structure_status']}",
            f"- 参考值证据：{evidence_labels(context.get('reference_value_evidence_ids', []), index) or '无'}",
            f"- 资本结构证据：{evidence_labels(context.get('capital_structure_evidence_ids', []), index) or '无'}",
            "",
        ])

    conclusion = data.get("investment_conclusion")
    if conclusion:
        lines.extend([
            f"### 条件式结论：{conclusion['stance']}",
            "",
            conclusion["rationale"],
            "",
            f"- 价格/估值条件：{conclusion['price_condition']}",
            f"- 判断期限：{conclusion['horizon']} | 置信度：{conclusion['confidence']}",
            f"- 基准情景：{conclusion['anchor_scenario_id']}",
            f"- 失效条件：{'；'.join(conclusion['invalidators'])}",
            f"- 证据：{evidence_labels(conclusion['evidence_ids'], index)}",
            "",
        ])

    decision_audit = data.get("decision_audit")
    if decision_audit:
        lines.extend([
            "### 投资决策审计",
            "",
            f"- 阶段：{decision_audit['stage']} | 准备度：{decision_audit['overall_status']} | 置信度：{decision_audit['confidence']}",
            f"- 行为偏差信号：{' / '.join(decision_audit['behavioral_flags']) or '未评估'}",
            f"- 机会成本：{decision_audit['opportunity_cost']}",
            f"- 待满足条件：{'；'.join(decision_audit.get('conditions', [])) or '无'}",
            f"- 审计摘要：{decision_audit['summary']}",
            "",
            "| 决策门 | 状态 | 依据 | 解释 | 证据/用户输入 |",
            "|---|---|---|---|---|",
        ])
        for gate in decision_audit["gates"]:
            references = []
            evidence_text = evidence_labels(gate.get("evidence_ids", []), index)
            if evidence_text:
                references.append(evidence_text)
            references.extend(
                f"用户回答 #{answer_index + 1}"
                for answer_index in gate.get("user_answer_indices", [])
            )
            labels = "；".join(references) or "未取证"
            lines.append(
                f"| {gate['gate']} | {gate['status']} | {gate['basis']} | "
                f"{md_cell(gate['explanation'])} | {md_cell(labels)} |"
            )
        lines.append("")

    if data.get("investment_theses"):
        lines.extend(["### 核心投资论点", "", "| 类型 | 论点 | 状态 | 置信度 | 失效条件 | 复查 |", "|---|---|---|---|---|---|"])
        for thesis in data["investment_theses"]:
            lines.append(
                f"| {thesis['thesis_type']} | {md_cell(thesis['statement'])} | {thesis['status']} | {thesis['confidence']} | {md_cell('；'.join(thesis['falsifiers']))} | {md_cell(thesis['review_cadence'])} |"
            )
        lines.append("")

    if data.get("thesis_changes"):
        lines.extend([
            "### 投资论文漂移",
            "",
            "> 只比较事实和证据；股价变化归入估值，纯改写不算基本面变化。",
            "",
            "| 论点 | 基线→当前 | 变化类型 | 状态迁移 | 方向 | 动作影响 | 置信度 | 触发证据 |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for change in data["thesis_changes"]:
            thesis = index.get(change["thesis_id"], {}).get("statement", change["thesis_id"])
            lines.append(
                f"| {md_cell(thesis)} | {change['baseline_as_of']} → {change['current_as_of']} | {change['change_type']} | "
                f"{change['previous_status']} → {change['current_status']} | {change['direction']} | "
                f"{md_cell(change['action_impact'])} | {change['confidence']} | "
                f"{md_cell(evidence_labels(change['trigger_evidence_ids'], index)) or '纯措辞比较'} |"
            )
            lines.append(f"| 解释 |  |  |  |  | {md_cell(change['explanation'])} |  |  |")
        lines.append("")

    if data.get("valuation_scenarios"):
        lines.extend([
            "### 三情景估值",
            "",
            "> 目标价值是模型结果，不是可观察事实；回报由参考值、目标值和持有期复算。",
            "",
            "| 情景 | 方法 | 目标值 | 累计回报 | 年化回报 | 置信度 | 失效条件 |",
            "|---|---|---:|---:|---:|---|---|",
        ])
        for scenario in data["valuation_scenarios"]:
            lines.append(
                f"| {scenario['case']} | {md_cell(scenario['method'])} | {format_metric_value(scenario['target_value'])} {md_cell(scenario['currency'])} | {format_percent(scenario.get('expected_total_return'))} | {format_percent(scenario.get('expected_annual_return'))} | {scenario['confidence']} | {md_cell(scenario['falsifier'])} |"
            )
        lines.append("")

    if data.get("income_analysis"):
        income = data["income_analysis"]
        profile = income["distribution_profile"]
        lines.extend([
            "### 收益投资专项",
            "",
            f"- 分类：{income['classification']} | 证据质量：{income['evidence_quality']} | 置信度：{income['confidence']}",
            f"- 分配：{profile['distribution_type']} / {profile['frequency']} / {profile['currency']} / 历史 {format_metric_value(profile['history_years'])} 年",
            f"- 分配历史证据：{evidence_labels(profile['evidence_ids'], index)}",
            f"- 债务与再融资：{income['debt_refinancing_assessment']}",
            f"- 组合适配：{income['portfolio_fit']}",
            f"- 结论：{income['conclusion']}",
            "",
        ])
        if income.get("coverage_metrics"):
            lines.extend(["| 覆盖指标 | 周期 | 数值 | 证据 |", "|---|---|---:|---|"])
            for metric in income["coverage_metrics"]:
                lines.append(
                    f"| {md_cell(metric['metric'])} | {md_cell(metric['period'])} | "
                    f"{format_metric_value(metric['value'])} {md_cell(metric['unit'])} | "
                    f"{md_cell(evidence_labels(metric['evidence_ids'], index))} |"
                )
            lines.append("")
        if income.get("scenarios"):
            lines.extend(["| 收益情景 | 可分配现金 | 覆盖 | 分配结果 | 债务影响 | 估值影响 | 证据 |", "|---|---:|---:|---|---|---|---|"])
            for scenario in income["scenarios"]:
                cash = "未知" if scenario.get("distributable_cash") is None else format_metric_value(scenario["distributable_cash"])
                coverage = "未知" if scenario.get("payout_coverage") is None else format_metric_value(scenario["payout_coverage"])
                lines.append(
                    f"| {scenario['case']} | {cash} | {coverage} | {md_cell(scenario['distribution_outcome'])} | "
                    f"{md_cell(scenario['debt_effect'])} | {md_cell(scenario['valuation_effect'])} | "
                    f"{md_cell(evidence_labels(scenario['evidence_ids'], index))} |"
                )
            lines.append("")
            for scenario in income["scenarios"]:
                calculation = scenario["calculation"]
                components = " + ".join(
                    f"{item['name']}={format_metric_value(item['value'])}"
                    for item in calculation["cash_components"]
                )
                lines.append(
                    f"- **{scenario['case']} 复算**：可分配现金 = 现金组成项合计；"
                    f"覆盖倍数 = 可分配现金 / 分配额；"
                    f"输入：{components}；分配额={format_metric_value(calculation['distribution_amount'])}"
                )
            lines.append("")
        lines.extend(["收益阻断门：", ""])
        for gate in income["blocking_gates"]:
            labels = evidence_labels(gate.get('evidence_ids', []), index) or "无"
            lines.append(f"- **{gate['gate']} / {gate['status']}**：{gate['explanation']}；证据：{labels}")
        lines.append("")

    if data.get("scenarios"):
        lines.extend(["## 情景推演与观察清单", ""])
        for scenario in data["scenarios"]:
            lines.extend([
                f"### {scenario['name']}",
                "",
                f"- 触发条件：{scenario['trigger']}",
                f"- 如何解释：{scenario['interpretation']}",
                f"- 冲击变量：{'；'.join(scenario.get('shock_variables', [])) or '未量化'}",
                f"- 传导路径：{' → '.join(scenario.get('transmission_path', [])) or '未建立'}",
                f"- 影响维度：{'；'.join(scenario.get('impact_dimensions', [])) or '未声明'}",
                f"- 观察项：{'；'.join(scenario['watch_items'])}",
                f"- 领先指标：{'；'.join(scenario.get('leading_indicators', [])) or '未声明'}",
                f"- 推翻条件：{scenario.get('falsifier') or '未声明'}",
                "",
            ])

    if data.get("monitoring_plan"):
        lines.extend(["## 持续监控计划", "", "| 对象 | 指标 | 触发条件 | 频率 | 数据组 | 触发后动作 | 状态 |", "|---|---|---|---|---|---|---|"])
        for item in data["monitoring_plan"]:
            lines.append(f"| {md_cell(item['target'])} | {md_cell(item['indicator'])} | {md_cell(item['trigger'])} | {md_cell(item['cadence'])} | {md_cell(item['source_group'])} | {md_cell(item['action_if_triggered'])} | {item['status']} |")
        lines.append("")

    if data.get("scenario_results"):
        lines.extend(["## 情景敏感性区间", "", "> 这些是基于明确基线和冲击假设的敏感性计算，不是企业实际预测。", "", "| 情景 | 指标 | 基线 | 下界 | 基准 | 上界 | 单位 | 假设证据 |", "|---|---|---:|---:|---:|---:|---|---|"])
        for result in data["scenario_results"]:
            scenario = index.get(result["scenario_id"], {}).get("name", result["scenario_id"])
            lines.append(f"| {md_cell(scenario)} | {md_cell(result['metric'])} | {result['baseline']:g} | {result['lower_bound']:g} | {result['base_case']:g} | {result['upper_bound']:g} | {md_cell(result['unit'])} | {md_cell(evidence_labels(result['evidence_ids'], index))} |")
        lines.append("")

    if data.get("opportunities"):
        lines.extend(["## 商业切入点", ""])
        for opportunity in data["opportunities"]:
            lines.extend([
                f"### {opportunity['name']}：{opportunity['status']}",
                "",
                opportunity["rationale"],
                "",
                f"下一步最小验证：{opportunity.get('next_test', '未定义')}",
                "",
            ])

    if data.get("source_coverage"):
        lines.extend(["## 信源覆盖与缺口", "", "| 视角 | 状态 | 已采纳来源 | 缺口/下一步 |", "|---|---|---|---|"])
        for row in data["source_coverage"]:
            sources = evidence_labels(row.get("source_ids", []), index) or "无"
            gap = row.get("gap_reason") or row.get("next_search") or "—"
            lines.append(f"| {row['perspective']} | {row['status']} | {md_cell(sources)} | {md_cell(gap)} |")
        lines.append("")

    if data.get("source_health"):
        lines.extend(["## 数据源健康与新鲜度", "", "| 数据组 | 提供方 | 层 | 状态 | 观测时间 | 新鲜度预算 | 回退 | 缺失覆盖 |", "|---|---|---|---|---|---:|---|---|"])
        for health in data["source_health"]:
            missing = "；".join(health.get("missing_coverage", [])) or "无"
            lines.append(f"| {md_cell(health['source_group'])} | {md_cell(health['provider'])} | {health['layer']} | {health['status']} | {health['observed_at']} | {health['freshness_budget_hours']}h | {'是' if health['fallback_used'] else '否'} | {md_cell(missing)} |")
        lines.append("")

    if data.get("discarded_sources"):
        lines.extend(["## 垃圾信息与降级审计", "", "> 被丢弃不等于从未看见；这里记录去重、软文和未证实材料的处理理由。", ""])
        for item in data["discarded_sources"]:
            lines.append(f"- **{item['decision']}** [{item['title']}]({item['url']})：{item['reason']}")
        lines.append("")

    lines.extend(["## 局限", ""])
    lines.extend(f"- {item}" for item in data.get("limitations", []))
    lines.extend(["", "## 来源", ""])
    for source in data.get("sources", []):
        perspective = source.get("source_perspective", "unknown")
        bias = f"；可能偏差：{source['incentive_bias']}" if source.get("incentive_bias") else ""
        lines.append(f"- [{source['title']}]({source['url']}) — {source['authority']} / {source['evidence_type']} / {source['verification']} / {perspective}{bias}")
    return "\n".join(lines) + "\n"


def render_html(markdown_text: str, title: str) -> str:
    try:
        import markdown
        body = markdown.markdown(markdown_text, extensions=["tables"])
    except ImportError:
        body = f"<pre>{html.escape(markdown_text)}</pre>"
    body = sanitize_report_html(body)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;max-width:960px;margin:0 auto;padding:36px 20px;line-height:1.75;color:#172033;background:#f8fafc}}
h1,h2,h3{{color:#0f172a}} h2{{margin-top:36px;border-bottom:1px solid #cbd5e1;padding-bottom:8px}}
table{{border-collapse:collapse;width:100%;background:white}} th,td{{border:1px solid #cbd5e1;padding:8px;text-align:left;vertical-align:top}}
blockquote{{border-left:4px solid #2563eb;margin-left:0;padding-left:14px;color:#475569}} a{{color:#1d4ed8}}
</style></head><body>{body}</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("research", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = validate_before_render(args.research)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    markdown_text = render_markdown(data)
    (args.out_dir / "report.md").write_text(markdown_text, encoding="utf-8")
    (args.out_dir / "report.html").write_text(render_html(markdown_text, data["meta"]["title"]), encoding="utf-8")
    print(args.out_dir / "report.md")
    print(args.out_dir / "report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
