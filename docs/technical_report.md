# Technical report

## Delivered scope

The implementation is a bounded local application covering file ingestion, metadata/schema inspection, confirmed preparation, business analytics, evaluated ML, local structured model calls, a LangGraph agent, n8n job submission/status/scheduling, local document retrieval, text exploration, conversational tool selection, arithmetic scenarios and safe exports. All application source is included as Jupyter code cells. No mock sales result is used by the API; examples are explicitly fictional and isolated.

| Topic | Implementation and conditions |
|---|---|
| Excel/CSV | All ordinary worksheets; UTF-8 CSV; restricted non-macro XLS; XLSX archive/formula checks; 25 MB, 200,000 rows total and 200 columns by default |
| Mapping | Header-based suggestions, manual confirmation, explicit grain, calendar, currency and amount definitions |
| Relationships | One confirmed dimension join per dataset, validated many-to-one or one-to-one; ambiguous/unmatched keys require a decision |
| Cleaning | Preserve originals; separate cleaned versions; configurable numeric null/duplicate policy; invalid-value review; per-cell lineage |
| Analytics | Sales, time trends, customers/products/regions, AOV, discounts, Pareto, RFM, monthly cohorts, basket rules, MAD anomalies and numeric correlations |
| ML | Seasonal-baseline comparison, recursive daily forecast backtests, ridge regression, balanced logistic classification, RFM KMeans with silhouette comparison |
| Local model | Shared configurable Ollama model through LangChain, structured Pydantic output, bounded retries/context, prompt hashes, no cloud endpoints or external tracing |
| Agent | Five LangGraph roles; fixed tool registry, evidence references, human-confirmed preparation prerequisite, SQLite checkpoints |
| n8n | Three inactive importable workflows: async question submission, task status and optional scheduled dashboard |
| RAG | Local Ollama embeddings, FAISS, source attribution, byte/model/chunk hashes, text PDF/DOCX/TXT/MD, retrieval evaluation utility |
| NLP | TF-IDF keywords and NMF topics; sentiment/complaint classifier evaluation with existing, reviewed labels, chronological holdout and duplicate-text checks |
| Conversation | Persian/English deterministic fallback or local LLM router; real analysis query; explicit date filters; no generated Python/SQL execution |
| What-if | Explicit price/volume/discount arithmetic; user assumptions; optional cost scenario; no inferred causal elasticity |
| Delivery | React/Vite/TypeScript/Tailwind/Plotly, FastAPI, SQLite/Parquet, notebooks, examples, tests, native and Compose setup |

## Explicit boundaries

This is a single-company implementation. It does not include multi-tenant accounts, staff RBAC, internet-facing deployment, OCR, unattended source-folder ingestion, multiple simultaneous dimension joins, exchange-rate conversion, pretrained/calibrated sentiment models, an automatic complaint taxonomy, validated churn/CLV targets, estimated causal demand elasticity, PDF report generation, or external customer messaging. Numeric classification and regression run only on supplied numeric predictors and existing labels. Text classification uses a separate TF-IDF/logistic pipeline and requires reviewed labels. No XGBoost dependency is added without a measured need.

Native ingestion does not run in a hardened parser sandbox. Size/archive/formula restrictions reduce risk but are not a guarantee that every parser vulnerability or malicious PDF will be caught. Use trusted local input in this deployment. Application-level data encryption and decimal-ledger accounting are separate requirements. Inspect disk/backups permissions for real company data.

Sentiment and complaint classification need domain/language evaluation. Churn labeling needs a defensible outcome horizon and observation window. A synthetic sample label demonstrates the classifier API and must not be interpreted as predictive capability. Missing support is reported explicitly rather than replaced by invented targets or scores.

The forecast minimum of 90 days is an engineering guard, not a statistical guarantee. Model usefulness depends on time span, seasonality, structural changes and backtest results. Its displayed uncertainty band uses pooled absolute residuals and has no guaranteed coverage at each future horizon. RFM clusters are descriptive and their IDs have no intrinsic business meaning.

The model cannot author free-form financial findings. It selects an allowed tool and optional review actions; Python renders computed values. This restricts open-ended explanation but keeps the evidence path inspectable. “Why” questions yield descriptive trend evidence, not a causal conclusion. User-confirmed filters are separate from language interpretation.

## Performance and reproducibility

Workbook sheets are parsed once into Parquet. Analysis uses vectorized operations where appropriate. Changed dataset versions separate all result keys. The process queue is bounded at 16 and defaults to one worker. n8n requests return task receipts promptly. Ollama's model count/concurrency is bounded in Compose. Contexts are bounded, and model calls share one chat model across roles.

The current reader is deliberately bounded and does not implement out-of-core analytics. Larger-than-limit CSV input must be split or handled by a separately designed chunked aggregation flow. Benchmarks report wall/CPU time and completion RSS. A sampling benchmark script records observed peak RSS, not a guaranteed instantaneous OS high-water mark. No performance claim is made without a measurement on the same data and hardware.

Python and npm lock files record the versions used during validation. Image tags are pinned but not digest-locked. Regenerate notebook source cells after any implementation change. The validation record distinguishes unit/integration tests, notebook execution, frontend builds and unperformed live integrations.

## Suggested academic evaluation

Evaluate ingestion correctness using known totals and hostile/ambiguous files. Evaluate mapping against a labeled column-matching set. Evaluate numeric analytics against independent hand calculations. Use chronological forecast backtests and a seasonal baseline. Evaluate retrieval with labeled relevant source IDs. Evaluate question routing and refusal behavior with Persian/English queries, including unsupported claims and prompt injection attempts. Evaluate commercial suggestions through a separately approved business experiment; citations alone do not prove an action will improve sales.
