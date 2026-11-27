---
title: RiskLens AI
sdk: docker
app_port: 7860
---

# RiskLens AI

RiskLens AI is an evidence-driven investigation workspace for a risk or operations analyst deciding whether unusual activity warrants further review. The user can inspect a transaction, compare it with earlier observed activity, examine supporting and weakening evidence, and save a human disposition. Its research model target is suspicious activity in synthetic AML data; it is not a payment-fraud, chargeback, or realized-loss model.

The application runs without credentials or a model artifact. In that mode it still demonstrates transaction ingestion, historical features, evidence retrieval, investigation report validation, and analyst review, while explicitly returning **no model probability**. It never substitutes random predictions or hand-authored alert scores.

**Research foundation:** [Quantitative Transaction Risk Modeling](https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling), pinned to commit `bbe79212099c9d81c74c643362d52c228db7db08`.

## Two-minute demonstration

1. Start the app with `uvicorn app.main:app --host 0.0.0.0 --port 7860` and open <http://localhost:7860>.
2. Reset the **Burst pattern** demo. The simulator creates 36 reproducible synthetic records with no exposed target labels.
3. Open a transaction and select **Run investigation**. RiskLens retrieves earlier activity, calculates indicators, optionally scores with a compatible model, validates source references, and saves an evidence-linked report. Existing cases reopen without duplication.
4. This checkout has no `risklens-causal-v2` model artifact, so it displays evidence and uncertainty without a model probability or SHAP attribution. Source model artifacts with the old HHI definition are rejected.
5. Record an analyst decision and note; reopen the case to see the saved decision, revisions, and workflow trace.
6. Change expected-cost inputs and run the policy simulator. Its estimates are hypothetical and do not claim measured savings.
7. Use **Research provenance** to distinguish the historical SAML-D results from app measurements.

## What is implemented

### Dashboard workspace

The dashboard separates Overview, Transactions, Case inbox, Policy lab, System
health, and Research foundation. It uses local CSS, JavaScript, SVG icons, and
charts, with no frontend runtime dependencies or external assets.

- Search IDs and accounts; filter, sort, paginate, and export the recent transaction window as CSV.
- Reopen saved cases, inspect evidence and bounded prior account activity, and review persisted workflow events.
- Save analyst decisions and notes together, keep review revisions in the case history, and export a case as JSON.
- Explore hypothetical policy costs with explicit assumptions; historical research performance stays in the provenance view.

Lists show up to the latest 500 records. The public app uses browser-session
database isolation; resets affect only that session. Sessions are disposable,
unauthenticated demos, with a seven-day cookie lifetime and 30-day inactive data
cleanup. For local development, run `python scripts/dev.py` (port 3000) or
`npm run dev` after installing Python dependencies.

- FastAPI REST API and responsive dashboard; OpenAPI at `/api/docs`.
- Seeded simulation with routine and burst modes; start, pause, step, and reset controls.
- Parameterized SQLite persistence for transactions, cases, prediction latency, and append-only audit events.
- Strict Pydantic transaction and investigation schemas, idempotent transaction ingestion, and a 1 MB body and per-process request limit.
- Versioned causal point-in-time feature transformation with an explicit compatibility break for the source HHI bug; model artifacts require the `risklens-causal-v2` contract.
- Optional calibrated XGBoost inference and local SHAP contributions, only when a v2 artifact is supplied.
- Deterministic evidence reports bound to successful tool calls, stored tool results, cited transaction IDs, account scope, and time windows.
- Persistent analyst decisions and notes, reopenable cases, and a saved workflow/tool trace.
- Bounded API body handling including chunked requests; API clients cannot self-assert trusted simulator provenance.
- Hypothetical expected-cost policy simulation and output-distribution drift comparison when actual model observations exist.
- Optional OpenAI-compatible summary synthesis gated to synthetic demo records; no free-text description or personal transaction text is sent to the provider. No API key is required for offline use.
- An 18-case investigation-integrity evaluation, automated tests, CI workflow, Docker configuration, and deployment instructions.

## Research metrics and app measurements

The following are copied from the source repository report at the pinned commit; they are historical held-out results on synthetic SAML-D data, not new RiskLens results and not live monitoring metrics.

| Historical research metric | Value | Version and scope |
|---|---:|---|
| PR-AUC | 0.9859286 | source model 2.1.0 · SAML-D · held-out synthetic AML test split |
| ROC-AUC | 0.9998338 | source model 2.1.0 · SAML-D · held-out synthetic AML test split |
| Recall at top 0.1% alert budget | 83.8843% | source model 2.1.0 · SAML-D · held-out synthetic AML test split |

RiskLens v2 model results, AI investigation comparisons, human-study results,
and hosted-service measurements are not published until measured for their own
version and sample. No live URL or analyst time-savings claim is currently
verified.

Metric provenance, other reported scores, the artifact gap, and the feature compatibility notes are in [docs/research-foundation.md](docs/research-foundation.md). App latency and scenario-evaluation output are written from actual local runs; they are not filled with sample values.

## Run locally

