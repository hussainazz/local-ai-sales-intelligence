# Set up the local n8n workflows

## Start services

Run `scripts/bootstrap.py`, then start the stack with `docker compose up --build -d`. Open [n8n](http://127.0.0.1:5678) and create its owner account. The application does not create an n8n login for you.

Import each JSON in `workflows/` through n8n's workflow import menu. The imports contain credential references named below; replace those references with credentials created in your own n8n instance. The IDs in the JSON are intentionally nonfunctional placeholders, not real credentials.

## Create two Header Auth credentials

1. Name one `Sales backend API`. Its header name is `X-API-Key`; its value is `SALES_API_KEY` from the private project `.env`. Assign it to each HTTP Request node.
2. Name the other `Sales webhook access`. Its header name is `X-Webhook-Key`; use a new random secret, different from the backend key. Assign it to both Webhook nodes.

Store these through n8n's credential UI. Do not paste secrets into expressions, JSON exports, chat messages or notebooks.

## Check local API URLs

Compose workflows use `http://api:8000`, which is the backend's container-network name. If n8n and the API both run natively, edit HTTP Request node URL origins to `http://127.0.0.1:8000`. If only n8n runs in Docker, configure a host-gateway route deliberately; container localhost points at n8n itself.

The request path uses `encodeURIComponent` for the dataset/task ID. The host is fixed and cannot be selected by webhook input. The backend validates UUIDs, request fields and preparation approvals.

## Prepare a dataset

Use the React dashboard to upload data and confirm its mapping and cleaning policy. Keep the dataset UUID shown by the dashboard. Notebook examples use a separate temporary dataset store, so their UUIDs do not refer to the API's store.

## Submit a question

Use the test URL while the Webhook node is listening. After configuring credentials, publish both the question and status workflows to enable the production URLs. In a Python notebook or script:

```python
import getpass
import time
import httpx

headers = {"X-Webhook-Key": getpass.getpass("n8n webhook key: ")}
dataset_id = input("Prepared dataset UUID: ").strip()
with httpx.Client(base_url="http://127.0.0.1:5678", trust_env=False, timeout=20) as client:
    response = client.post("/webhook/sales-advisor", headers=headers, json={
        "dataset_id": dataset_id,
        "question": "کدام محصولات بیشترین فروش را دارند؟",
        "filters": {},
        "use_llm": False,
    })
    response.raise_for_status()
    receipt = response.json()
    print("Task:", receipt["task_id"])
    for _ in range(300):
        response = client.get("/webhook/sales-status", headers=headers,
                              params={"task_id": receipt["task_id"]})
        response.raise_for_status()
        task = response.json()
        if task["status"] in {"completed", "failed", "cancelled"}:
            print(task)
            break
        time.sleep(1)
    else:
        print("Still running; use the task ID to check again later.")
```

The question webhook returns HTTP 202 and a task receipt. The result appears under `result.output` in task status. Verified findings, document excerpts and review suggestions have separate fields. A failed backend request stops the n8n execution; it does not silently turn an error into a successful recommendation. n8n execution payload saving is disabled in the shipped configuration.

## Optional daily report

Open `Local sales advisor - daily dashboard`. Replace `REPLACE_WITH_APPROVED_DATASET_UUID` in `Choose approved dataset`. Confirm the `Sales backend API` credential and the Asia/Tehran schedule, which is 08:00 daily. Publish only when you want scheduled execution. It queues a dashboard job and returns its receipt. It does not send emails, Telegram messages or other external notifications.

Because repeated requests with identical version/parameters reuse the existing result, the scheduled flow does not retrain or recalculate unchanged data unnecessarily. A newly uploaded dataset gets a new UUID; update the selected dataset deliberately. No directory watcher or unattended import is configured.

## Verify in your instance

Confirm the expected node types resolve, a sample question returns 202, the status workflow reaches `completed`, a bad webhook key is denied, and an invalid dataset does not produce a report. These checks require a running n8n instance. The repository's automated tests validate graph connections and the backend contract; they do not prove an n8n import or a live Ollama invocation succeeded.
