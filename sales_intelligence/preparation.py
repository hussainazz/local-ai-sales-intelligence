import math
import re
from datetime import datetime
from uuid import uuid4

import jdatetime
import pandas as pd

from .ingestion import atomic_json, raw_sheet
from .schemas import Cleaning, Mapping, Relationship

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ALIASES = {
    "customer_id": ["customer_id", "customerid", "کد مشتری", "شناسه مشتری"],
    "product_id": ["product_id", "sku", "کد کالا", "شناسه محصول"],
    "product_name": ["product_name", "product", "نام محصول", "نام کالا"],
    "customer_name": ["customer_name", "نام مشتری"],
    "order_id": ["order_id", "invoice_id", "شماره فاکتور", "کد سفارش"],
    "transaction_date": ["transaction_date", "date", "تاریخ", "تاریخ فروش"],
    "sales_amount": ["sales_amount", "revenue", "مبلغ فروش", "فروش خالص"],
    "sales_quantity": ["sales_quantity", "quantity", "qty", "تعداد"],
    "cost": ["cost", "هزینه", "بهای تمام شده"],
    "discount": ["discount", "تخفیف"],
}


def normalize(value):
    return re.sub(r"[\s_\-\u200c]+", "", str(value).lower().replace("ي", "ی").replace("ك", "ک"))


def inspect(store, dataset_id):
    data = store.get(dataset_id)
    profiles = {}
    for sheet in data["meta"]["sheets"]:
        frame = raw_sheet(store, dataset_id, sheet)
        columns = {}
        suggestions = {}
        for column in frame.columns:
            values = frame[column].dropna()
            numeric = pd.to_numeric(values, errors="coerce")
            columns[column] = {
                "nulls": int(frame[column].isna().sum()),
                "unique": int(values.nunique()),
                "storage_dtype": str(frame[column].dtype),
                "numeric_parse_ratio": float(numeric.notna().mean()) if len(values) else 0,
            }
            matches = [
                canonical
                for canonical, aliases in ALIASES.items()
                if normalize(column) in {normalize(alias) for alias in aliases}
            ]
            if len(matches) == 1:
                suggestions[matches[0]] = column
        profiles[sheet] = {
            "rows": len(frame),
            "exact_duplicate_rows": int(frame.duplicated().sum()),
            "columns": columns,
            "mapping_suggestions": suggestions,
            "suggestions_require_confirmation": True,
        }
    return {"dataset_id": dataset_id, "version": data["version"], "sheets": profiles}


def save_mapping(store, dataset_id, request: Mapping):
    data = store.get(dataset_id)
    frame = raw_sheet(store, dataset_id, request.sheet)
    missing = set(request.columns.values()) - set(frame.columns)
    if missing:
        raise ValueError(f"Source columns do not exist: {sorted(missing)}")
    meta = data["meta"]
    meta.update(mapping=request.model_dump(), relationships=[], state="mapped")
    meta.pop("cleaned", None)
    store.update(dataset_id, meta, data["version"])
    store.audit(dataset_id, "mapping_confirmed", request.model_dump())
    return store.get(dataset_id)