```bash
git clone https://github.com/Samarthuday/RiskLens-AI.git
cd RiskLens-AI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

The database defaults to `data/risklens.sqlite3`. It is local and ignored by Git. No raw dataset is needed to start the synthetic demonstration.

### Optional validated model artifact

This checkout intentionally contains no model binary or licensed SAML-D data. The historical research artifact is not compatible with RiskLens's corrected HHI semantics and will be rejected. See [docs/research-foundation.md](docs/research-foundation.md) for provenance and the new v2 feature/training commands. The upstream dataset is marked CC BY-NC-SA 4.0; confirm the intended use and distribution rights before using or publishing a derived model. Once authorized and trained, verify the artifact with:

```bash
mkdir -p artifacts
cp /path/to/trusted/risk_model.joblib artifacts/risk_model.joblib
shasum -a 256 artifacts/risk_model.joblib
```

Set `RISKLENS_MODEL_PATH` and the required matching `RISKLENS_MODEL_SHA256` in `.env`, then restart. The artifact must declare the exact `risklens-causal-v2` feature contract and the manifest shape in [docs/model-artifact-manifest.schema.json](docs/model-artifact-manifest.schema.json). The health and model metadata endpoints report whether it loaded and the actual checksum. Never load a joblib artifact from an untrusted source: Python pickle loading can execute code.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

The local service listens on port 7860. To enable model scoring, mount the trusted artifact read-only at `/app/artifacts/risk_model.joblib` and configure its SHA-256 using your deployment secret/settings store. The application starts in no-model mode otherwise.

## APIs

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health`, `/ready` | Liveness and readiness |
| GET | `/api/v1/model/metadata` | Runtime artifact state and separately labelled research results |
| POST/GET | `/api/v1/transactions` | Ingest and list transactions |
| GET | `/api/v1/transactions/{id}` | Retrieve a transaction |
| POST | `/api/v1/risk/score` | Score a stored transaction using the compatible model |
| POST/GET | `/api/v1/investigations` | Create and list evidence reports |
| GET | `/api/v1/investigations/{id}` | Retrieve a persisted report |
| GET | `/api/v1/investigations/{id}/trace` | Retrieve investigation workflow events |
| POST | `/api/v1/cases/{id}/review` | Persist analyst disposition |
| GET | `/api/v1/monitoring/metrics`, `/api/v1/monitoring/drift` | Measured local observability and guarded drift comparison |
| POST | `/api/v1/policies/simulate` | Compare expected costs from supplied probabilities and assumptions |
| POST | `/api/v1/simulation/{start,pause,step,reset}` | Control the seeded demo stream |
| GET | `/api/v1/evaluation/results` | Pinned offline research metrics and provenance |

See the interactive docs at `/api/docs` and examples in [docs/api.md](docs/api.md).
The optional local MCP server and client configuration are documented in [docs/mcp.md](docs/mcp.md). The fixed investigation workflow is not an autonomous agent; the optional LLM only summarizes evidence.

## Architecture and quantitative methodology

The request path and deterministic/LLM boundary are documented in [docs/architecture.md](docs/architecture.md). Versioned online features are in `app/features.py`; these exclude the current transaction and identifiers/target columns. The calibrator module under `src/models/` preserves an import path used by source artifacts, but matching that import path does not make a legacy artifact feature-compatible.

Risk bands are demo policy cutoffs (low `<0.05`, medium `0.05–0.20`, high `0.20–0.50`, critical `>=0.50`). The decision simulator uses user-defined abstract cost units and assumes manual review prevents 80% of modeled missed-event cost. Its configured/model threshold can constrain the cost break-even threshold; the response reports which threshold determined the action. These assumptions do not describe an actual operations team, fraud loss, or measured savings. The source research target is AML suspicious activity and its reported metrics are only available in the provenance view.

## Evaluation and tests

```bash
pytest -q
ruff check app scripts tests src
python scripts/run_investigation_eval.py
python scripts/verify_artifact.py --artifact build/risk_model.joblib --sha256 YOUR_TRUSTED_SHA256
```

The investigation integrity evaluation has 18 varied routine, burst, unusual-legitimate, missing-history, contradictory-evidence, and prompt-injection-text cases. Each metric reports its applicable-case denominator; inapplicable checks are excluded rather than counted as passes. It measures deterministic report integrity and prompt-text isolation. It does not evaluate agent tool choice, model accuracy, comparative usefulness, or LLM quality. No v2 metric is reported until a real training/evaluation run completes and dataset rights are cleared.

## Security and limitations

- This is a simulated financial research demonstration; it is not integrated with a payment processor and does not move, hold, approve, or reject real money.
- All recommendations require a human review. LLM synthesis cannot assign probability or change a policy action.
- The optional LLM path is disabled by default and only accepts generated simulator evidence. It has one request, an 8-second timeout, an output token cap, visible evidence citations, and rejects numeric claims and decisive fraud/action language. These lexical checks do not prove semantic entailment. Free-text descriptions are excluded.
- SQLite, in-memory per-process rate limiting, and the local simulator suit a single-instance demo. They are not substitutes for production auth, a managed database, distributed rate controls, or service-level observability.
- Synthetic SAML-D results do not establish performance on real institution data. Drift is a score-distribution check and cannot establish performance deterioration without labels.
- Feature names/order derive from the research project, but source HHI semantics and tied-row behavior are not online-compatible. The loader rejects legacy artifacts; a separately trained and evaluated v2 artifact is required.
- A public deployment URL is not claimed. See [docs/deployment.md](docs/deployment.md) for deployment setup and remaining artifact requirements.

## Project description

**RiskLens AI —** Built a standalone FastAPI transaction-surveillance demo with versioned point-in-time features, fail-closed model artifact loading, evidence-linked investigations, analyst notes and decisions, cost-policy simulation, SQLite audit traces, optional constrained MCP/LLM interfaces, and an 18-case integrity evaluation. Historical AML research metrics are separately attributed to a pinned synthetic SAML-D source; live scoring requires a separately trained v2 artifact.
