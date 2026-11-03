"""Measure the same fictional workload locally; do not infer production performance."""

import json
import threading
import time
from pathlib import Path

import psutil

from sales_intelligence.analytics import dashboard
from sales_intelligence.ml import forecast
from sales_intelligence.schemas import Forecast
from scripts.notebook_demo import make_demo

ROOT = Path(__file__).resolve().parents[1]


def main():
    process = psutil.Process()
    peak = [process.memory_info().rss]
    done = threading.Event()

    def sample():
        while not done.wait(0.02):
            peak[0] = max(peak[0], process.memory_info().rss)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    durations = {}
    start = time.perf_counter()
    store, _settings, dataset_id, frame = make_demo(ROOT)
    durations["ingestion_mapping_cleaning_seconds"] = time.perf_counter() - start
    for name, operation in [
        ("analysis_dashboard", lambda: dashboard(store, dataset_id)),
        ("forecast_training_validation", lambda: forecast(store, dataset_id, Forecast(horizon=7))),
    ]:
        start = time.perf_counter()
        operation()
        durations[name + "_seconds"] = time.perf_counter() - start
    done.set()
    thread.join()
    result = {
        "fictional_rows": len(frame),
        "durations": durations,
        "sampled_peak_rss_bytes": peak[0],
        "logical_cpus": psutil.cpu_count(),
        "cpu_times": process.cpu_times()._asdict(),
        "not_measured": ["LLM latency", "live n8n execution", "production workload"],
        "note": "Observed RSS sampled every 20 ms; may miss shorter spikes. Fixture generation is included in preparation timing.",
    }
    (ROOT / ".cache").mkdir(exist_ok=True)
    (ROOT / ".cache/benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
