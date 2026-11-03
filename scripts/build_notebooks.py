"""Build the teaching notebooks from the exact tested source files."""

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks"

SETUP = """from pathlib import Path
import os, sys, json

ROOT = Path.cwd().resolve()
if ROOT.name == "notebooks":
    ROOT = ROOT.parent
assert (ROOT / "pyproject.toml").exists(), "Open this notebook from the supplied project or its notebooks directory."
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Source-writing cells reconstruct a separate copy and preserve the supplied project.
BUILD_ROOT = ROOT / "notebook_project"
BUILD_ROOT.mkdir(exist_ok=True)
for folder in ["sales_intelligence", "scripts", "tests", "workflows", "frontend/src", "docs"]:
    (BUILD_ROOT / folder).mkdir(parents=True, exist_ok=True)
RUN_LOCAL_MODELS = False  # opt in only after installing local Ollama models
RUN_N8N = False          # opt in only after configuring/publishing the local workflows
print("Python:", sys.version.split()[0])
print("Source reconstruction:", BUILD_ROOT)
"""

DEMO = """if "demo_store" not in globals():
    from scripts.notebook_demo import make_demo
    demo_store, demo_settings, demo_id, sample_frame = make_demo(ROOT)
print("Fictional dataset:", demo_id)
"""

