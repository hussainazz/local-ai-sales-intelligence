import html
import io
import json

import pandas as pd

from .analytics import analyze
from .preparation import load_clean
from .schemas import Simulation


def simulate(store, dataset_id, request: Simulation):
    if not request.assumptions_confirmed:
        raise ValueError(
            "Confirm that this is arithmetic under assumptions, not an estimated demand response."
        )
    frame, data = load_clean(store, dataset_id)
    if frame._net_sales.isna().any() or (frame._net_sales < 0).any():
        raise ValueError("Simulation requires complete, nonnegative net amounts; analyze returns separately.")
    new_discount = request.current_discount_rate + request.discount_change_points
    if not 0 <= new_discount < 1:
        raise ValueError("The resulting discount rate must be between zero and one, excluding one.")
    baseline = float(frame._net_sales.sum())
    gross = baseline / (1 - request.current_discount_rate)
    hypothetical = gross * (1 + request.price_change) * (1 + request.volume_change) * (1 - new_discount)
    result = {
        "dataset_version": data["version"],
        "currency": data["meta"]["mapping"]["currency"],
        "baseline_net_sales": baseline,
        "hypothetical_net_sales": hypothetical,
        "difference": hypothetical - baseline,
        "assumptions": request.model_dump(),
        "formula": "baseline_net/(1-current_discount) * (1+price_change) * (1+volume_change) * (1-new_discount)",
        "kind": "arithmetic_scenario",
        "causal_prediction": False,
        "limitations": [
            "Applies one user-confirmed average discount rate to all sales.",
            "Volume response is supplied by the user, not learned from observational data.",
            "Retention and CLV changes need a separately validated behavioral model.",
        ],
    }
    if "_total_cost" in frame and frame._total_cost.notna().all():
        result["hypothetical_profit"] = hypothetical - float(frame._total_cost.sum()) * (
            1 + request.volume_change
        )
        result["cost_assumption"] = (
            "Costs scale linearly with volume; unit costs stay fixed. Fixed costs are not separated."
        )
    return result


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export(store, dataset_id, format):
    frame, data = load_clean(store, dataset_id)
    safe = frame.map(safe_cell)
    if format == "csv":
        return safe.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8", "cleaned.csv"
    if format == "xlsx":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            safe.to_excel(writer, sheet_name="Cleaned", index=False)
            pd.DataFrame([{"metadata": json.dumps(data["meta"], ensure_ascii=False)}]).to_excel(
                writer, sheet_name="Metadata", index=False
            )
        return (
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "report.xlsx",
        )
    report = {"summary": analyze(store, dataset_id), "quality": data["meta"]["quality"]}
    if format == "json":
        return (
            json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode(),
            "application/json",
            "report.json",
        )
    if format == "html":
        text = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
        body = f'<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>گزارش فروش</title><body><h1>گزارش فروش</h1><pre dir="auto">{text}</pre></body></html>'
        return body.encode(), "text/html; charset=utf-8", "report.html"
    raise ValueError("Supported exports: csv, xlsx, json, html.")
