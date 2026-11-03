import hashlib
import json
import re
from itertools import pairwise
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .analytics import analyze
from .llm import LocalModel
from .ml import forecast
from .rag import retrieve
from .schemas import Chat, Forecast


class AgentState(TypedDict, total=False):
    dataset_id: str
    request: dict
    tool: str
    version: int
    findings: dict
    evidence: list[dict]
    documents: list[dict]
    advice: list[dict]
    warnings: list[str]
    answer: dict


ACTIONS = {
    "review_product_mix": {
        "tools": {"products", "basket"},
        "text": "ترکیب محصولات و فرصت‌های فروش مکمل را با توجه به داده‌های مشاهده‌شده بررسی کنید.",
    },
    "investigate_trend": {
        "tools": {"trend", "forecast"},
        "text": "تغییرات فروش را با رویدادهای ثبت‌شده کسب‌وکار مقایسه کنید؛ علت تغییر هنوز تأیید نشده است.",
    },
    "review_customer_followup": {
        "tools": {"customers", "rfm", "retention"},
        "text": "اولویت پیگیری مشتریان را براساس سابقه خرید و با بررسی تیم فروش تعیین کنید.",
    },
    "verify_data_quality": {
        "tools": {"summary", "products", "customers", "trend", "rfm", "retention", "basket", "forecast"},
        "text": "پوشش داده، مقادیر خالی و تعریف شاخص‌ها را پیش از تصمیم تجاری مرور کنید.",
    },
}


def describe_finding(finding, currency):
    """Render computed facts in Persian without asking a model to author numbers."""
    digits = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")

    def amount(value):
        return format(value, ",.2f").rstrip("0").rstrip(".").translate(digits)

    kind, value = finding["analysis"], finding["result"]
    if kind == "summary" and value.get("net_sales") is not None:
        return f"فروش خالص در داده‌های انتخاب‌شده {amount(value['net_sales'])} {currency} است. پوشش داده و تعریف فروش را همراه این نتیجه بررسی کنید."
    if kind in {"products", "customers"} and value.get("ranking"):
        top = value["ranking"][0]
        name = "محصول" if kind == "products" else "مشتری"
        identifier = top["product_id" if kind == "products" else "customer_id"]
        return f"در رتبه‌بندی داده‌های انتخاب‌شده، {name} با شناسه {identifier} و فروش خالص {amount(top['net_sales'])} {currency} در جایگاه نخست است."
    if kind == "trend" and value.get("daily"):
        last = value["daily"][-1]
        return f"آخرین جمع روزانه ثبت‌شده در بازه انتخابی {amount(last['net_sales'])} {currency} است. روند مشاهده‌شده به‌تنهایی علت تغییر فروش را مشخص نمی‌کند."
    if kind == "forecast":
        return "پیش‌بینی همراه با نتیجه مقایسه مدل و روش پایه ارائه شده است. بازه نمایش‌داده‌شده تضمین‌کننده نتیجه آینده نیست."
    return "نتیجه محاسبه، تعریف شاخص و منبع داده در ادامه آمده است."


def keyword_route(question):
    question = question.lower()
    for words, tool in [
        (["تخفیف", "discount", "what if", "اگر", "churn", "ریزش", "سود", "profit"], "unsupported"),
        (["forecast", "پیش‌بینی", "پیش بینی"], "forecast"),
        (["basket", "together", "همراه", "مکمل", "با هم"], "basket"),
        (["retention", "cohort", "ماندگاری", "بازگشت مشتری"], "retention"),
        (["rfm", "بخش‌بندی", "بخش بندی"], "rfm"),
        (["trend", "why", "چرا", "روند", "کاهش"], "trend"),
        (["product", "محصول", "کالا"], "products"),
        (["customer", "مشتری"], "customers"),
        (["sales", "revenue", "فروش", "درآمد", "summary", "خلاصه"], "summary"),
    ]:
        if any(word in question for word in words):
            return tool
    return "unsupported"