CHAPTERS = [
    (
        1,
        "Foundation",
        "Create the project configuration, SQLite metadata store and bounded file reader. Original files stay separate from parsed and cleaned versions. The supplied implementation targets one local company with an authenticated API.",
        [
            "pyproject.toml",
            ".gitignore",
            ".env.example",
            "sales_intelligence/__init__.py",
            "sales_intelligence/config.py",
            "sales_intelligence/schemas.py",
            "sales_intelligence/store.py",
            "sales_intelligence/ingestion.py",
            "scripts/bootstrap.py",
            "scripts/make_sample.py",
        ],
        """from tempfile import TemporaryDirectory
from sales_intelligence.config import Settings
from sales_intelligence.store import Store
from sales_intelligence.ingestion import ingest
with TemporaryDirectory() as directory:
    settings = Settings(api_key="fictional-notebook-key-" + "x"*32, data_dir=directory, _env_file=None).prepare()
    store = Store(settings.data_dir)
    dataset = ingest(store, settings, "tiny.csv", b"date,amount\\n2025-01-01,100\\n")
    assert dataset["meta"]["sheets"]["CSV"]["rows"] == 1
    print(dataset["meta"])
""",
        "Check that the original file and parsed table exist independently. CSV input is UTF-8. Formula-bearing workbooks are rejected; export calculated values before uploading. Review limits before importing large files.",
    ),
    (
        2,
        "Data intelligence",
        "Inspect every sheet, propose header matches, confirm the meaning of fields, validate a dimension join and record cleaning changes. This chapter uses deterministic mapping suggestions; local AI becomes optional in later chapters.",
        ["sales_intelligence/preparation.py"],
        DEMO
        + """from sales_intelligence.preparation import inspect, load_clean
profile = inspect(demo_store, demo_id)
cleaned, metadata = load_clean(demo_store, demo_id)
assert len(cleaned) == len(sample_frame)
assert metadata["meta"]["quality"]["removed_source_rows"] == []
display(profile)
display(cleaned.head())
""",
        "Human confirmation is required by the Mapping and Cleaning request schemas. Unknown identifiers stay unknown. One many-to-one or one-to-one dimension is supported; many-to-many joins are rejected. Review the change audit and missing-value coverage.",
    ),
    (
        3,
        "Core analytics and dashboard",
        "Calculate net sales, complete-order average value, product/customer rankings, RFM, monthly retention, basket associations, anomalies and correlations. Build Plotly figures from computed values.",
        [
            "sales_intelligence/analytics.py",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/tsconfig.json",
            "frontend/vite.config.ts",
            "frontend/index.html",
            "frontend/src/plotly.d.ts",
            "frontend/src/main.tsx",
            "frontend/src/style.css",
            "frontend/src/App.tsx",
        ],
        DEMO
        + """from sales_intelligence.analytics import analyze, dashboard
from sales_intelligence.schemas import Filters
totals = analyze(demo_store, demo_id)
assert totals["result"]["net_sales"] == float(sample_frame.sales_amount.sum())
display(totals)
charts = dashboard(demo_store, demo_id)
import plotly.graph_objects as go
import plotly.io as pio
from IPython.display import HTML
display(HTML(pio.to_html(go.Figure(charts["figures"][0]), include_plotlyjs=True, full_html=False)))
display(analyze(demo_store, demo_id, "retention")["result"])
""",
        "Check units, filters, date coverage and order grain. Basket rules are associations. Retention uses first purchase observed in the supplied history. The React dashboard runs separately from Jupyter; launch instructions are in README.md.",
    ),
    (
        4,
        "Machine learning",
        "Evaluate a daily forecast against a seasonal baseline using expanding-window, recursive backtests. Run scaled RFM clustering and label-based supervised learning only when their requirements pass.",
        ["sales_intelligence/ml.py"],
        DEMO
        + """from sales_intelligence.ml import forecast, cluster, supervised
from sales_intelligence.schemas import Forecast, Supervised
forecast_result = forecast(demo_store, demo_id, Forecast(horizon=7))
assert all(fold["train_end"] < fold["test_start"] for fold in forecast_result["folds"])
display(forecast_result)
display(cluster(demo_store, demo_id))
# The sample risk label is explicitly synthetic. It demonstrates plumbing, not business validity.
model_result = supervised(demo_store, demo_id, Supervised(
    task="classification", target="raw__risk_label", features=["sales_quantity"],
    target_definition="Synthetic fixture label, never a genuine churn label.",
    prediction_horizon="Demonstration only", leakage_reviewed=True))
display(model_result)
""",
        "Inspect baseline performance before using a model. Forecast bands are exploratory residual bands, not guaranteed intervals. Churn, purchase propensity and CLV require defensible labels/definitions; this project does not invent them.",
    ),
    (
        5,
        "Local LLM engineering",
        "Connect one shared Ollama chat model through LangChain with validated JSON, bounded context, local-only endpoints, timeouts, limited retries and prompt hashes. The model selects tools and evidence-linked actions rather than authoring numbers.",
        ["sales_intelligence/llm.py"],
        DEMO
        + """from sales_intelligence.llm import LocalModel, PROMPTS
model = LocalModel(demo_settings, demo_store)
print("Registered role prompts:", sorted(PROMPTS))
with demo_store.db() as connection:
    print("Versioned prompts:", connection.execute("SELECT COUNT(*) FROM prompts").fetchone()[0])
if RUN_LOCAL_MODELS:
    from sales_intelligence.config import Settings
    local_settings = Settings().prepare()
    assert local_settings.use_llm, "Enable SALES_USE_LLM after downloading the models."
    local_model = LocalModel(local_settings)
    display(local_model.route("Which products have the highest sales?"))
else:
    print("Live model call not run. Enable RUN_LOCAL_MODELS after local Ollama setup.")
""",
        "Run Ollama with OLLAMA_NO_CLOUD=1. Download qwen3:8b and nomic-embed-text before enabling model calls. Setup downloads need internet; business-data processing stays local. Smaller/larger models can be configured after benchmarking.",
    ),
    (
        6,
        "Agent workflow",
        "Compose the orchestrator, data, analytics, intelligence and reporting nodes with LangGraph. Human-confirmed preparation is a prerequisite. SQLite checkpoints preserve state; suggestions carry dataset evidence IDs.",
        ["sales_intelligence/agents.py"],
        DEMO
        + """from sales_intelligence.agents import run_agent
from sales_intelligence.schemas import Chat
answer = run_agent(demo_store, demo_settings, demo_id, Chat(question="کدام محصولات بیشترین فروش را دارند؟"))
assert answer["status"] == "completed"
assert answer["verified_findings"][0]["values"]["ranking"]
display(answer)
unsupported = run_agent(demo_store, demo_settings, demo_id, Chat(question="Which customers will churn?"))
assert unsupported["status"] == "needs_clarification_or_data"
display(unsupported)
""",
        "Inspect the selected tool and its source/version. Relative dates require explicit UI date filters. Free-form SQL and generated Python execution are not provided. Checkpoints retain history but failed tasks restart explicitly; they do not resume model training mid-operation.",
    ),
    (
        7,
        "n8n automation",
        "Use n8n to submit a sales question and retrieve task status. A separate inactive schedule can submit a daily dashboard job. The backend owns data processing and agent state; n8n owns triggers and API connections.",
        [
            "scripts/build_workflows.py",
            "workflows/sales_advisor.json",
            "workflows/task_status.json",
            "workflows/daily_report.json",
        ],
        """workflows = {}
for path in (ROOT / "workflows").glob("*.json"):
    flow = json.loads(path.read_text())
    assert flow["active"] is False
    workflows[path.name] = {"name": flow["name"], "nodes": [node["name"] for node in flow["nodes"]]}
display(workflows)
if RUN_N8N:
    import getpass, httpx
    base = "http://localhost:5678"
    webhook_key = getpass.getpass("Local n8n webhook key: ")
    approved_dataset_id = input("Prepared API dataset UUID, not the notebook demonstration UUID: ").strip()
    response = httpx.post(base + "/webhook/sales-advisor", headers={"X-Webhook-Key": webhook_key},
        json={"dataset_id": approved_dataset_id, "question": "Which products sell best?", "use_llm": False},
        timeout=20, trust_env=False)
    response.raise_for_status()
    display(response.json())
else:
    print("Live n8n call not run. Import the JSON files and configure header credentials using docs/n8n_setup.md.")
""",
        "Use separate credentials for n8n webhook access and the backend API. Never export secrets into workflow JSON. Docker URLs use http://api:8000; a fully native setup uses http://127.0.0.1:8000. No workflow sends messages or publishes itself.",
    ),
    (
        8,
        "Local RAG and text analysis",
        "Extract bounded TXT/MD, text PDF or DOCX content, chunk it, embed through local Ollama and index vectors using FAISS. Document/model hashes prevent redundant embedding. Use deterministic TF-IDF and NMF for text exploration.",
        ["sales_intelligence/rag.py", "sales_intelligence/nlp.py"],
        DEMO
        + """from sales_intelligence.nlp import text_analysis
from sales_intelligence.rag import add_document, retrieve
display(text_analysis(demo_store, demo_id))
if RUN_LOCAL_MODELS:
    from sales_intelligence.config import Settings
    from sales_intelligence.llm import LocalModel
    local_model = LocalModel(Settings().prepare())
    policy = (ROOT / "sample_data/company_policy.txt").read_bytes()
    display(add_document(demo_store, demo_id, "fictional_policy.txt", policy, local_model))
    display(retrieve(demo_store, demo_id, "What approval is required for product bundles?", local_model))
else:
    print("Live embedding/retrieval not run. Tests exercise FAISS indexing with explicit fixture embeddings.")
""",
        "Sentiment and complaint classification are reported as not estimated without reviewed labels. evaluate_text_classifier trains and evaluates the supplied taxonomy with TF-IDF, logistic regression and a chronological holdout; it never invents labels. NMF topics are exploratory. Scanned PDFs need OCR outside this implementation. Retrieved documents are not treated as verified transaction facts.",
    ),
    (
        9,
        "Conversational API and background jobs",
        "Expose authenticated FastAPI endpoints for uploading, preparation approvals, queries, exports and background ML/RAG jobs. A bounded process pool handles longer operations; clients poll task IDs and can request cancellation or one retry.",
        ["sales_intelligence/jobs.py", "sales_intelligence/api.py", "scripts/serve.py"],
        DEMO
        + """from fastapi.testclient import TestClient
from sales_intelligence.api import create_app
# This in-process check starts no public server and uses only fictional credentials.
app = create_app(demo_settings)
client = TestClient(app)
assert client.get("/api/health").status_code == 401
client.headers["X-API-Key"] = demo_settings.api_key
assert client.get("/api/health").status_code == 200
display(client.get("/api/schema/" + demo_id).json())
""",
        "Run one API server worker; its internal process pool is configurable. Cancellation is cooperative at task boundaries. A restart marks incomplete jobs failed for explicit retry. Dataset changes invalidate queued and in-flight results.",
    ),
    (
        10,
        "Simulation, reporting, deployment and verification",
        "Calculate explicit arithmetic scenarios, export safe CSV/XLSX/JSON/HTML, document assumptions, package local deployment and run the full acceptance tests. Cleanup previews expire-after-inactivity candidates before explicit deletion.",
        [
            "sales_intelligence/reporting.py",
            "scripts/cleanup.py",
            "scripts/notebook_demo.py",
            "Dockerfile",
            ".dockerignore",
            "compose.yaml",
            "frontend/Dockerfile",
            "frontend/nginx.conf",
            "tests/conftest.py",
            "tests/test_data.py",
            "tests/test_agents_ml.py",
            "tests/test_api.py",
            "tests/test_text_and_safety.py",
            "scripts/benchmark.py",
            "scripts/verify_notebooks.py",
            "scripts/package_project.py",
            "scripts/build_notebooks.py",
            "requirements.lock.txt",
            "requirements-dev.lock.txt",
            "README.md",
            "docs/architecture.md",
            "docs/n8n_setup.md",
            "docs/technical_report.md",
            "docs/sources.md",
            "docs/validation.md",
        ],
        DEMO
        + """from sales_intelligence.reporting import simulate, export
from sales_intelligence.schemas import Simulation
scenario = simulate(demo_store, demo_id, Simulation(price_change=0.05, assumptions_confirmed=True))
assert scenario["causal_prediction"] is False
display(scenario)
for output_format in ["csv", "xlsx", "json", "html"]:
    body, mime, name = export(demo_store, demo_id, output_format)
    assert len(body) > 0
    print(name, mime, len(body), "bytes")
# Run the tests in a terminal, or opt in here. This takes longer than the demonstration cells.
RUN_TESTS = False
if RUN_TESTS:
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)
""",
        "Review docs/technical_report.md for delivered capabilities and limits. No local model, n8n server, Docker deployment or user-facing service is started by Run All. Integration cells stay opt-in. Do not use synthetic labels as evidence of predictive business value.",
    ),
]