def save_relationship(store, dataset_id, request: Relationship):
    if not request.confirmed:
        raise ValueError("A person must confirm the relationship.")
    data = store.get(dataset_id)
    mapping = Mapping.model_validate(data["meta"].get("mapping", {}))
    if request.sheet == mapping.sheet:
        raise ValueError("A dimension must be a different sheet.")
    left = raw_sheet(store, dataset_id, mapping.sheet)
    right = raw_sheet(store, dataset_id, request.sheet)
    if request.left_on not in left or request.right_on not in right:
        raise ValueError("Join columns do not exist.")
    if request.right_on in request.columns or set(request.columns) - set(right.columns):
        raise ValueError("Select existing dimension columns, excluding its key.")
    if set(request.columns) & set(left.columns):
        raise ValueError("Rename overlapping dimension columns before joining.")
    if right[request.right_on].isna().any() or right[request.right_on].duplicated().any():
        raise ValueError("Dimension keys must be non-null and unique. Join would risk double counting.")
    if request.cardinality == "one_to_one" and left[request.left_on].duplicated().any():
        raise ValueError("The sales key is not unique.")
    unmatched = ~left[request.left_on].isin(right[request.right_on])
    if unmatched.any() and not request.allow_unmatched:
        raise ValueError(f"{int(unmatched.sum())} sales rows have no matching dimension. Confirm explicitly.")
    existing = data["meta"].get("relationships", [])
    if existing:
        raise ValueError("This version supports one dimension join per dataset; combine dimensions upstream.")
    data["meta"]["relationships"] = [request.model_dump()]
    data["meta"].pop("cleaned", None)
    data["meta"]["state"] = "mapped"
    store.update(dataset_id, data["meta"], data["version"])
    store.audit(
        dataset_id, "relationship_confirmed", {**request.model_dump(), "unmatched": int(unmatched.sum())}
    )
    return {"unmatched": int(unmatched.sum()), "rows_before": len(left), "relationship": request.model_dump()}


