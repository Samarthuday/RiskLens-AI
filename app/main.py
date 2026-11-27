"""RiskLens AI REST API and static dashboard."""

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import ROOT, get_settings
from app.database import Store
from app.features import build_feature_vector
from app.investigation import investigate
from app.model import compatibility_warnings, explain, load_artifact, predict
from app.policy import PolicyCosts, simulate_policy
from app.schemas import (
    InvestigationRequest,
    PolicySimulationRequest,
    ReviewRequest,
    TransactionCreate,
    TransactionScoreRequest,
)
from app.simulator import Simulator

METRICS_PATH = ROOT / "research/reported_metrics.json"
PUBLIC_PATH = ROOT / "public"


class RequestGuard(BaseHTTPMiddleware):
    """Small single-process rate and body-size guard for the local portfolio demo."""

    def __init__(self, app, limit_per_minute: int = 120):
        super().__init__(app)
        self.limit = limit_per_minute
        self.requests: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > 1_000_000:
            return JSONResponse({"detail": "Request body exceeds the 1 MB limit."}, status_code=413)
        if self.limit > 0 and request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/v1/health", "/api/v1/ready"}:
            address = request.client.host if request.client else "unknown"
            now = time.monotonic()
            history = self.requests[address]
            while history and history[0] < now - 60:
                history.popleft()
            if len(history) >= self.limit:
                return JSONResponse({"detail": "Rate limit exceeded; retry in one minute."}, status_code=429, headers={"Retry-After": "60"})
            history.append(now)
        return await call_next(request)


def _public_transaction(row: dict) -> dict:
    result = dict(row)
    result["simulated"] = result.get("source") == "simulator"
    return result