def md(text):
    return nbf.v4.new_markdown_cell(text)


def code(text):
    return nbf.v4.new_code_cell(text.rstrip() + "\n")


def source_cells(paths):
    cells = []
    for path in paths:
        full = ROOT / path
        if not full.is_file():
            raise FileNotFoundError(full)
        cells.append(
            md(
                f"### Code cell · `{path}`\n\nThis is the complete source file. Running the cell writes a separate reconstruction under `notebook_project/`."
            )
        )
        cells.append(code(f'%%writefile "{{BUILD_ROOT / {path!r}}}"\n' + full.read_text()))
    return cells


def write_notebook(path, cells):
    notebook = nbf.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Python 3 (local-sales)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
    )
    nbf.validate(notebook)
    nbf.write(notebook, path)


def build():
    OUT.mkdir(exist_ok=True)
    introduction = """# Local AI Sales Intelligence\n\nA complete source walkthrough in ten chapters. Each chapter contains explanations, full file-writing code cells, runnable fictional-data examples and a verification checkpoint.\n\nStart Jupyter from this project using its virtual environment. Read `README.md` first. The delivered source files are already present. Source cells reconstruct a separate copy in `notebook_project/`; demonstrations import the supplied, tested package.\n\nAll demonstrations use clearly fictional transactions. Model and n8n calls are opt-in. `Run All` does not install system software, download models, publish workflows, or start services. To review one chapter at a time, use the individual notebooks and pause at each checkpoint.\n\nThe original prompt's ten topics are retained. Basic deterministic preparation comes before optional local models, and the complete web API is assembled after its modules exist.\n"""
    master = [md(introduction), md("## Cell 1 · Notebook setup"), code(SETUP)]
    index = [
        "# Notebook index",
        "",
        "Open `00_Local_AI_Sales_Intelligence.ipynb` for the entire project, or use one chapter at a time.",
        "",
    ]
    for number, title, description, paths, example, checkpoint in CHAPTERS:
        header = md(f"## Chapter {number} · {title}\n\n{description}")
        cells = [
            header,
            *source_cells(paths),
            md("### Run the chapter example"),
            code(example),
            md(
                "### Review checkpoint\n\n"
                + checkpoint
                + "\n\nReview this result before moving to the next chapter."
            ),
        ]
        slug = title.lower().replace(" ", "_").replace(",", "")
        filename = f"{number:02d}_{slug}.ipynb"
        write_notebook(OUT / filename, [md(introduction), code(SETUP), *cells])
        master.extend(cells)
        index.append(f"{number}. [{title}]({filename})")
    write_notebook(OUT / "00_Local_AI_Sales_Intelligence.ipynb", master)
    (OUT / "README.md").write_text("\n".join(index) + "\n")
    print(
        f"Built 11 notebooks. Master has {len(master)} cells, including {sum(c.cell_type == 'code' for c in master)} code cells."
    )


if __name__ == "__main__":
    build()
