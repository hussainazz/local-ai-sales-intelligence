import io
from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from sales_intelligence.ingestion import ingest
from sales_intelligence.nlp import evaluate_text_classifier
from sales_intelligence.preparation import clean, save_mapping
from sales_intelligence.schemas import Cleaning, Mapping, TextClassifier


def test_native_excel_dates_work_with_confirmed_date_format(store, settings):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["date", "sales"])
    sheet.append([datetime(2025, 1, 1), 100])
    buffer = io.BytesIO()
    book.save(buffer)
    data = ingest(store, settings, "sales.xlsx", buffer.getvalue())
    save_mapping(
        store,
        data["id"],
        Mapping(
            sheet="Sales",
            columns={"transaction_date": "date", "sales_amount": "sales"},
            grain="order",
            currency="DEMO",
            sales_definition="Net sales excluding tax and shipping.",
            confirmed=True,
        ),
    )
    assert clean(store, data["id"], Cleaning(confirmed=True))["issues"] == []


def test_sentiment_evaluation_requires_existing_reviewed_labels(store, settings):
    dates = pd.date_range("2025-01-01", periods=120)
    rows = [
        {
            "date": date.date().isoformat(),
            "amount": 10,
            "feedback": ("excellent quality happy " if index % 2 else "bad delivery unhappy ")
            + f"reference{index}",
            "sentiment": "positive" if index % 2 else "negative",
        }
        for index, date in enumerate(dates)
    ]
    data = ingest(store, settings, "labeled.csv", pd.DataFrame(rows).to_csv(index=False).encode())
    save_mapping(
        store,
        data["id"],
        Mapping(
            sheet="CSV",
            columns={"transaction_date": "date", "sales_amount": "amount", "text": "feedback"},
            grain="order",
            currency="DEMO",
            sales_definition="Fictional net amounts for a text classification test.",
            confirmed=True,
        ),
    )
    clean(store, data["id"], Cleaning(confirmed=True))
    request = TextClassifier(
        purpose="sentiment",
        label_column="raw__sentiment",
        label_definition="Synthetic fixture sentiment, not a domain evaluation.",
        permitted_labels=["positive", "negative"],
    )
    with pytest.raises(ValueError, match="review"):
        evaluate_text_classifier(store, data["id"], request)
    request.labeling_reviewed = True
    result = evaluate_text_classifier(store, data["id"], request)
    assert result["test_rows"] >= 20
    assert result["f1_macro"] > result["baseline_f1_macro"]
    assert result["evaluation_deduplicated_texts"] is True
