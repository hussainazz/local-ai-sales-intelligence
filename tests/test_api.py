import time

from fastapi.testclient import TestClient

from sales_intelligence.api import create_app


def test_auth_and_path_validation(settings):
    app = create_app(settings)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/jobs/not-a-uuid", headers={"X-API-Key": settings.api_key}).status_code == 422
    assert client.get("/api/health", headers={"X-API-Key": settings.api_key}).status_code == 200


def test_end_to_end_upload_approval_background_analysis_export(settings):
    with TestClient(create_app(settings)) as client:
        client.headers["X-API-Key"] = settings.api_key
        response = client.post(
            "/api/upload",
            files={"file": ("s.csv", b"date,amount,order\n2025-01-01,100,A\n2025-01-02,50,B\n", "text/csv")},
        )
        assert response.status_code == 201, response.text
        dataset_id = response.json()["id"]
        assert client.post("/api/analyze/" + dataset_id, json={}).status_code == 400
        mapping = {
            "sheet": "CSV",
            "columns": {"transaction_date": "date", "sales_amount": "amount", "order_id": "order"},
            "grain": "order",
            "currency": "DEMO",
            "sales_definition": "Net sales excluding tax and shipping.",
            "confirmed": True,
        }
        assert client.post("/api/mapping/" + dataset_id, json=mapping).status_code == 200
        assert client.post("/api/clean/" + dataset_id, json={"confirmed": True}).status_code == 200
        receipt = client.post("/api/analyze/" + dataset_id, json={})
        assert receipt.status_code == 202, receipt.text
        task_id = receipt.json()["task_id"]
        assert client.post("/api/analyze/" + dataset_id, json={}).json()["task_id"] == task_id
        for _ in range(200):
            task = client.get("/api/tasks/" + task_id).json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert task["status"] == "completed", task
        assert task["result"]["output"]["analyses"]["summary"]["result"]["net_sales"] == 150
        assert client.get("/api/dashboard/" + dataset_id).status_code == 200
        assert client.get("/api/export/" + dataset_id + "?format=xlsx").status_code == 200
        assert client.get("/api/audit/" + dataset_id).json()
