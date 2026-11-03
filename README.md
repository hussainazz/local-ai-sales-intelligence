# Local AI Sales Intelligence

A local sales-analysis application with a FastAPI backend, React/Plotly dashboard, LangGraph agent, local Ollama integration and importable n8n workflows. The complete source is also provided as Jupyter code cells in ten chapters.

Start with **[the complete notebook](notebooks/00_Local_AI_Sales_Intelligence.ipynb)**. Use [the chapter index](notebooks/README.md) to work through one topic at a time. Each chapter includes its full source files, a runnable example and a review checkpoint. Writing cells reconstruct a separate `notebook_project/` copy; they preserve the supplied source. Examples import the supplied package.

## Install and open Jupyter

Python 3.12–3.14 and Node.js 24 are supported. This checkout was validated with Python 3.13. The commands below work in Fish and Bash because they do not depend on shell activation.

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock.txt
uv pip install --python .venv/bin/python --no-deps -e .
.venv/bin/python scripts/bootstrap.py
.venv/bin/python scripts/make_sample.py
.venv/bin/python -m jupyterlab notebooks/00_Local_AI_Sales_Intelligence.ipynb
```

If uv is unavailable, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements-dev.lock.txt` and `.venv/bin/python -m pip install --no-deps -e .`. The locks record the validated Linux/Python 3.13 environment; on another platform or interpreter resolve from `pyproject.toml` with `.venv/bin/python -m pip install -e '.[dev]'`. On Windows, replace `.venv/bin/python` with `.venv/Scripts/python.exe`.

`bootstrap.py` creates a private `.env`, preserves an existing one and does not print secrets. The notebook examples use separate fictional credentials and data. Do not upload company data to a hosted notebook service. Initial package, image and model downloads require internet; runtime data processing uses local services.

## Run the native application

In the first terminal, from this directory:

```sh
.venv/bin/python scripts/serve.py
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open [the local dashboard](http://127.0.0.1:5173). Copy the value of `SALES_API_KEY` from your local `.env` into its password field. The page keeps it only in memory. Upload `sample_data/sales.xlsx` or your own file, map the columns, describe what sales amounts mean, confirm the mapping, and approve the cleaning policy. Then calculate a dashboard or ask a question. Use the date filters for questions such as “last month.”

For the fictional sample, use `Sales`, one product per order row, currency `DEMO`, dates `%Y-%m-%d`, net sales after discount and line-total costs. Map `feedback` to text. Do not map the synthetic `risk_label` as a business outcome.

The local application works without an LLM. Its fallback recognises a limited set of Persian/English sales intents. Set `SALES_USE_LLM=true` only after setting up local Ollama. Supervised model evaluation and retrieval evaluation are available through Python/API and the notebooks. The dashboard provides the common analysis, forecast, clustering, text, document and scenario flows.

## Enable local models

Install Ollama separately. Run its server with cloud features disabled. For Fish:

```fish
env OLLAMA_NO_CLOUD=1 ollama serve
```

Download the configured chat and embedding models in another terminal:

```sh
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

Update `.env` to `SALES_USE_LLM=true`, then restart the API. The application allows only loopback Ollama URLs or the `ollama` Compose service, verifies downloaded model tags, rejects cloud-tagged/remote-backed models and disables LangSmith tracing. Set the cloud-disable option on the Ollama server itself, including an existing server you operate separately. Hardware requirements depend on model quantization and context size; benchmark on your machine before choosing a larger model.

## Run with Docker Compose

```sh
.venv/bin/python scripts/bootstrap.py
docker compose up --build -d
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull nomic-embed-text
```

If enabling the LLM, edit `SALES_USE_LLM` in `.env` and recreate the API with `docker compose up -d api`. All published ports bind to `127.0.0.1`. Open the dashboard on port 5173 and n8n on port 5678. API data, Ollama models and n8n settings have separate persistent volumes. The Python server runs as an unprivileged container user. The native and Compose data stores are separate.

Compose pins n8n and Ollama image tags. Review image compatibility and update them deliberately. The Docker build uses `requirements.lock.txt` for the Python runtime. The frontend uses `package-lock.json` with `npm ci`.

## Import the n8n agent workflows

See [the n8n setup guide](docs/n8n_setup.md). Import:

- `workflows/sales_advisor.json` to submit an analysis question.
- `workflows/task_status.json` to retrieve results and evidence.
- `workflows/daily_report.json` for an optional daily local report submission.

All workflows are inactive. Importing the JSON does not configure credentials, publish a workflow or contact customers. Backend jobs are asynchronous. The submit webhook returns HTTP 202 and a task ID; the status webhook returns the result when ready.

## Validate

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check sales_intelligence scripts tests
.venv/bin/python scripts/verify_notebooks.py
cd frontend
npm run build
```

`verify_notebooks.py` validates all notebooks and executes the master notebook with live model/n8n calls disabled. It uses the current Python environment as the kernel and keeps runtime/cache files inside this project. Run it after installing the dev dependencies. Regenerate notebooks after source changes with `.venv/bin/python scripts/build_notebooks.py`.

Read [the architecture](docs/architecture.md), [the technical report and limits](docs/technical_report.md), [the source references](docs/sources.md) and [the validation record](docs/validation.md).

## Retention

Datasets remain until explicit cleanup. `SALES_RETENTION_DAYS`, default 30, is an inactivity threshold used by the cleanup script. Preview with `.venv/bin/python scripts/cleanup.py`. Add `--apply` only when you intend to delete expired datasets, including originals and history. No destructive cleanup runs automatically. Protect local disks and backups because company files are stored locally without application-level encryption.
