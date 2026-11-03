import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4


def now():
    return datetime.now(UTC).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str, sort_keys=True)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0, meta TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL, updated TEXT NOT NULL, payload TEXT NOT NULL,
                result TEXT, error TEXT, cancel INTEGER NOT NULL DEFAULT 0,
                UNIQUE(dataset_id, kind, payload));
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL,
                created TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS prompts (
                name TEXT NOT NULL, hash TEXT NOT NULL, content TEXT NOT NULL,
                created TEXT NOT NULL, PRIMARY KEY(name, hash));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "metadata.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def directory(self, dataset_id):
        UUID(dataset_id)
        path = self.root / dataset_id
        if not path.is_dir():
            raise KeyError("Dataset does not exist.")
        return path

    def create(self, meta):
        dataset_id = str(uuid4())
        (self.root / dataset_id).mkdir(mode=0o700)
        with self.db() as db:
            db.execute("INSERT INTO datasets VALUES (?, ?, ?, 0, ?)", (dataset_id, now(), now(), dumps(meta)))
        return dataset_id

    def get(self, dataset_id):
        UUID(dataset_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError("Dataset does not exist.")
        return {**dict(row), "meta": json.loads(row["meta"])}

    def update(self, dataset_id, meta, expected_version):
        with self.db() as db:
            count = db.execute(
                "UPDATE datasets SET meta=?, version=version+1, updated=? WHERE id=? AND version=?",
                (dumps(meta), now(), dataset_id, expected_version),
            ).rowcount
        if not count:
            raise ValueError("Dataset changed. Refresh before applying this operation.")
        return expected_version + 1

    def audit(self, dataset_id, action, detail):
        with self.db() as db:
            db.execute(
                "INSERT INTO audit(dataset_id,created,action,detail) VALUES (?,?,?,?)",
                (dataset_id, now(), action, dumps(detail)),
            )

    def cache_path(self, dataset_id, kind, parameters, version=None):
        version = self.get(dataset_id)["version"] if version is None else version
        key = hashlib.sha256(
            dumps(
                {
                    "version": version,
                    "parameters": parameters,
                    "analysis_version": "0.1.0",
                    "kind": kind,
                }
            ).encode()
        ).hexdigest()
        directory = self.directory(dataset_id) / "cache"
        directory.mkdir(exist_ok=True)
        return directory / f"{key}.json"

    def task(self, task_id):
        UUID(task_id)
        with self.db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("Task does not exist.")
        result = dict(row)
        for key in ["payload", "result"]:
            result[key] = json.loads(result[key]) if result[key] else None
        return result
