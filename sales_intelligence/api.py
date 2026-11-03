import hmac
import json
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .ingestion import ingest
from .jobs import JobQueue
from .preparation import clean, inspect, load_clean, save_mapping, save_relationship
from .reporting import export, simulate
from .schemas import (
    Chat,
    Cleaning,
    Filters,
    Forecast,
    Mapping,
    Relationship,
    Simulation,
    Supervised,
    TextClassifier,
)
from .store import Store, now


def create_app(settings=None):
    settings = (settings or Settings()).prepare()
    store = Store(settings.data_dir)
    queue = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal queue
        with store.db() as db:
            db.execute(
                "UPDATE tasks SET status='failed',error='API restarted. Retry explicitly.',updated=? WHERE status IN ('queued','running')",
                (now(),),
            )
        queue = JobQueue(store, settings)
        yield
        queue.close()

    app = FastAPI(
        title="Local AI Sales Intelligence",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    def authorize(x_api_key: Annotated[str | None, Header()] = None):
        if x_api_key is None or not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(401, "A valid X-API-Key is required.")

    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)[:1000]})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Dataset or task not found."})

    @router.get("/health")
    def health():
        return {"status": "ok", "local_llm_enabled": settings.use_llm, "single_company": True}

    @router.post("/upload", status_code=201)
    async def upload(file: Annotated[UploadFile, File()]):
        try:
            body = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
            return await run_in_threadpool(ingest, store, settings, file.filename or "upload", body)
        finally:
            await file.close()

    @router.get("/jobs/{job_id}")
    def dataset(job_id: UUID):
        return store.get(str(job_id))

    @router.get("/sheets/{job_id}")
    def sheets(job_id: UUID):
        return store.get(str(job_id))["meta"]["sheets"]

    @router.get("/schema/{job_id}")
    def schema(job_id: UUID):
        return inspect(store, str(job_id))

    @router.post("/mapping/{job_id}")
    def mapping(job_id: UUID, request: Mapping):
        return save_mapping(store, str(job_id), request)

    @router.post("/relationships/{job_id}")
    def relationships(job_id: UUID, request: Relationship):
        return save_relationship(store, str(job_id), request)

    @router.post("/clean/{job_id}")
    def cleaning(job_id: UUID, request: Cleaning):
        return clean(store, str(job_id), request)

    def enqueue(job_id, kind, request):
        if queue is None:
            raise HTTPException(503, "Start the API with its lifespan enabled.")
        task = queue.enqueue(str(job_id), kind, request)
        return {
            "task_id": task["id"],
            "dataset_id": str(job_id),
            "status": task["status"],
            "status_url": f"/api/tasks/{task['id']}",
        }

    @router.post("/analyze/{job_id}", status_code=202)
    def analysis(job_id: UUID, filters: Filters):
        return enqueue(job_id, "analyze", filters.model_dump())

    @router.get("/dashboard/{job_id}")
    def get_dashboard(job_id: UUID, filters: Annotated[Filters, Query()]):
        # Return a completed dashboard artifact; CPU-heavy generation is submitted with /analyze.
        path = store.cache_path(str(job_id), "dashboard", filters.model_dump())
        if path.exists():
            return json.loads(path.read_text())
        raise HTTPException(409, "Submit POST /api/analyze/{dataset_id} and retrieve the task output.")

    @router.post("/chat/{job_id}", status_code=202)
    def chat(job_id: UUID, request: Chat):
        return enqueue(job_id, "chat", request.model_dump())

    @router.get("/recommendations/{job_id}", status_code=202)
    def recommendations(job_id: UUID):
        return enqueue(job_id, "recommendations", {})

    @router.post("/ml/forecast/{job_id}", status_code=202)
    def predict(job_id: UUID, request: Forecast):
        return enqueue(job_id, "forecast", request.model_dump())

    @router.post("/ml/supervised/{job_id}", status_code=202)
    def train(job_id: UUID, request: Supervised):
        return enqueue(job_id, "supervised", request.model_dump())

    @router.post("/ml/cluster/{job_id}", status_code=202)
    def clustering(job_id: UUID):
        return enqueue(job_id, "cluster", {})

    @router.post("/nlp/{job_id}", status_code=202)
    def nlp(job_id: UUID):
        return enqueue(job_id, "nlp", {})

    @router.post("/nlp/classifier/{job_id}", status_code=202)
    def text_classifier(job_id: UUID, request: TextClassifier):
        return enqueue(job_id, "text_classifier", request.model_dump())

    @router.post("/rag/documents/{job_id}", status_code=202)
    async def document(job_id: UUID, file: Annotated[UploadFile, File()]):
        if not settings.use_llm:
            raise HTTPException(409, "Enable local models and download the embedding model first.")
        directory = store.directory(str(job_id))
        staged = f"document_upload_{uuid4().hex}.tmp"
        path = directory / staged
        try:
            body = await file.read(10 * 1024 * 1024 + 1)
            if len(body) > 10 * 1024 * 1024 or not body:
                raise ValueError("Document exceeds the 10 MB limit or is empty.")
            path.write_bytes(body)
            return enqueue(
                job_id, "document", {"staged_file": staged, "filename": file.filename or "document.txt"}
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @router.post("/simulation/{job_id}")
    def scenario(job_id: UUID, request: Simulation):
        return simulate(store, str(job_id), request)

    @router.get("/export/{job_id}")
    def download(job_id: UUID, format: str = "json"):
        content, mime, name = export(store, str(job_id), format)
        return Response(
            content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )

    @router.get("/preview/{job_id}")
    def preview(job_id: UUID, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
        frame, _ = load_clean(store, str(job_id))
        return {
            "total": len(frame),
            "offset": offset,
            "rows": json.loads(
                frame.iloc[offset : offset + limit].to_json(orient="records", date_format="iso")
            ),
        }

    @router.get("/tasks/{task_id}")
    def task(task_id: UUID):
        task = store.task(str(task_id))
        task.pop("payload", None)
        return task

    @router.post("/tasks/{task_id}/cancel")
    def cancel(task_id: UUID):
        task = store.task(str(task_id))
        if task["status"] in {"completed", "failed", "cancelled"}:
            return {"status": task["status"]}
        with store.db() as db:
            db.execute("UPDATE tasks SET cancel=1,updated=? WHERE id=?", (now(), str(task_id)))
        return {
            "status": "cancellation_requested",
            "note": "Cooperative cancellation takes effect at a task boundary.",
        }

    @router.post("/tasks/{task_id}/retry", status_code=202)
    def retry(task_id: UUID):
        if queue is None:
            raise HTTPException(503, "Job queue is unavailable.")
        return queue.retry(str(task_id))

    @router.get("/audit/{job_id}")
    def audit(job_id: UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        store.get(str(job_id))
        with store.db() as db:
            rows = db.execute(
                "SELECT * FROM audit WHERE dataset_id=? ORDER BY id LIMIT ? OFFSET ?",
                (str(job_id), limit, offset),
            ).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]

    app.include_router(router)
    return app
