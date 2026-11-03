"""Reusable fictional-data setup so every chapter can run independently."""

import tempfile
from pathlib import Path

from sales_intelligence.config import Settings
from sales_intelligence.ingestion import ingest
from sales_intelligence.preparation import clean, save_mapping
from sales_intelligence.schemas import Cleaning, Mapping
from sales_intelligence.store import Store
from scripts.make_sample import create_sample


def make_demo(root):
    directory = Path(root) / "notebook_data"
    directory.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="fictional-", dir=directory))
    settings = Settings(
        api_key="notebook-fictional-only-" + "x" * 32, data_dir=run_dir / "data", _env_file=None
    ).prepare()
    store = Store(settings.data_dir)
    frame = create_sample(run_dir / "sample")
    data = ingest(store, settings, "sales.csv", frame.to_csv(index=False).encode())
    columns = {
        name: name
        for name in [
            "order_id",
            "customer_id",
            "product_id",
            "transaction_date",
            "sales_quantity",
            "sales_amount",
            "cost",
            "discount",
        ]
    }
    columns["text"] = "feedback"
    save_mapping(
        store,
        data["id"],
        Mapping(
            sheet="CSV",
            columns=columns,
            grain="line_item",
            currency="DEMO",
            sales_definition="Fictional net line amounts; no tax, shipping or returns; demonstration units.",
            cost_basis="line_total",
            confirmed=True,
        ),
    )
    clean(store, data["id"], Cleaning(confirmed=True))
    return store, settings, data["id"], frame
