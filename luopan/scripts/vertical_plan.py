#!/usr/bin/env python3
"""Generate a reusable vertical-source research plan for a company."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote


ROUTES = [
    {
        "dimension": "government_procurement",
        "entry": "https://search.ccgp.gov.cn/bxsearch",
        "access": "http_or_browser_rate_limited",
        "queries": ["{company}", "{company} 中标", "{company} 合同", "{company} 验收"],
        "proves": ["公开采购关系", "项目金额与时间", "采购/代理主体"],
        "does_not_prove": ["收入确认", "回款", "持续复购"],
    },
    {
        "dimension": "corporate_registry",
        "entry": "https://www.gsxt.gov.cn/index.html",
        "access": "browser_manual_likely",
        "queries": ["{company}", "{brand}", "{founder}"],
        "proves": ["法定主体", "股东与变更", "登记处罚"],
        "does_not_prove": ["真实营收", "隐性控制关系"],
    },
    {
        "dimension": "patent_and_trademark",
        "entry": "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch",
        "access": "browser_manual_likely",
        "queries": ["申请人 {company}", "发明人 {founder}", "产品型号 {product}"],
        "proves": ["技术资产", "申请人/发明人", "法律状态"],
        "does_not_prove": ["技术先进", "量产", "客户采用"],
    },
    {
        "dimension": "icp_and_domain",
        "entry": "https://beian.miit.gov.cn/",
        "access": "browser_manual_likely",
        "queries": ["{domain}", "{company}"],
        "proves": ["域名备案主体", "主体与网站的时间关系"],
        "does_not_prove": ["网站当前经营主体", "产品真实性"],
    },
    {
        "dimension": "certification_and_recall",
        "entry": "https://cx.cnca.cn/CertECloud/index/index/page",
        "secondary_entry": "https://www.samrdprc.org.cn/search/searchlist.jsp",
        "access": "browser_or_http",
        "queries": ["{company}", "{brand}", "{product}"],
        "proves": ["认证/召回持有人", "产品型号", "合规与缺陷边界"],
        "does_not_prove": ["销量", "总体故障率"],
    },
    {
        "dimension": "environment_and_capacity",
        "entry": "https://www.google.com/search?q={query}",
        "access": "search_then_government_http_or_pdf",
        "queries": ["{company} 环评", "{company} 能评", "{company} 排污许可", "{company} 项目公示", "{address} 环评"],
        "proves": ["项目地址", "设备与理论产能", "扩建时间"],
        "does_not_prove": ["实际利用率", "实际销量"],
    },
    {
        "dimension": "judicial_and_enforcement",
        "entry": "https://wenshu.court.gov.cn/",
        "secondary_entry": "https://zxgk.court.gov.cn/",
        "access": "browser_manual_likely",
        "queries": ["{company}", "{founder}", "{company} 合同", "{company} 知识产权", "{company} 劳动"],
        "proves": ["公开纠纷与执行", "合同/回款/劳动风险线索"],
        "does_not_prove": ["整体违约率", "整体管理质量"],
    },
    {
        "dimension": "hiring_and_people",
        "entry": "company_site_and_public_job_boards",
        "access": "http_scrapling_or_browser",
        "queries": ["{company} 招聘", "{company} {product} 招聘", "{company} 校园招聘", "{founder} 团队"],
        "proves": ["资源配置意图", "岗位职能与地区", "团队能力线索"],
        "does_not_prove": ["净增员", "项目成功", "营收增长"],
    },
    {
        "dimension": "customers_suppliers_channels",
        "entry": "reverse_search",
        "access": "search_http_scrapling_or_browser",
        "queries": ["\"{company}\" 客户", "\"{company}\" 供应商", "\"{company}\" 经销商", "\"{brand}\" 报价", "\"{product}\" 采购"],
        "proves": ["外部关系线索", "价格/渠道/部署"],
        "does_not_prove": ["Logo 等于付费客户", "报价等于成交价"],
    },
]


def render_query(template: str, values: dict[str, object]) -> str | None:
    required = [name for name, value in values.items() if "{" + name + "}" in template]
    if any(not values[name] for name in required):
        return None
    scalar_values = {name: value for name, value in values.items() if not isinstance(value, list)}
    return template.format(**scalar_values)


def route_queries(route: dict, values: dict[str, object]) -> list[str]:
    """Expand company-specific routes for the canonical entity and aliases.

    Aliases only substitute `{company}`; brand/product/founder inputs remain
    unchanged so legal-entity queries stay precise and do not create list
    literals in rendered search strings.
    """
    companies = [str(values.get("company") or ""), *[str(item) for item in values.get("alias", []) if str(item).strip()]]
    rendered: list[str] = []
    for company in dict.fromkeys(item.strip() for item in companies if item.strip()):
        scoped = {**values, "company": company}
        for template in route["queries"]:
            query = render_query(template, scoped)
            if query and query not in rendered:
                rendered.append(query)
    return rendered


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--brand", default="")
    parser.add_argument("--alias", action="append", default=[], help="additional legal, historic, or subsidiary name")
    parser.add_argument("--founder", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--product", default="")
    parser.add_argument("--address", default="")
    args = parser.parse_args()
    values = vars(args)

    routes = []
    for route in ROUTES:
        item = dict(route)
        queries = route_queries(route, values)
        item["queries"] = queries
        if "{query}" in item.get("entry", ""):
            item["entry_template"] = item.pop("entry")
            item["example_urls"] = [
                item["entry_template"].format(query=quote(query)) for query in item["queries"]
            ]
        routes.append(item)

    print(json.dumps({"subject": values, "routes": routes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
