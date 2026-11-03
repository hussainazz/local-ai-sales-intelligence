import json
from pathlib import Path

import pytest

from sales_intelligence.agents import run_agent
from sales_intelligence.config import Settings
from sales_intelligence.ingestion import ingest
from sales_intelligence.ml import cluster, forecast, supervised
from sales_intelligence.nlp import text_analysis
from sales_intelligence.preparation import clean, save_mapping
from sales_intelligence.rag import add_document, retrieve
from sales_intelligence.schemas import Chat, Cleaning, Forecast, Mapping, Supervised
from scripts.make_sample import create_sample


def test_agent_queries_real_data_and_cites_version(store, settings, prepared):
    result = run_agent(store, settings, prepared, Chat(question="Which products sell best?"))
    assert result["selected_tool"] == "products"
    evidence = result["verified_findings"][0]
    assert evidence["values"]["ranking"][0]["net_sales"] == 180
    assert evidence["version"] == store.get(prepared)["version"]
    assert all(
        evidence["id"] in item["evidence_ids"] for item in result["interpretations_and_review_actions"]
    )


def test_agent_does_not_fabricate_churn_or_ignore_relative_dates(store, settings, prepared):
    for question in ["Which customers will churn?", "فروش ماه گذشته چقدر بود؟"]:
        result = run_agent(store, settings, prepared, Chat(question=question))
        assert result["status"] == "needs_clarification_or_data"
        assert result["verified_findings"] == []


def test_agent_rejects_model_invented_evidence_ids(store, settings, prepared, monkeypatch):
    from sales_intelligence.llm import LocalModel
    from sales_intelligence.schemas import Advice, AdviceItem, Route

    monkeypatch.setattr(LocalModel, "route", lambda self, question: (Route(tool="products"), {}))
    monkeypatch.setattr(
        LocalModel,
        "advice",
        lambda self, evidence: (
            Advice(items=[AdviceItem(action="review_product_mix", evidence_ids=["invented-source"])]),
            {},
        ),
    )
    monkeypatch.setattr("sales_intelligence.agents.retrieve", lambda *args: [])
    result = run_agent(store, settings, prepared, Chat(question="Which products sell best?", use_llm=True))
    assert result["verified_findings"]
    assert result["interpretations_and_review_actions"] == []


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com",
        "http://127.0.0.1@evil.example",
        "http://localhost:11434/redirect",
        "http://10.0.0.1",
    ],
)
def test_cloud_model_endpoints_rejected(url):
    with pytest.raises(ValueError):
        Settings(api_key="a" * 32, ollama_url=url, _env_file=None)


def test_no_text_reports_skip(store, prepared):
    assert text_analysis(store, prepared)["status"] == "skipped"


@pytest.fixture
def sample(store, settings, tmp_path):
    frame = create_sample(tmp_path / "fictional")
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
            sales_definition="Fictional net sales excluding tax and shipping.",
            cost_basis="line_total",
            confirmed=True,
        ),
    )
    clean(store, data["id"], Cleaning(confirmed=True))
    return data["id"]


def test_forecast_uses_past_only_and_compares_baseline(store, sample):
    result = forecast(store, sample, Forecast(horizon=7))
    assert len(result["forecast"]) == 7
    assert all(fold["train_end"] < fold["test_start"] for fold in result["folds"])
    assert result["model_mae"] >= 0 and result["baseline_mae"] >= 0
    if result["baseline_mae"] <= result["model_mae"]:
        assert result["model"] == "seasonal_naive_7"


def test_insufficient_data_refuses_ml(store, prepared):
    with pytest.raises(ValueError):
        forecast(store, prepared, Forecast())
    with pytest.raises(ValueError):
        cluster(store, prepared)


def test_supervised_requires_label_definition_and_leakage_review(store, sample):
    request = Supervised(
        task="classification",
        target="raw__risk_label",
        features=["sales_quantity"],
        target_definition="Synthetic demonstration label, never a valid churn label.",
        prediction_horizon="Demonstration only",
    )
    with pytest.raises(ValueError, match="review"):
        supervised(store, sample, request)
    request.leakage_reviewed = True
    request.features = ["raw__risk_label"]
    with pytest.raises(ValueError, match="target"):
        supervised(store, sample, request)


def test_supervised_and_clustering_run_on_fictional_data(store, sample):
    request = Supervised(
        task="classification",
        target="raw__risk_label",
        features=["sales_quantity"],
        target_definition="Synthetic fixture classification, not a real churn target.",
        prediction_horizon="Demonstration only",
        leakage_reviewed=True,
    )
    result = supervised(store, sample, request)
    assert "baseline_f1_macro" in result["metrics"]
    assert cluster(store, sample)["clusters"] >= 2
    assert text_analysis(store, sample)["status"] == "completed"


class FakeEmbeddings:
    class settings:
        embedding_model = "test-local-embedding"

    calls = 0

    def verify_downloaded(self, name):
        return "fixed-fixture-digest"

    def embed(self, texts):
        self.calls += 1
        return [
            [float("bundle" in text.lower()) + 0.01, float("consent" in text.lower()) + 0.01, 0.1]
            for text in texts
        ]


def test_rag_source_attribution_and_embedding_dedup(store, prepared):
    model = FakeEmbeddings()
    body = b"Bundles require manager review. Customer consent is required."
    first = add_document(store, prepared, "../../policy.txt", body, model)
    calls = model.calls
    second = add_document(store, prepared, "policy.txt", body, model)
    assert second["cached"] is True and first["document_id"] == second["document_id"]
    assert model.calls == calls
    result = retrieve(store, prepared, "bundle", model)
    assert result[0]["source"] == "policy.txt" and result[0]["source_id"].endswith(":0")


def test_workflow_graphs_have_no_secrets_and_have_matching_edges():
    for path in (Path(__file__).parents[1] / "workflows").glob("*.json"):
        flow = json.loads(path.read_text())
        names = {node["name"] for node in flow["nodes"]}
        assert flow["active"] is False
        assert all(node["type"] != "n8n-nodes-base.code" for node in flow["nodes"])
        for source, connections in flow["connections"].items():
            assert source in names
            assert all(edge["node"] in names for branch in connections["main"] for edge in branch)