def create_app(model_path: Path | None = None, database_path: Path | None = None) -> FastAPI:
    settings = get_settings()
    resolved_model_path = model_path or settings.model_path
    artifact, model_error, checksum = load_artifact(resolved_model_path, settings.model_sha256)
    store = Store(database_path)
    simulator = Simulator(settings.demo_seed)
    app = FastAPI(
        title="RiskLens AI — Payment Risk Intelligence",
        description="Synthetic transaction monitoring, evidence-based investigations, and optional validated model inference.",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.store = store
    app.state.simulator = simulator
    app.state.model = artifact
    app.state.model_error = model_error
    app.state.model_sha256 = checksum
    app.add_middleware(RequestGuard, limit_per_minute=settings.rate_limit_per_minute)

    @app.get("/health")
    @app.get("/api/v1/health")
    @app.get("/api/health")
    async def health():
        return {"status": "healthy" if artifact else "model_unavailable", "model_loaded": artifact is not None,
                "timestamp": datetime.now(timezone.utc).isoformat(), "detail": model_error}

    @app.get("/ready")
    @app.get("/api/v1/ready")
    async def ready():
        return {"ready": True, "model_loaded": artifact is not None, "database": "available"}

    @app.get("/api/v1/model/metadata")
    async def model_metadata():
        research = json.loads(METRICS_PATH.read_text())
        return {
            "runtime_model_loaded": artifact is not None,
            "model_version": artifact.get("model_version") if artifact else None,
            "artifact_sha256": checksum,
            "model_error": model_error,
            "compatibility_warnings": compatibility_warnings(artifact),
            "training_package_versions": artifact.get("package_versions", {}) if artifact else {},
            "research_metrics": research,
            "risk_bands": {"low": "<0.05", "medium": "0.05–0.20", "high": "0.20–0.50", "critical": ">=0.50", "basis": "demonstration policy thresholds"},
        }

    @app.post("/api/v1/transactions", status_code=201)
    async def create_transaction(payload: TransactionCreate):
        record = payload.model_dump(mode="json")
        record["timestamp"] = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).isoformat()
        existing = store.get_transaction(record["transaction_id"])
        if existing:
            comparable = {key: existing[key] for key in record}
            if comparable == record:
                return {"transaction": _public_transaction(existing), "idempotent_replay": True}
            raise HTTPException(409, "transaction_id already exists with different content")
        try:
            saved = store.add_transaction(payload.model_dump(mode="python"))
        except Exception as error:
            raise HTTPException(409, f"Unable to persist transaction: {type(error).__name__}") from error
        store.audit(None, payload.transaction_id, "transaction_ingested", {"source": payload.source})
        return {"transaction": _public_transaction(saved), "idempotent_replay": False}

    @app.get("/api/v1/transactions")
    async def list_transactions(limit: int = Query(100, ge=1, le=500)):
        rows = store.list_transactions(limit)
        return {"items": [_public_transaction(row) for row in rows], "count": len(rows)}

    @app.get("/api/v1/transactions/{transaction_id}")
    async def get_transaction(transaction_id: str):
        row = store.get_transaction(transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        return _public_transaction(row)

    @app.post("/api/v1/risk/score")
    async def score_transaction(payload: TransactionScoreRequest):
        if artifact is None:
            raise HTTPException(503, model_error)
        row = store.get_transaction(payload.transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        history = store.feature_history(row)
        vector = build_feature_vector(row, history)
        probability, latency_ms = await asyncio.to_thread(predict, artifact, vector)
        store.record_prediction(row["transaction_id"], artifact["model_version"], probability, latency_ms)
        threshold = float(artifact["decision_threshold"])
        band = "critical" if probability >= .5 else "high" if probability >= .2 else "medium" if probability >= .05 else "low"
        return {"transaction_id": row["transaction_id"], "calibrated_probability": probability,
                "risk_band": band, "requires_review": probability >= threshold,
                "decision_threshold": threshold, "model_version": artifact["model_version"],
                "inference_latency_ms": latency_ms, "feature_schema_version": "research-bbe7921-v1",
                "feature_warnings": ["No entity IDs or labels were used as model inputs."]}

    @app.post("/api/v1/investigations")
    async def create_investigation(payload: InvestigationRequest):
        row = store.get_transaction(payload.transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        report = await asyncio.to_thread(investigate, store, row, artifact, payload)
        return report

    @app.get("/api/v1/risk/explanation/{transaction_id}")
    async def explain_transaction(transaction_id: str):
        if artifact is None:
            raise HTTPException(503, model_error)
        row = store.get_transaction(transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        vector = build_feature_vector(row, store.feature_history(row))
        contributions = await asyncio.to_thread(explain, artifact, vector)
        if contributions is None:
            raise HTTPException(503, "SHAP explanation could not be calculated with this model build")
        return {"transaction_id": transaction_id, "model_version": artifact["model_version"],
                "method": "SHAP TreeExplainer on model-preprocessed features", "causal_claim": False,
                "contributions": contributions}

    @app.get("/api/v1/investigations/{investigation_id}")
    async def get_investigation(investigation_id: str):
        report = store.get_investigation(investigation_id)
        if report is None:
            raise HTTPException(404, "investigation not found")
        return report

    @app.get("/api/v1/investigations")
    async def list_investigations(limit: int = Query(100, ge=1, le=500)):
        items = store.list_investigations(limit)
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/investigations/{investigation_id}/trace")
    async def investigation_trace(investigation_id: str):
        if store.get_investigation(investigation_id) is None:
            raise HTTPException(404, "investigation not found")
        return {"investigation_id": investigation_id, "events": store.investigation_trace(investigation_id)}

    @app.post("/api/v1/cases/{case_id}/review")
    async def review_case(case_id: str, payload: ReviewRequest):
        report = store.get_investigation(case_id)
        if report is None:
            raise HTTPException(404, "case not found")
        report["status"] = "reviewed"
        report["review_decision"] = payload.decision
        store.update_investigation(report)
        store.audit(case_id, report["transaction_id"], "human_review_recorded", {"decision": payload.decision, "analyst_note_recorded": bool(payload.analyst_note), "analyst_note_length": len(payload.analyst_note)})
        return report

    @app.get("/api/v1/monitoring/metrics")
    async def monitoring_metrics():
        summary = store.monitoring_summary()
        with store.connect() as db:
            latencies = [row[0] for row in db.execute("SELECT inference_ms FROM predictions ORDER BY inference_ms")]
        summary["latency_p50_ms"] = float(np.percentile(latencies, 50)) if latencies else None
        summary["latency_p95_ms"] = float(np.percentile(latencies, 95)) if latencies else None
        summary["model_observation_status"] = "measured from persisted inference calls" if latencies else "no inference calls recorded"
        return summary

    @app.get("/api/v1/monitoring/drift")
    async def monitoring_drift():
        with store.connect() as db:
            observed = [row[0] for row in db.execute("SELECT probability FROM predictions ORDER BY created_at DESC LIMIT 1000")]
        if artifact is None or not artifact.get("validation_probability_quantiles"):
            return {"status": "unavailable", "detail": "Compatible model validation quantiles are required for drift comparison."}
        baseline = np.asarray(artifact["validation_probability_quantiles"], dtype=float)
        if len(observed) < 20:
            return {"status": "insufficient_sample", "observations": len(observed), "minimum_observations": 20, "baseline_source": "artifact validation probability quantiles"}
        observed = np.asarray(observed)
        edges = np.unique(np.quantile(baseline, np.linspace(0, 1, 11)))
        if len(edges) < 3:
            return {"status": "unavailable", "detail": "Validation baseline has insufficient score variation."}
        edges[0], edges[-1] = -np.inf, np.inf
        baseline_hist, _ = np.histogram(baseline, bins=edges)
        current_hist, _ = np.histogram(observed, bins=edges)
        expected = np.maximum(baseline_hist / baseline_hist.sum(), 1e-6)
        actual = np.maximum(current_hist / current_hist.sum(), 1e-6)
        psi = float(np.sum((actual - expected) * np.log(actual / expected)))
        return {"status": "measured", "population_stability_index": psi, "alert_threshold": 0.2,
                "drift_alert": psi >= 0.2, "observations": len(observed),
                "baseline_source": "artifact validation probability quantiles",
                "interpretation": "Score-distribution shift only; does not establish model performance degradation."}

    @app.get("/api/v1/evaluation/results")
    async def evaluation_results():
        return json.loads(METRICS_PATH.read_text())

    @app.post("/api/v1/policies/simulate")
    async def policies_simulate(payload: PolicySimulationRequest):
        costs = PolicyCosts(payload.false_positive_cost, payload.missed_fraud_cost, payload.manual_review_cost)
        return simulate_policy(payload.probabilities, payload.alert_budget, costs)

    @app.get("/api/v1/simulation/status")
    async def simulation_status():
        return simulator.status()

    @app.post("/api/v1/simulation/reset")
    async def simulation_reset(scenario: str = Query("burst", pattern="^(burst|routine)$"), count: int = Query(36, ge=1, le=500)):
        removed = store.reset_simulated_transactions()
        records = simulator.reset(scenario, count)
        saved = [store.add_transaction(record.model_dump(mode="python")) for record in records]
        store.audit(None, None, "demo_simulation_seeded", {"scenario": scenario, "count": len(saved), "seed": settings.demo_seed, "removed": removed})
        return {"status": simulator.status(), "inserted": len(saved), "scenario": scenario, "synthetic": True}

    @app.post("/api/v1/simulation/start")
    async def simulation_start():
        return simulator.start()

    @app.post("/api/v1/simulation/pause")
    async def simulation_pause():
        return simulator.pause()

    @app.post("/api/v1/simulation/step")
    async def simulation_step(count: int = Query(5, ge=1, le=50)):
        if not simulator.running:
            raise HTTPException(409, "simulation is paused")
        records = simulator.next_batch(count)
        saved = [store.add_transaction(record.model_dump(mode="python")) for record in records]
        store.audit(None, None, "demo_simulation_step", {"count": len(saved), "seed": settings.demo_seed})
        return {"inserted": [_public_transaction(row) for row in saved], "status": simulator.status()}

    if PUBLIC_PATH.exists():
        app.mount("/", StaticFiles(directory=str(PUBLIC_PATH), html=True), name="frontend")
    return app


app = create_app()