def number(value, policy):
    if pd.isna(value) or str(value).strip() == "":
        return float("nan")
    text = str(value).translate(DIGITS).strip().replace("−", "-").replace("٫", policy.decimal_separator)
    if policy.thousands_separator:
        # Reject ambiguous or malformed groups instead of silently changing their value.
        sep = re.escape(policy.thousands_separator)
        decimal = re.escape(policy.decimal_separator)
        if policy.thousands_separator in text and not re.fullmatch(
            rf"[+-]?\d{{1,3}}(?:{sep}\d{{3}})+(?:{decimal}\d+)?", text
        ):
            raise ValueError(f"Invalid thousands grouping: {text[:80]}")
        text = text.replace(policy.thousands_separator, "")
    text = text.replace(policy.decimal_separator, ".").replace("٫", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError(f"Invalid numeric value: {text[:80]}")
    result = float(text)
    if not math.isfinite(result):
        raise ValueError("Nonfinite numeric value.")
    return result


def parse_date(value, mapping):
    if pd.isna(value):
        return pd.NaT
    text = str(value).translate(DIGITS).strip()
    if mapping.date_calendar == "jalali":
        return pd.Timestamp(jdatetime.datetime.strptime(text, mapping.date_format).togregorian())
    return pd.Timestamp(datetime.strptime(text, mapping.date_format))


def clean(store, dataset_id, policy: Cleaning):
    data = store.get(dataset_id)
    mapping = Mapping.model_validate(data["meta"].get("mapping", {}))
    frame = raw_sheet(store, dataset_id, mapping.sheet)
    frame["_row_id"] = range(2, len(frame) + 2)
    for relation in data["meta"].get("relationships", []):
        right = raw_sheet(store, dataset_id, relation["sheet"])
        selected = right[[relation["right_on"], *relation["columns"]]]
        count = len(frame)
        frame = frame.merge(
            selected,
            left_on=relation["left_on"],
            right_on=relation["right_on"],
            how="left",
            validate=relation["cardinality"],
            suffixes=("", "__dimension_key"),
        )
        if len(frame) != count:
            raise ValueError("Join changed the number of sales rows.")
    source_to_canonical = {source: target for target, source in mapping.columns.items()}
    rename = {
        column: source_to_canonical.get(column, f"raw__{column}")
        for column in frame.columns
        if column != "_row_id"
    }
    frame = frame.rename(columns=rename)
    frame["_source_sheet"] = mapping.sheet
    before = frame.copy()
    numeric_fields = {"sales_amount", "sales_quantity", "purchase_amount", "cost", "discount", "unit_price"}
    issues = []
    for column in numeric_fields & set(frame.columns):
        converted = []
        for index, value in frame[column].items():
            try:
                converted.append(number(value, policy))
            except ValueError:
                issues.append(
                    {"row": int(frame.at[index, "_row_id"]), "column": column, "issue": "invalid_numeric"}
                )
                converted.append(float("nan"))
        frame[column] = converted
        if frame[column].isna().any() and policy.numeric_nulls == "error":
            raise ValueError(f"Null values in {column}; policy is error.")
        if policy.numeric_nulls == "zero":
            frame[column] = frame[column].fillna(0)
    dates = []
    for index, value in frame["transaction_date"].items():
        try:
            dates.append(parse_date(value, mapping))
        except (ValueError, TypeError, OverflowError):
            issues.append(
                {
                    "row": int(frame.at[index, "_row_id"]),
                    "column": "transaction_date",
                    "issue": "invalid_date",
                }
            )
            dates.append(pd.NaT)
    if issues and policy.invalid_values == "error":
        raise ValueError(f"{len(issues)} invalid values. First issues: {issues[:5]}")
    frame["transaction_date"] = pd.to_datetime(dates)
    if "currency" in frame:
        currencies = frame["currency"].dropna().unique().tolist()
        if frame["currency"].isna().any() or currencies != [mapping.currency]:
            raise ValueError("Mixed, missing or mismatched currencies require explicit upstream conversion.")
    duplicate_columns = [column for column in frame if not column.startswith("_")]
    duplicates = frame.duplicated(subset=duplicate_columns)
    duplicate_count = int(duplicates.sum())
    removed = []
    if policy.duplicates == "drop_exact":
        removed = frame.loc[duplicates, "_row_id"].astype(int).tolist()
        frame = frame.loc[~duplicates].copy()
    if mapping.grain == "order" and "order_id" in frame:
        ids = frame["order_id"].dropna()
        if ids.duplicated().any():
            raise ValueError("Repeated order IDs contradict the confirmed one-row-per-order grain.")
    if mapping.sales_basis == "gross_before_discount":
        frame["_net_sales"] = frame["sales_amount"] - frame["discount"]
    else:
        frame["_net_sales"] = frame["sales_amount"]
    if mapping.cost_basis != "unavailable":
        frame["_total_cost"] = (
            frame["cost"] * frame["sales_quantity"] if mapping.cost_basis == "per_unit" else frame["cost"]
        )
        frame["_profit"] = frame["_net_sales"] - frame["_total_cost"]
    version_name = f"cleaned_{uuid4().hex}"
    directory = store.directory(dataset_id)
    path = directory / f"{version_name}.parquet"
    frame.to_parquet(path, index=False)
    changes = []
    for column in (numeric_fields | {"transaction_date"}) & set(before.columns):
        for index in frame.index:
            old, new = before.at[index, column], frame.at[index, column]
            old_text = None if pd.isna(old) else str(old)
            new_text = None if pd.isna(new) else str(new)
            if old_text != new_text:
                changes.append(
                    {
                        "row": int(frame.at[index, "_row_id"]),
                        "column": column,
                        "before": old_text,
                        "after": new_text,
                    }
                )
    report = {
        "rows_before": len(before),
        "rows_after": len(frame),
        "duplicates_found": duplicate_count,
        "removed_source_rows": removed,
        "issues": issues,
        "policy": policy.model_dump(),
        "changed_cells": len(changes),
        "nulls": {c: int(frame[c].isna().sum()) for c in frame.columns},
        "sales_definition": mapping.sales_definition,
    }
    atomic_json(directory / f"{version_name}_changes.json", changes)
    atomic_json(directory / f"{version_name}_quality.json", report)
    data["meta"].update(cleaned=path.name, quality=report, state="cleaned", cleaning=policy.model_dump())
    version = store.update(dataset_id, data["meta"], data["version"])
    store.audit(
        dataset_id,
        "cleaning_confirmed",
        {"version": version, "report": report, "changes_file": f"{version_name}_changes.json"},
    )
    return report


def load_clean(store, dataset_id):
    data = store.get(dataset_id)
    if "cleaned" not in data["meta"]:
        raise ValueError("Confirm the mapping and run cleaning before analysis.")
    return pd.read_parquet(store.directory(dataset_id) / data["meta"]["cleaned"]), data
