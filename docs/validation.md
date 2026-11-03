# Validation record

Checked on 2026-11-03 using Python 3.13.16 and Node.js 24.21.0. Package versions are recorded in the Python and npm lockfiles.

| Check | Result |
|---|---|
| Backend unit/integration tests | 42 passed, including upload, approval, background processing and export through FastAPI |
| Financial and preparation guards | Confirmed totals/AOV/profit, gross discounts, per-unit costs, missing values, duplicate reporting, safe joins, Persian numbers and Jalali/native Excel dates |
| ML and agent guards | Chronological backtests, baseline comparisons, existing-label requirements, evidence/source references, refusal of unsupported questions and invented source IDs |
| Local retrieval | FAISS indexing, retrieval attribution and content-hash deduplication exercised with explicit fixture embeddings |
| Text classification | Existing reviewed labels, chronological evaluation and duplicate-text handling exercised on a clearly synthetic fixture |
| Python lint/format | Ruff checks and format checks passed |
| Notebook files | All 11 notebook schemas valid; master code cells executed without errors using a local kernel, with live model/n8n calls disabled |
| React frontend | TypeScript checks and Vite production build passed |
| Workflow artifacts | Three inactive JSON graphs checked for node connections and backend request structure |
| Compose | YAML structure checked; images were not built or started |

The backend test client and Jupyter kernel required execution outside the restricted tool sandbox because it blocks local asynchronous/network primitives. They completed successfully there. The tests use fictional or temporary data and do not contact a company database.

The initial direct npm download timed out. Dependencies were fetched from the official npm registry through a temporary local cache using Python networking. npm verified package integrity, and the delivered lockfile contains official registry URLs. That temporary cache helper is not part of the application.

The production frontend build reports a large Plotly chunk, about 4.84 MB before gzip and 1.47 MB after gzip. It loads dynamically when charts are displayed. The main application JavaScript is about 243 KB before gzip.

## Measured fictional-data workload

For the generated 1,600-row dataset in this session, a single local benchmark observed approximately 1.42 seconds for sample generation/ingestion/mapping/cleaning, 0.43 seconds for the dashboard analyses and 0.52 seconds for forecast training/validation. Sampled peak process RSS was about 327 MB. These are one-run development measurements, not production guarantees. No live LLM latency or n8n execution latency was measured.

## Not verified live

- Importing/publishing the JSON inside a running n8n instance.
- Ollama model inference, embeddings from a real downloaded model, or hardware suitability for a chosen model.
- Docker image builds, service startup or an activated deployment.
- Real-company label quality, forecasting value, retrieval relevance or commercial effectiveness.
- A browser interaction test of the dashboard. The frontend was checked by TypeScript and production build.

The setup guide describes how to perform the n8n/Ollama integration checks. Those integrations are configuration-dependent and have not been presented as completed.
