"""Preview or explicitly delete expired datasets. Original files are included only on explicit deletion."""

import argparse
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta

from sales_intelligence.config import Settings
from sales_intelligence.store import Store

parser = argparse.ArgumentParser()
parser.add_argument(
    "--apply", action="store_true", help="Actually delete expired datasets, original files and history"
)
arguments = parser.parse_args()
settings = Settings().prepare()
store = Store(settings.data_dir)
cutoff = (datetime.now(UTC) - timedelta(days=settings.retention_days)).isoformat()
with store.db() as db:
    candidates = db.execute(
        "SELECT id FROM datasets WHERE updated < ? AND id NOT IN (SELECT dataset_id FROM tasks WHERE status IN ('queued','running'))",
        (cutoff,),
    ).fetchall()
    for row in candidates:
        dataset_id = row["id"]
        print(dataset_id, "delete" if arguments.apply else "would expire")
        if arguments.apply:
            checkpoints = store.root / "graph_state.sqlite"
            if checkpoints.exists():
                with sqlite3.connect(checkpoints) as graph_db:
                    for table in ["checkpoints", "writes"]:
                        exists = graph_db.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                        ).fetchone()
                        if exists:
                            graph_db.execute(
                                f"DELETE FROM {table} WHERE thread_id LIKE ?", (dataset_id + ":%",)
                            )
            shutil.rmtree(store.directory(dataset_id))
            db.execute("DELETE FROM audit WHERE dataset_id=?", (dataset_id,))
            db.execute("DELETE FROM tasks WHERE dataset_id=?", (dataset_id,))
            db.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
print(
    "Preview only. Add --apply to delete expired datasets." if not arguments.apply else "Cleanup completed."
)