def evidence_for(findings):
    digest = hashlib.sha256(json.dumps(findings, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    return [
        {
            "id": f"dataset:{digest}",
            "type": "dataset_finding",
            "analysis": findings["analysis"],
            "dataset_id": findings["dataset_id"],
            "version": findings["dataset_version"],
            "source_hash": findings.get("source_hash"),
            "filters": findings.get("filters"),
            "values": findings["result"],
        }
    ]


def run_agent(store, settings, dataset_id, request: Chat, task_id=None):
    model = LocalModel(settings, store)

    def orchestrator(state):
        warnings = []
        # Relative dates must be resolved visibly by the person, rather than silently ignored.
        temporal = r"last month|last week|this month|yesterday|ماه گذشته|ماه قبل|هفته گذشته|دیروز"
        has_dates = request.filters.start is not None and request.filters.end is not None
        if re.search(temporal, request.question.lower()) and not has_dates:
            return {
                "tool": "unsupported",
                "warnings": ["برای پرسش زمانی، ابتدا شروع و پایان بازه را در فیلتر تاریخ مشخص کنید."],
            }
        tool = keyword_route(request.question)
        if request.use_llm:
            try:
                route, _ = model.route(request.question)
                tool = route.tool
            except Exception as exc:  # noqa: BLE001 - inference failure must not prevent deterministic analysis
                store.audit(dataset_id, "local_model_route_failed", {"error_type": type(exc).__name__})
                warnings.append("مدل محلی پاسخ معتبر نداد؛ انتخاب ابزار با قواعد محدود انجام شد.")
        return {"tool": tool, "warnings": warnings}

    def data_agent(state):
        data = store.get(dataset_id)
        if "cleaned" not in data["meta"]:
            raise ValueError("Human-confirmed mapping and cleaning are required before the agent can run.")
        return {"version": data["version"]}

    def analytics_agent(state):
        tool = state["tool"]
        if tool == "unsupported":
            return {"findings": {}, "evidence": []}
        try:
            if tool == "forecast":
                payload = forecast(store, dataset_id, Forecast(), request.filters)
                finding = {
                    "dataset_id": dataset_id,
                    "dataset_version": state["version"],
                    "analysis": tool,
                    "source_hash": store.get(dataset_id)["meta"]["content_hash"],
                    "filters": request.filters.model_dump(),
                    "result": payload,
                }
            else:
                finding = analyze(store, dataset_id, tool, request.filters)
            if finding["dataset_version"] != state["version"]:
                raise ValueError("Dataset changed during analysis. Retry on the new version.")
            return {"findings": finding, "evidence": evidence_for(finding)}
        except ValueError as exc:
            return {"findings": {}, "evidence": [], "warnings": [*state["warnings"], str(exc)]}

    def intelligence_agent(state):
        evidence = state["evidence"]
        if not evidence:
            return {"advice": [], "documents": []}
        tool = state["tool"]
        eligible = {name for name, definition in ACTIONS.items() if tool in definition["tools"]}
        chosen = [{"action": name, "evidence_ids": [evidence[0]["id"]]} for name in sorted(eligible)]
        documents = []
        if request.use_llm:
            try:
                advice, _ = model.advice(evidence)
                allowed_ids = {item["id"] for item in evidence}
                chosen = [
                    item.model_dump()
                    for item in advice.items
                    if item.action in eligible and set(item.evidence_ids) <= allowed_ids
                ]
                documents = retrieve(store, dataset_id, request.question, model)
            except Exception as exc:  # noqa: BLE001 - preserve the verified result when optional inference fails
                store.audit(
                    dataset_id, "optional_model_or_retrieval_failed", {"error_type": type(exc).__name__}
                )
        return {
            "advice": [
                {
                    **item,
                    "text": ACTIONS[item["action"]]["text"],
                    "type": "review_suggestion",
                    "confidence": "not_a_tested_causal_effect",
                }
                for item in chosen
            ],
            "documents": documents,
        }

    def reporting_agent(state):
        if store.get(dataset_id)["version"] != state["version"]:
            raise ValueError("Dataset changed while reporting. Re-run the request.")
        supported = bool(state["evidence"])
        return {
            "answer": {
                "status": "completed" if supported else "needs_clarification_or_data",
                "question": request.question,
                "selected_tool": state["tool"],
                "dataset_version": state["version"],
                "verified_findings": state["evidence"],
                "organizational_knowledge": state["documents"],
                "interpretations_and_review_actions": state["advice"],
                "warnings": state["warnings"],
                "message": describe_finding(
                    state["findings"], store.get(dataset_id)["meta"]["mapping"]["currency"]
                )
                if supported
                else "برای این پرسش داده کافی یا ابزار تأییدشده در دسترس نیست. هدف تحلیل یا فیلترها را مشخص کنید.",
                "limits": [
                    "نتایج مشاهده‌شده علت قطعی تغییر فروش را اثبات نمی‌کنند.",
                    "پیشنهادها برای بررسی‌اند و نتیجه تجاری تضمین‌شده ندارند.",
                ],
            }
        }

    graph = StateGraph(AgentState)
    for name, node in [
        ("orchestrator", orchestrator),
        ("data_agent", data_agent),
        ("analytics_agent", analytics_agent),
        ("intelligence_agent", intelligence_agent),
        ("reporting_agent", reporting_agent),
    ]:
        graph.add_node(name, node)
    names = [
        START,
        "orchestrator",
        "data_agent",
        "analytics_agent",
        "intelligence_agent",
        "reporting_agent",
        END,
    ]
    for left, right in pairwise(names):
        graph.add_edge(left, right)
    with SqliteSaver.from_conn_string(str(store.root / "graph_state.sqlite")) as checkpointer:
        workflow = graph.compile(checkpointer=checkpointer)
        output = workflow.invoke(
            {"dataset_id": dataset_id, "request": request.model_dump()},
            {"configurable": {"thread_id": dataset_id + ":" + (task_id or str(uuid4()))}},
        )
    return output["answer"]
