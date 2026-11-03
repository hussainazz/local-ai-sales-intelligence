"""Deterministic business metrics with coverage and source/version attribution."""

import json
from collections import Counter
from itertools import combinations

import pandas as pd
import plotly.express as px
import plotly.io as pio

from .ingestion import atomic_json
from .preparation import load_clean
from .schemas import Filters


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def filtered(frame, filters):
    frame = frame.copy()
    for key, operator in [("start", "ge"), ("end", "le")]:
        value = getattr(filters, key)
        if value:
            date = pd.Timestamp(value)
            if date.tzinfo:
                raise ValueError("Filters use local calendar dates without timezone offsets.")
            if key == "end":
                date = date.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            frame = frame.loc[getattr(frame.transaction_date, operator)(date)]
    if filters.start and filters.end and pd.Timestamp(filters.start) > pd.Timestamp(filters.end):
        raise ValueError("The start date must be before the end date.")
    for column in ["customer_id", "product_id"]:
        value = getattr(filters, column)
        if value is not None:
            if column not in frame:
                raise ValueError(f"{column} is unavailable.")
            frame = frame.loc[frame[column] == value]
    return frame


def require(frame, columns):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Required fields are unavailable: {sorted(missing)}")


def summary(frame):
    values = frame._net_sales.dropna()
    result = {
        "net_sales": float(values.sum()) if len(values) else None,
        "rows": len(frame),
        "sales_rows_included": len(values),
        "sales_rows_missing": int(frame._net_sales.isna().sum()),
        "dates_missing": int(frame.transaction_date.isna().sum()),
        "orders": None,
        "average_order_value": None,
        "definitions": {
            "net_sales": "Sum of confirmed net line/order amounts, including negative returns.",
            "orders": "Distinct non-null order IDs in the filtered rows.",
            "average_order_value": "Net sales of fully valued known orders / number of those orders.",
        },
    }
    if "order_id" in frame:
        known = frame.loc[frame.order_id.notna()]
        grouped = known.groupby("order_id")._net_sales.agg(["sum", "count", "size"])
        complete = grouped.loc[grouped["count"] == grouped["size"]]
        result.update(
            orders=int(known.order_id.nunique()),
            order_rows_missing=int(frame.order_id.isna().sum()),
            complete_orders=len(complete),
            incomplete_orders=len(grouped) - len(complete),
            average_order_value=float(complete["sum"].mean()) if len(complete) else None,
        )
    if "_profit" in frame:
        valid = frame._profit.notna()
        result.update(
            profit=float(frame.loc[valid, "_profit"].sum()) if valid.any() else None,
            profit_rows_included=int(valid.sum()),
            profit_rows_missing=int((~valid).sum()),
        )
    if "sales_quantity" in frame:
        result["quantity"] = (
            float(frame.sales_quantity.sum(min_count=1)) if frame.sales_quantity.notna().any() else None
        )
    if "discount" in frame:
        result["monetary_discount"] = float(frame.discount.sum())
    return result


def ranked(frame, column, limit):
    require(frame, [column])
    valid = frame.loc[frame[column].notna() & frame._net_sales.notna()]
    result = (
        valid.groupby(column, as_index=False)._net_sales.sum().rename(columns={"_net_sales": "net_sales"})
    )
    result = result.sort_values("net_sales", ascending=False)
    if len(result) and (result.net_sales >= 0).all() and result.net_sales.sum() > 0:
        result["share"] = result.net_sales / result.net_sales.sum()
        result["cumulative_share"] = result.share.cumsum()
    return {
        "ranking": records(result.head(limit)),
        "entities": len(result),
        "excluded_rows": int(len(frame) - len(valid)),
        "ranking_limit": limit,
        "pareto_available": "cumulative_share" in result,
    }


def trend(frame):
    valid = frame.dropna(subset=["transaction_date", "_net_sales"])
    daily = valid.groupby(valid.transaction_date.dt.strftime("%Y-%m-%d"))._net_sales.sum()
    result = daily.rename_axis("date").reset_index(name="net_sales")
    median = daily.median()
    mad = (daily - median).abs().median()
    if mad > 0:
        result["anomaly"] = (0.6745 * (daily.to_numpy() - median) / mad).__abs__() > 3.5
    else:
        result["anomaly"] = False
    return {
        "daily": records(result),
        "excluded_rows": len(frame) - len(valid),
        "definition": "Observed daily totals. Missing dates are not automatically treated as zero.",
        "anomaly_method": "Two-sided robust median absolute deviation; exploratory, not a causal explanation.",
    }


def rfm(frame):
    require(frame, ["customer_id", "order_id"])
    valid = frame.dropna(subset=["customer_id", "order_id", "transaction_date", "_net_sales"])
    if valid.empty:
        raise ValueError("RFM requires known customers, orders, dates and amounts.")
    reference = valid.transaction_date.max().normalize() + pd.Timedelta(days=1)
    result = (
        valid.groupby("customer_id")
        .agg(
            last_purchase=("transaction_date", "max"),
            frequency=("order_id", "nunique"),
            monetary=("_net_sales", "sum"),
        )
        .reset_index()
    )
    result["recency_days"] = (reference - result.last_purchase.dt.normalize()).dt.days
    result = result.drop(columns="last_purchase")
    return {
        "customers": records(result),
        "reference_date": reference.date().isoformat(),
        "excluded_rows": len(frame) - len(valid),
        "definition": "Recency from day after latest observed purchase; frequency is distinct orders.",
    }


