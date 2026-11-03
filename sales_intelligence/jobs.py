import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from uuid import uuid4

import psutil

from .agents import run_agent
from .analytics import dashboard
from .config import Settings
from .ingestion import atomic_json
from .llm import LocalModel
from .ml import cluster, forecast, supervised
from .nlp import evaluate_text_classifier, text_analysis
from .rag import add_document
from .schemas import Chat, Filters, Forecast, Supervised, TextClassifier
from .store import Store, dumps, now


def set_status(store, task_id, status, progress, result=None, error=None):
    with store.db() as db:
        db.execute(
            "UPDATE tasks SET status=?,progress=?,result=?,error=?,updated=? WHERE id=?",
            (status, progress, dumps(result) if result is not None else None, error, now(), task_id),
        )


def execute_task(root, settings_values, task_id):
    # One worker and one model at a time by default; no external telemetry.
    os.environ["OMP_NUM_THREADS"] = "1"
    settings = Settings.model_validate(settings_values)
    store = Store(root)
    task = store.task(task_id)
    if task["cancel"]:
        set_status(store, task_id, "cancelled", 0)
        return
    payload = task["payload"]
    expected = payload["_dataset_version"]
    if store.get(task["dataset_id"])["version"] != expected:
        set_status(
            store, task_id, "failed", 0, error="Dataset changed before this task started. Submit again."
        )
        return
    set_status(store, task_id, "running", 10)
    started = time.monotonic()
    process = psutil.Process()
    cpu_start = process.cpu_times()
    try:
        kind, dataset_id = task["kind"], task["dataset_id"]
        request = payload["request"]
        if kind == "analyze":
            result = dashboard(store, dataset_id, Filters.model_validate(request))
        elif kind == "chat":
            result = run_agent(store, settings, dataset_id, Chat.model_validate(request), task_id)
        elif kind == "forecast":
            result = forecast(store, dataset_id, Forecast.model_validate(request))
        elif kind == "supervised":
            result = supervised(store, dataset_id, Supervised.model_validate(request))
        elif kind == "cluster":
            result = cluster(store, dataset_id)
        elif kind == "nlp":
            result = text_analysis(store, dataset_id)
        elif kind == "text_classifier":
            result = evaluate_text_classifier(store, dataset_id, TextClassifier.model_validate(request))
        elif kind == "document":
            path = store.directory(dataset_id) / request["staged_file"]
            try:
                result = add_document(
                    store, dataset_id, request["filename"], path.read_bytes(), LocalModel(settings, store)
                )
            finally:
                path.unlink(missing_ok=True)
        elif kind == "recommendations":
            result = run_agent(
                store, settings, dataset_id, Chat(question="خلاصه فروش", use_llm=settings.use_llm), task_id
            )
        else:
            raise ValueError("Unknown task kind.")
        if store.get(dataset_id)["version"] != expected:
            raise ValueError("Dataset changed during this task. Submit again on the current version.")
        if store.task(task_id)["cancel"]:
            set_status(store, task_id, "cancelled", 100)
            return
        if kind == "analyze":
            atomic_json(store.cache_path(dataset_id, "dashboard", request, version=expected), result)
        cpu_end = process.cpu_times()
        metrics = {
            "wall_seconds": time.monotonic() - started,
            "cpu_seconds": cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system,
            "resident_ram_bytes_at_completion": process.memory_info().rss,
        }
        set_status(store, task_id, "completed", 100, {"output": result, "metrics": metrics})
        store.audit(dataset_id, "task_completed", {"task_id": task_id, "kind": kind, "metrics": metrics})
    except Exception as exc:  # noqa: BLE001 - worker exceptions must become a persisted terminal task status
        # Do not expose model prompts, raw records, credentials or parser internals in API errors.
        message = (
            str(exc)[:500]
            if isinstance(exc, ValueError)
            else f"{type(exc).__name__}: task failed; inspect local configuration."
        )
        set_status(store, task_id, "failed", 100, error=message)


class JobQueue:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.pool = ProcessPoolExecutor(
            max_workers=settings.workers, mp_context=multiprocessing.get_context("spawn")
        )

    def enqueue(self, dataset_id, kind, request):
        data = self.store.get(dataset_id)
        if "cleaned" not in data["meta"]:
            raise ValueError("Confirm mapping and cleaning before submitting analysis jobs.")
        payload = dumps({"request": request, "_dataset_version": data["version"]})
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,status FROM tasks WHERE dataset_id=? AND kind=? AND payload=?",
                (dataset_id, kind, payload),
            ).fetchone()
            if existing:
                return self.store.task(existing["id"])
            count = db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[
                0
            ]
            if count >= 16:
                raise ValueError("Local task queue is full. Wait for an existing task to finish.")
            task_id = str(uuid4())
            db.execute(
                "INSERT INTO tasks(id,dataset_id,kind,status,created,updated,payload) VALUES (?,?,?,'queued',?,?,?)",
                (task_id, dataset_id, kind, now(), now(), payload),
            )
        self.pool.submit(execute_task, str(self.store.root), self.settings.model_dump(mode="json"), task_id)
        return self.store.task(task_id)

    def retry(self, task_id):
        task = self.store.task(task_id)
        if task["status"] not in {"failed", "cancelled"} or task["kind"] == "document":
            raise ValueError("Only failed/cancelled analysis tasks can be retried. Upload documents again.")
        if self.store.get(task["dataset_id"])["version"] != task["payload"]["_dataset_version"]:
            raise ValueError("Dataset changed; create a new request.")
        # At most one explicit retry per task, tracked by an audit event.
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT COUNT(*) FROM audit WHERE action='task_retry' AND detail=?",
                (dumps({"task_id": task_id}),),
            ).fetchone()[0]
            if prior:
                raise ValueError("Retry limit reached. Correct the cause and change the request.")
            db.execute(
                "UPDATE tasks SET status='queued',cancel=0,error=NULL,progress=0 WHERE id=?", (task_id,)
            )
            db.execute(
                "INSERT INTO audit(dataset_id,created,action,detail) VALUES (?,?,?,?)",
                (task["dataset_id"], now(), "task_retry", dumps({"task_id": task_id})),
            )
        self.pool.submit(execute_task, str(self.store.root), self.settings.model_dump(mode="json"), task_id)
        return self.store.task(task_id)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=False)
