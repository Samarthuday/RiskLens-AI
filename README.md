---
title: RiskLens AI
sdk: docker
app_port: 7860
---

# RiskLens AI

RiskLens AI is a standalone payment risk investigation application built on a pinned rare-event financial ML research project. It combines a seeded synthetic transaction stream, point-in-time feature construction, optional inference from the validated XGBoost artifact, local SHAP explanations, deterministic cost-sensitive policy recommendations, a human review workflow, and SQLite audit records.

The application runs without credentials or a model artifact. In that mode it still demonstrates transaction ingestion, historical features, evidence retrieval, investigation report validation, and analyst review, while explicitly returning **no model probability**. It never substitutes random predictions or hand-authored alert scores.

**Research foundation:** [Quantitative Transaction Risk Modeling](https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling), pinned to commit `bbe79212099c9d81c74c643362d52c228db7db08`.

## Two-minute demonstration

1. Start the app with `uvicorn app.main:app --host 0.0.0.0 --port 7860` and open <http://localhost:7860>.
2. Reset the **Burst pattern** demo. The simulator creates 36 reproducible synthetic records with no exposed target labels.
3. Select a transaction from the queue. RiskLens retrieves earlier sender activity, computes the research-compatible feature vector, validates a structured report, and saves its evidence and workflow trace.
4. With `artifacts/risk_model.joblib` installed, the investigation also runs the calibrated model and attempts local SHAP attribution. Without it, model probability and explanation stay unavailable.
5. Record an analyst decision; inspect the audit event count and actual workflow latency.
6. Change expected-cost inputs and run the policy simulator. Its estimates are hypothetical and do not claim measured savings.
7. Use **Research provenance** to distinguish the historical SAML-D results from app measurements.

## What is implemented

- FastAPI REST API and responsive dark dashboard; OpenAPI at `/api/docs`.
- Seeded simulation with routine and burst modes; start, pause, step, and reset controls.
- Parameterized SQLite persistence for transactions, cases, prediction latency, and append-only audit events.
- Strict Pydantic transaction and investigation schemas, idempotent transaction ingestion, and a 1 MB body and per-process request limit.
- Point-in-time transaction, behavioral, and network feature transformation aligned to the pinned research feature schema.
- Optional calibrated XGBoost inference, threshold-based review flag, and local SHAP contributions, only when a compatible artifact is supplied.
- Deterministic evidence-based report generation, evidence reference checks, conditional model routing, and explicit uncertainty/counter-evidence fields.
- Human review and persisted analyst actions; a bounded, read-only optional MCP tool server.
- Hypothetical expected-cost policy simulation and output-distribution drift comparison when actual model observations exist.
- Optional OpenAI-compatible summary synthesis gated to synthetic demo records; no free-text description or personal transaction text is sent to the provider. No API key is required for offline use.
- A 30-scenario evidence-integrity evaluation suite, automated tests, CI workflow, Docker configuration, and deployment instructions.

## Research metrics and app measurements

The following are copied from the source repository report at the pinned commit; they are historical held-out results on synthetic SAML-D data, not new RiskLens results and not live monitoring metrics.

| Historical research metric | Reported result |
|---|---:|
| PR-AUC | 0.9859286 |
| ROC-AUC | 0.9998338 |
| Recall at top 0.1% alert budget | 83.8843% |

Metric provenance, other reported scores, the artifact gap, and the feature compatibility notes are in [docs/research-foundation.md](docs/research-foundation.md). App latency and scenario-evaluation output are written from actual local runs; they are not filled with sample values.

## Run locally

```bash
git clone https://github.com/Samarthuday/RiskLens-AI.git
cd RiskLens-AI
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

The database defaults to `data/risklens.sqlite3`. It is local and ignored by Git. No raw dataset is needed to start the synthetic demonstration.

### Optional validated model artifact

This checkout intentionally contains no model binary or licensed SAML-D data. See [docs/research-foundation.md](docs/research-foundation.md) for the exact recovery/training procedure from the pinned research source. Once you have a trusted compatible artifact:

```bash
mkdir -p artifacts
cp /path/to/trusted/risk_model.joblib artifacts/risk_model.joblib
shasum -a 256 artifacts/risk_model.joblib
```

Set `RISKLENS_MODEL_PATH` and the matching `RISKLENS_MODEL_SHA256` in `.env`, then restart. The health and model metadata endpoints report whether it loaded and the actual checksum. Never load a joblib artifact from an untrusted source: Python pickle loading can execute code.

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
The optional local MCP server and client configuration are documented in [docs/mcp.md](docs/mcp.md).

## Architecture and quantitative methodology

The request path and deterministic/LLM boundary are documented in [docs/architecture.md](docs/architecture.md). Research-compatible online features are in `app/features.py`; these exclude the current transaction and identifiers/target columns. The calibrator module under `src/models/` preserves the import path embedded in source artifacts.

Risk bands are demo policy cutoffs (low `<0.05`, medium `0.05–0.20`, high `0.20–0.50`, critical `>=0.50`). The model's alert threshold is learned on the source validation set and used by score endpoints when a compatible artifact loads. The decision simulator assumes manual review prevents 80% of modeled missed-event cost; this assumption is adjustable in code and is not a claim about an actual operations team. It reports expected costs, never precision/recall without labels or actual financial savings.

## Evaluation and tests

```bash
pytest -q
ruff check app scripts tests src
python scripts/run_agent_eval.py
```

The agent evaluation has 30 routine, burst, unusual-legitimate, missing-history, contradictory-evidence, and prompt-injection-text cases. It measures schema/evidence validity, use of expected deterministic indicators, and exclusion of untrusted transaction descriptions. It does not measure fraud classification accuracy: no compatible model artifact or adjudicated outcome labels are distributed with this repository.

## Security and limitations

- This is a simulated financial research demonstration; it is not integrated with a payment processor and does not move, hold, approve, or reject real money.
- All recommendations require a human review. LLM synthesis cannot assign probability or change a policy action.
- The optional LLM path is disabled by default and only accepts generated simulator evidence. It has one request, an 8-second timeout, an output token cap, citations restricted to supplied evidence, and rejects numeric claims. Free-text descriptions are excluded.
- SQLite, in-memory per-process rate limiting, and the local simulator suit a single-instance demo. They are not substitutes for production auth, a managed database, distributed rate controls, or service-level observability.
- Synthetic SAML-D results do not establish performance on real institution data. Drift is a score-distribution check and cannot establish performance deterioration without labels.
- The local feature calculation matches the published schema and point-in-time windows. Same-timestamp order is intentionally excluded to avoid leakage; training artifacts should be verified on the user's accepted sample before operational use.
- A public deployment URL is not claimed. See [docs/deployment.md](docs/deployment.md) for deployment setup and remaining artifact requirements.

## Project description

**RiskLens AI —** Built a standalone FastAPI payment-risk investigation demo with point-in-time behavioral/network features, calibrated XGBoost inference when a trusted artifact is configured, SHAP attribution, deterministic evidence validation, cost-sensitive policy simulation, SQLite case/audit persistence, optional constrained MCP/LLM interfaces, and a 30-scenario integrity evaluation. Historical performance figures are separately attributed to a pinned synthetic SAML-D research source.
