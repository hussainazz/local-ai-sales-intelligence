"""Generate importable n8n workflows. No secrets and no executable Code nodes."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]


def node(name, type_name, version, parameters, position, credential=None):
    result = {
        "id": str(uuid5(NAMESPACE_URL, name)),
        "name": name,
        "type": "n8n-nodes-base." + type_name,
        "typeVersion": version,
        "parameters": parameters,
        "position": position,
    }
    if credential:
        result["credentials"] = {"httpHeaderAuth": {"id": "configure-after-import", "name": credential}}
    if type_name == "webhook":
        result["webhookId"] = str(uuid5(NAMESPACE_URL, parameters["path"]))
    return result


def request(name, method, url, position, body=None):
    parameters = {
        "method": method,
        "url": url,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": 15000},
    }
    if body is not None:
        parameters.update(sendBody=True, specifyBody="json", jsonBody=body)
    return node(name, "httpRequest", 4.2, parameters, position, "Sales backend API")


def workflow(name, nodes, edges):
    connections = {}
    for left, right in edges:
        connections[left] = {"main": [[{"node": right, "type": "main", "index": 0}]]}
    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {
            "executionOrder": "v1",
            "timezone": "Asia/Tehran",
            "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none",
            "saveManualExecutions": False,
        },
        "pinData": {},
        "tags": [],
    }


def build():
    directory = ROOT / "workflows"
    directory.mkdir(exist_ok=True)
    nodes = [
        node(
            "Sales question",
            "webhook",
            2,
            {
                "httpMethod": "POST",
                "path": "sales-advisor",
                "authentication": "headerAuth",
                "responseMode": "responseNode",
                "options": {},
            },
            [0, 0],
            "Sales webhook access",
        ),
        request(
            "Submit local agent",
            "POST",
            "={{ 'http://api:8000/api/chat/' + encodeURIComponent($json.body.dataset_id) }}",
            [260, 0],
            "={{ { question: $json.body.question, filters: $json.body.filters ?? {}, use_llm: $json.body.use_llm === true } }}",
        ),
        node(
            "Return task receipt",
            "respondToWebhook",
            1.4,
            {"respondWith": "json", "responseBody": "={{ $json }}", "options": {"responseCode": 202}},
            [520, 0],
        ),
    ]
    chat = workflow(
        "Local sales advisor - submit question",
        nodes,
        [("Sales question", "Submit local agent"), ("Submit local agent", "Return task receipt")],
    )
    nodes = [
        node(
            "Task status",
            "webhook",
            2,
            {
                "httpMethod": "GET",
                "path": "sales-status",
                "authentication": "headerAuth",
                "responseMode": "responseNode",
                "options": {},
            },
            [0, 0],
            "Sales webhook access",
        ),
        request(
            "Read local task",
            "GET",
            "={{ 'http://api:8000/api/tasks/' + encodeURIComponent($json.query.task_id) }}",
            [260, 0],
        ),
        node(
            "Return status and evidence",
            "respondToWebhook",
            1.4,
            {"respondWith": "json", "responseBody": "={{ $json }}", "options": {"responseCode": 200}},
            [520, 0],
        ),
    ]
    status = workflow(
        "Local sales advisor - task status",
        nodes,
        [("Task status", "Read local task"), ("Read local task", "Return status and evidence")],
    )
    nodes = [
        node(
            "Daily local report",
            "scheduleTrigger",
            1.2,
            {"rule": {"interval": [{"field": "cronExpression", "expression": "0 8 * * *"}]}},
            [0, 0],
        ),
        node(
            "Choose approved dataset",
            "set",
            3.4,
            {
                "assignments": {
                    "assignments": [
                        {
                            "id": "dataset",
                            "name": "dataset_id",
                            "type": "string",
                            "value": "REPLACE_WITH_APPROVED_DATASET_UUID",
                        }
                    ]
                },
                "options": {},
            },
            [250, 0],
        ),
        request(
            "Queue dashboard report",
            "POST",
            "={{ 'http://api:8000/api/analyze/' + encodeURIComponent($json.dataset_id) }}",
            [500, 0],
            "={{ {} }}",
        ),
    ]
    schedule = workflow(
        "Local sales advisor - daily dashboard",
        nodes,
        [
            ("Daily local report", "Choose approved dataset"),
            ("Choose approved dataset", "Queue dashboard report"),
        ],
    )
    for filename, value in [
        ("sales_advisor.json", chat),
        ("task_status.json", status),
        ("daily_report.json", schedule),
    ]:
        (directory / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    print(
        "Generated 3 inactive workflows; assign header credentials and verify local API URLs before publishing."
    )


if __name__ == "__main__":
    build()
