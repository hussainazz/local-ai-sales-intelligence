import io
import json
import zipfile

import openpyxl
import pandas as pd
import pytest

from sales_intelligence.analytics import analyze, dashboard
from sales_intelligence.ingestion import check_archive, ingest
from sales_intelligence.preparation import clean, load_clean, number, save_mapping, save_relationship
from sales_intelligence.reporting import export, simulate
from sales_intelligence.schemas import Cleaning, Filters, Mapping, Relationship, Simulation


def test_verified_totals_and_order_grain(store, prepared):
    result = analyze(store, prepared)["result"]
    assert result["net_sales"] == 250
    assert result["orders"] == 3
    assert result["average_order_value"] == pytest.approx(250 / 3)
    assert result["profit"] == 110
    assert analyze(store, prepared, "products")["result"]["ranking"][0]["net_sales"] == 180


def test_filters_change_real_query(store, prepared):
    result = analyze(store, prepared, filters=Filters(start="2025-01-02", end="2025-01-02"))
    assert result["result"]["net_sales"] == 80
    assert result["filters"]["start"] == "2025-01-02"
    with pytest.raises(ValueError, match="No rows"):
        analyze(store, prepared, filters=Filters(customer_id="UNKNOWN"))


def test_null_ids_preserved_and_quality_reported(store, prepared):
    frame, data = load_clean(store, prepared)
    assert pd.isna(frame.iloc[-1].customer_id)
    assert data["meta"]["quality"]["nulls"]["customer_id"] == 1
    assert analyze(store, prepared, "customers")["result"]["excluded_rows"] == 1
    assert (store.directory(prepared) / "original.csv").exists()
    changes = list(store.directory(prepared).glob("*_changes.json"))
    assert changes and json.loads(changes[0].read_text())


def test_mapping_requires_human_confirmation():
    with pytest.raises(ValueError, match="person"):
        Mapping(
            sheet="CSV",
            columns={},
            grain="order",
            currency="IRT",
            sales_definition="Net sales after discount.",
        )


def test_purchase_amount_not_automatically_sales(store, settings):
    dataset = ingest(store, settings, "p.csv", b"date,purchase_amount\n2025-01-01,100\n")
    from sales_intelligence.preparation import inspect

    assert "sales_amount" not in inspect(store, dataset["id"])["sheets"]["CSV"]["mapping_suggestions"]


@pytest.mark.parametrize("text,expected", [("۱٬۲۳۴٫۵", 1234.5), ("۱۲۳", 123), ("-۱۲", -12)])
def test_persian_numbers(text, expected):
    assert number(text, Cleaning(thousands_separator="٬", confirmed=True)) == expected


def test_ambiguous_number_rejected():
    with pytest.raises(ValueError):
        number("12,34", Cleaning(confirmed=True))


def test_jalali_date_and_exact_duplicates(store, settings):
    dataset = ingest(
        store, settings, "p.csv", "date,amount,id\n۱۴۰۴/۰۱/۰۱,۱۰۰,001\n۱۴۰۴/۰۱/۰۱,۱۰۰,001\n".encode()
    )
    save_mapping(
        store,
        dataset["id"],
        Mapping(
            sheet="CSV",
            columns={"transaction_date": "date", "sales_amount": "amount", "customer_id": "id"},
            grain="line_item",
            currency="IRT",
            sales_definition="Net sales, tax and shipping excluded.",
            date_calendar="jalali",
            date_format="%Y/%m/%d",
            confirmed=True,
        ),
    )
    report = clean(store, dataset["id"], Cleaning(duplicates="drop_exact", confirmed=True))
    frame, _ = load_clean(store, dataset["id"])
    assert report["rows_before"] == 2 and report["rows_after"] == 1
    assert report["removed_source_rows"] == [3]
    assert frame.iloc[0].customer_id == "001"
    assert str(frame.iloc[0].transaction_date.date()) == "2025-03-21"


def test_duplicate_headers_are_not_silently_renamed(store, settings):
    with pytest.raises(ValueError, match="Duplicate column"):
        ingest(store, settings, "p.csv", b"date,date\n1,2\n")


def workbook_bytes(sales, dimensions):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        sales.to_excel(writer, sheet_name="Sales", index=False)
        dimensions.to_excel(writer, sheet_name="Products", index=False)
    return output.getvalue()


def test_many_to_many_join_rejected(store, settings):
    body = workbook_bytes(
        pd.DataFrame({"date": ["2025-01-01"], "amount": [100], "sku": ["P1"]}),
        pd.DataFrame({"key": ["P1", "P1"], "category": ["A", "B"]}),
    )
    dataset = ingest(store, settings, "sales.xlsx", body)
    save_mapping(
        store,
        dataset["id"],
        Mapping(
            sheet="Sales",
            columns={"transaction_date": "date", "sales_amount": "amount", "product_id": "sku"},
            grain="line_item",
            currency="DEMO",
            sales_definition="Net after discounts and tax excluded.",
            confirmed=True,
        ),
    )
    with pytest.raises(ValueError, match="double counting"):
        save_relationship(
            store,
            dataset["id"],
            Relationship(
                sheet="Products", left_on="sku", right_on="key", columns=["category"], confirmed=True
            ),
        )