def retention(frame):
    require(frame, ["customer_id"])
    valid = frame.dropna(subset=["customer_id", "transaction_date"])[
        ["customer_id", "transaction_date"]
    ].copy()
    if valid.empty:
        raise ValueError("Retention requires customer IDs and valid dates.")
    valid["month"] = valid.transaction_date.dt.to_period("M")
    valid["cohort"] = valid.groupby("customer_id").month.transform("min")
    valid["age"] = valid.month.astype("int64") - valid.cohort.astype("int64")
    sizes = valid.groupby("cohort").customer_id.nunique()
    table = valid.groupby(["cohort", "age"]).customer_id.nunique().reset_index(name="customers")
    table["cohort_size"] = table.cohort.map(sizes)
    table["retention"] = table.customers / table.cohort_size
    table["cohort"] = table.cohort.astype(str)
    repeat = valid.groupby("customer_id").month.nunique()
    return {
        "cohorts": records(table),
        "customers_active_in_multiple_months": int((repeat > 1).sum()),
        "definition": "Monthly repeat activity using first purchase observed in this dataset, not necessarily the customer's lifetime first purchase.",
        "limitation": "Filtered history changes cohort assignment. The most recent month may be incomplete.",
    }


def basket(frame, limit=20):
    require(frame, ["order_id", "product_id"])
    valid = frame.dropna(subset=["order_id", "product_id", "_net_sales"])
    valid = valid.loc[valid._net_sales > 0]
    if "sales_quantity" in valid:
        valid = valid.loc[valid.sales_quantity > 0]
    orders = valid.groupby("order_id").product_id.agg(lambda values: sorted(set(values)))
    if len(orders) < 20 or valid.product_id.nunique() > 500 or orders.map(len).max() > 100:
        raise ValueError(
            "Basket analysis needs at least 20 orders, at most 500 products and 100 products per order."
        )
    singles, pairs = Counter(), Counter()
    for items in orders:
        singles.update(items)
        pairs.update(combinations(items, 2))
    rows = []
    for (a, b), count in pairs.items():
        if count < 3:
            continue
        for left, right in [(a, b), (b, a)]:
            rows.append(
                {
                    "antecedent": left,
                    "consequent": right,
                    "orders": count,
                    "support": count / len(orders),
                    "confidence": count / singles[left],
                    "lift": (count / singles[left]) / (singles[right] / len(orders)),
                }
            )
    rows.sort(key=lambda item: (item["lift"], item["orders"]), reverse=True)
    return {
        "rules": rows[:limit],
        "orders": len(orders),
        "minimum_pair_orders": 3,
        "limitation": "Co-purchase associations do not establish that one product causes another purchase.",
    }


TOOLS = {"summary": summary, "trend": trend, "rfm": rfm, "retention": retention}


def analyze(store, dataset_id, kind="summary", filters=None):
    filters = filters or Filters()
    frame, data = load_clean(store, dataset_id)
    frame = filtered(frame, filters)
    if frame.empty:
        raise ValueError("No rows match these filters.")
    if kind == "products":
        payload = ranked(frame, "product_id", filters.limit)
    elif kind == "customers":
        payload = ranked(frame, "customer_id", filters.limit)
    elif kind == "regions":
        payload = ranked(frame, "region", filters.limit)
    elif kind == "basket":
        payload = basket(frame, filters.limit)
    elif kind == "correlation":
        numeric = frame.select_dtypes(include="number").drop(columns=["_row_id"], errors="ignore")
        numeric = numeric.dropna(axis=1, how="all")
        payload = {
            "matrix": json.loads(numeric.corr(min_periods=10).to_json()),
            "limitation": "Correlation is exploratory and does not establish causation.",
        }
    elif kind in TOOLS:
        payload = TOOLS[kind](frame)
    else:
        raise ValueError("Unknown deterministic analysis tool.")
    result = {
        "dataset_id": dataset_id,
        "dataset_version": data["version"],
        "analysis": kind,
        "source_hash": data["meta"]["content_hash"],
        "currency": data["meta"]["mapping"]["currency"],
        "sales_definition": data["meta"]["mapping"]["sales_definition"],
        "filters": filters.model_dump(),
        "result": payload,
    }
    # Always execute the query against the requested data; the artifact is a versioned saved result.
    atomic_json(store.cache_path(dataset_id, kind, filters.model_dump(), version=data["version"]), result)
    return result


def dashboard(store, dataset_id, filters=None):
    filters = filters or Filters()
    dataset = store.get(dataset_id)
    result, figures, unavailable = {}, [], {}
    for kind in [
        "summary",
        "trend",
        "products",
        "customers",
        "rfm",
        "retention",
        "basket",
        "regions",
        "correlation",
    ]:
        try:
            result[kind] = analyze(store, dataset_id, kind, filters)
        except ValueError as exc:
            unavailable[kind] = str(exc)
    if store.get(dataset_id)["version"] != dataset["version"] or any(
        item["dataset_version"] != dataset["version"] for item in result.values()
    ):
        raise ValueError("Dataset changed while building the dashboard. Run it again.")
    currency = dataset["meta"]["mapping"]["currency"]
    if "trend" in result:
        table = pd.DataFrame(result["trend"]["result"]["daily"])
        if len(table):
            chart = px.line(table, x="date", y="net_sales", title=f"فروش روزانه · {currency}")
            figures.append(json.loads(pio.to_json(chart)))
    for kind, column, title in [
        ("products", "product_id", "فروش محصولات"),
        ("customers", "customer_id", "فروش مشتریان"),
    ]:
        if kind in result:
            table = pd.DataFrame(result[kind]["result"]["ranking"])
            if len(table):
                figures.append(
                    json.loads(
                        pio.to_json(px.bar(table, x=column, y="net_sales", title=f"{title} · {currency}"))
                    )
                )
    return {
        "dataset_version": dataset["version"],
        "analyses": result,
        "figures": figures,
        "unavailable": unavailable,
        "filters": filters.model_dump(),
        "currency": currency,
    }
