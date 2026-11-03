import pytest

from sales_intelligence.config import Settings
from sales_intelligence.ingestion import ingest
from sales_intelligence.preparation import clean, save_mapping
from sales_intelligence.schemas import Cleaning, Mapping
from sales_intelligence.store import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(api_key="test-only-" + "a" * 32, data_dir=tmp_path, _env_file=None).prepare()


@pytest.fixture
def store(settings):
    return Store(settings.data_dir)


@pytest.fixture
def prepared(store, settings):
    body = b"order_id,customer_id,product_id,transaction_date,sales_quantity,sales_amount,cost\nO1,C1,P1,2025-01-01,2,100,60\nO1,C1,P2,2025-01-01,1,50,30\nO2,C2,P1,2025-01-02,1,80,40\nO3,,P2,2025-01-03,1,20,10\n"
    dataset = ingest(store, settings, "sales.csv", body)
    dataset_id = dataset["id"]
    columns = [
        "order_id",
        "customer_id",
        "product_id",
        "transaction_date",
        "sales_quantity",
        "sales_amount",
        "cost",
    ]
    save_mapping(
        store,
        dataset_id,
        Mapping(
            sheet="CSV",
            columns={c: c for c in columns},
            grain="line_item",
            currency="DEMO",
            sales_definition="Net amounts after discounts, excluding tax and shipping.",
            cost_basis="line_total",
            confirmed=True,
        ),
    )
    clean(store, dataset_id, Cleaning(confirmed=True))
    return dataset_id