def test_join_preserves_sales_and_all_sheets(store, settings):
    body = workbook_bytes(
        pd.DataFrame({"date": ["2025-01-01", "2025-01-01"], "amount": [100, 50], "sku": ["P1", "P1"]}),
        pd.DataFrame({"key": ["P1"], "category": ["A"]}),
    )
    dataset = ingest(store, settings, "../../sales.xlsx", body)
    assert set(dataset["meta"]["sheets"]) == {"Sales", "Products"}
    save_mapping(
        store,
        dataset["id"],
        Mapping(
            sheet="Sales",
            columns={"transaction_date": "date", "sales_amount": "amount", "product_id": "sku"},
            grain="line_item",
            currency="DEMO",
            sales_definition="Net after discounts and tax excluded.",
            confirmed=True,
        ),
    )
    save_relationship(
        store,
        dataset["id"],
        Relationship(sheet="Products", left_on="sku", right_on="key", columns=["category"], confirmed=True),
    )
    clean(store, dataset["id"], Cleaning(confirmed=True))
    assert analyze(store, dataset["id"])["result"]["net_sales"] == 150


def test_workbook_formulas_rejected(store, settings):
    output = io.BytesIO()
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["date", "amount"])
    sheet.append(["2025-01-01", "=1+1"])
    book.save(output)
    with pytest.raises(ValueError, match="formulas"):
        ingest(store, settings, "bad.xlsx", output.getvalue())


@pytest.mark.parametrize("name", ["../escape", "/absolute", "xl/vbaProject.bin", "xl/externalLinks/link.xml"])
def test_unsafe_archive_entries(name):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(ValueError):
        check_archive(output.getvalue())


def test_missing_sales_are_not_zero_and_incomplete_order_excluded(store, settings):
    data = ingest(
        store, settings, "x.csv", b"date,amount,order\n2025-01-01,10,A\n2025-01-01,,A\n2025-01-02,20,B\n"
    )
    save_mapping(
        store,
        data["id"],
        Mapping(
            sheet="CSV",
            columns={"transaction_date": "date", "sales_amount": "amount", "order_id": "order"},
            grain="line_item",
            currency="DEMO",
            sales_definition="Net sales after monetary discounts.",
            confirmed=True,
        ),
    )
    clean(store, data["id"], Cleaning(confirmed=True))
    result = analyze(store, data["id"])["result"]
    assert result["sales_rows_missing"] == 1 and result["average_order_value"] == 20
    assert result["incomplete_orders"] == 1


def test_gross_discount_and_per_unit_cost(store, settings):
    data = ingest(store, settings, "x.csv", b"date,amount,discount,cost,qty\n2025-01-01,100,10,20,2\n")
    save_mapping(
        store,
        data["id"],
        Mapping(
            sheet="CSV",
            columns={
                "transaction_date": "date",
                "sales_amount": "amount",
                "discount": "discount",
                "cost": "cost",
                "sales_quantity": "qty",
            },
            grain="line_item",
            currency="DEMO",
            sales_definition="Gross before monetary discount, no tax.",
            sales_basis="gross_before_discount",
            cost_basis="per_unit",
            confirmed=True,
        ),
    )
    clean(store, data["id"], Cleaning(confirmed=True))
    assert analyze(store, data["id"])["result"]["net_sales"] == 90
    assert analyze(store, data["id"])["result"]["profit"] == 50


def test_cache_changes_with_dataset_version(store, prepared):
    first = store.cache_path(prepared, "summary", {})
    clean(store, prepared, Cleaning(confirmed=True))
    assert first != store.cache_path(prepared, "summary", {})


def test_dashboard_explains_missing_analyses(store, prepared):
    result = dashboard(store, prepared)
    assert len(result["figures"]) == 3
    assert "basket" in result["unavailable"]


def test_export_neutralizes_spreadsheet_formula(store, prepared):
    frame, data = load_clean(store, prepared)
    frame.loc[0, "customer_id"] = "=1+1"
    frame.to_parquet(store.directory(prepared) / data["meta"]["cleaned"], index=False)
    body, _, _ = export(store, prepared, "csv")
    assert "'=1+1" in body.decode("utf-8-sig")
    xlsx, _, _ = export(store, prepared, "xlsx")
    book = openpyxl.load_workbook(io.BytesIO(xlsx))
    assert all(cell.data_type != "f" for row in book["Cleaned"] for cell in row)


def test_scenario_is_explicit_arithmetic(store, prepared):
    with pytest.raises(ValueError, match="Confirm"):
        simulate(store, prepared, Simulation(price_change=0.1))
    result = simulate(store, prepared, Simulation(price_change=0.1, assumptions_confirmed=True))
    assert result["hypothetical_net_sales"] == pytest.approx(275)
    assert result["causal_prediction"] is False
