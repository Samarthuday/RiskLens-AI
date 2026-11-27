"""RiskLens AI REST API and static dashboard."""

import asyncio
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import ROOT, get_settings
from app.database import ACTIVE_SESSION_ID, Store
from app.features import FEATURE_SCHEMA_VERSION, build_feature_vector
from app.investigation import investigate
from app.model import compatibility_warnings, explain, load_artifact, predict
from app.payments import WebhookError, normalize_payment_event, verify_signature
from app.policy import PolicyCosts, simulate_policy
from app.schemas import (
    InvestigationRequest,
    PolicySimulationRequest,
    ReviewRequest,
    TransactionCreate,
    TransactionScoreRequest,
)
from app.simulator import SimulatorPool

METRICS_PATH = ROOT / "research/reported_metrics.json"
PUBLIC_PATH = ROOT / "public"


class RequestGuard(BaseHTTPMiddleware):
    """Small single-process rate and body-size guard for the local portfolio demo."""

    def __init__(self, app, limit_per_minute: int = 120):
        super().__init__(app)
        self.limit = limit_per_minute
        self.requests: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
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


class RequestBodyLimitMiddleware:
    """Bound streamed/chunked API bodies, including requests without Content-Length."""

    def __init__(self, app, max_bytes: int = 1_000_000):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > self.max_bytes:
            body = b'{"detail":"Request body exceeds the 1 MB limit."}'
            await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return

        chunks = bytearray()
        disconnected = False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                break
            chunks.extend(message.get("body", b""))
            if len(chunks) > self.max_bytes:
                body = b'{"detail":"Request body exceeds the 1 MB limit."}'
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
            if not message.get("more_body", False):
                break

        if disconnected:
            await self.app(scope, receive, send)
            return
        sent = False

        async def replay_body():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(chunks), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_body, send)


class SessionStoreMiddleware:
    """Select an isolated SQLite store using the signed, HTTP-only session cookie."""

    def __init__(self, app, store: Store, max_sessions: int = 500):
        self.app = app
        self.store = store
        self.max_sessions = max_sessions

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        session = scope.get("session")
        if session is None:
            raise RuntimeError("SessionMiddleware must wrap SessionStoreMiddleware.")
        session_id = session.get("risklens_session_id")
        if not isinstance(session_id, str) or len(session_id) < 32:
            session_id = secrets.token_urlsafe(32)
            session["risklens_session_id"] = session_id
            self.store.prune_expired_sessions(max_sessions=self.max_sessions, preserve_session_id=session_id)
        token = ACTIVE_SESSION_ID.set(session_id)
        try:
            await self.app(scope, receive, send)
            path = self.store.session_path(session_id)
            if path.exists():
                os.utime(path, None)
        finally:
            ACTIVE_SESSION_ID.reset(token)


class RequestMetricsMiddleware:
    """Persist status and full request latency for API requests per browser session."""

    def __init__(self, app, store: Store):
        self.app = app
        self.store = store

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/v1/") or path in {
            "/api/v1/health", "/api/v1/ready", "/api/v1/monitoring/metrics",
        }:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            try:
                self.store.record_request(path, status_code, (time.perf_counter() - started) * 1000)
            except Exception:
                # Observability must not convert a successful API response into a failure.
                pass


def _public_transaction(row: dict) -> dict:
    result = dict(row)
    result["simulated"] = result.get("source") == "simulator"
    return result


def create_app(model_path: Path | None = None, database_path: Path | None = None, *, session_isolation: bool = False) -> FastAPI:
    settings = get_settings()
    resolved_model_path = model_path or settings.model_path
    artifact, model_error, checksum = load_artifact(resolved_model_path, settings.model_sha256)
    store = Store(database_path)
    simulator = SimulatorPool(settings.demo_seed, settings.max_demo_sessions)
    app = FastAPI(
        title="RiskLens AI — Transaction Surveillance",
        description="Synthetic suspicious-activity monitoring, evidence-based investigations, and optional version-compatible model inference.",
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
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=1_000_000)
    app.add_middleware(RequestMetricsMiddleware, store=store)
    if session_isolation:
        store.prune_expired_sessions(max_sessions=settings.max_demo_sessions)
        # Middleware wraps in reverse registration order: sessions must be outermost.
        app.add_middleware(SessionStoreMiddleware, store=store, max_sessions=settings.max_demo_sessions)
        app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, max_age=7 * 24 * 60 * 60,
                           same_site="lax", https_only=settings.session_cookie_secure,
                           session_cookie="risklens_session")

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
        # Provenance is assigned by trusted internal simulator code, never by API callers.
        record["source"] = "manual"
        record["timestamp"] = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).isoformat()
        existing = store.get_transaction(record["transaction_id"])
        if existing:
            comparable = {key: existing[key] for key in record}
            if comparable == record:
                return {"transaction": _public_transaction(existing), "idempotent_replay": True}
            raise HTTPException(409, "transaction_id already exists with different content")
        try:
            saved = store.add_transaction(record)
        except Exception as error:
            raise HTTPException(409, f"Unable to persist transaction: {type(error).__name__}") from error
        store.audit(None, payload.transaction_id, "transaction_ingested", {"source": "manual"})
        return {"transaction": _public_transaction(saved), "idempotent_replay": False}

    @app.get("/api/v1/transactions")
    async def list_transactions(limit: int = Query(100, ge=1, le=500)):
        rows = store.list_transactions(limit)
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        return {"items": [_public_transaction(row) for row in rows], "count": len(rows), "total": total}

    @app.get("/api/v1/transactions/{transaction_id}")
    async def get_transaction(transaction_id: str):
        row = store.get_transaction(transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        return _public_transaction(row)

    @app.get("/api/v1/transactions/{transaction_id}/history")
    async def transaction_history(transaction_id: str, limit: int = Query(50, ge=1, le=100)):
        row = store.get_transaction(transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        items, total = store.transaction_history(row, limit)
        return {"items": [_public_transaction(item) for item in items], "count": len(items), "total": total}

    @app.post("/api/v1/webhooks/razorpay", status_code=202)
    async def razorpay_webhook(request: Request):
        if settings.razorpay_mode != "test" or not settings.razorpay_test_webhook_secret:
            raise HTTPException(503, "Razorpay Test Mode webhook intake is not configured.")
        raw_body = await request.body()
        signature = request.headers.get("x-razorpay-signature", "")
        if not verify_signature(raw_body, signature, settings.razorpay_test_webhook_secret):
            raise HTTPException(401, "Webhook signature is invalid.")
        event_id = request.headers.get("x-razorpay-event-id", "")
        try:
            event = normalize_payment_event(raw_body, event_id, datetime.now(timezone.utc).isoformat())
        except WebhookError as error:
            raise HTTPException(422, str(error)) from error
        # Processor events are in a separate owner-managed store, not any browser's session DB.
        with store.base_scope():
            inserted, snapshot = store.accept_razorpay_event(event)
        return {"accepted": inserted, "duplicate": not inserted,
                "payment_id": snapshot.get("payment_id"), "processing": "durably_received"}

    @app.get("/api/v1/payments")
    async def razorpay_payments(
        request: Request,
        limit: int = Query(100, ge=1, le=500),
        status: str | None = Query(None, max_length=32),
        currency: str | None = Query(None, min_length=3, max_length=3),
        method: str | None = Query(None, max_length=32),
        q: str | None = Query(None, max_length=128),
    ):
        expected = settings.razorpay_test_read_token
        authorization = request.headers.get("authorization", "")
        if not expected or not hmac.compare_digest(authorization, f"Bearer {expected}"):
            raise HTTPException(403, "Payment event records require the owner read token.")
        with store.base_scope():
            items, total = store.list_razorpay_payments(limit, status, currency, method, q)
        return {"items": items, "count": len(items), "total": total,
                "scope": "Razorpay Test Mode fields only; amounts remain in provider currency subunits; no AML probability is produced."}

    @app.get("/api/v1/payments/{payment_id}/events")
    async def razorpay_payment_events(payment_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
        expected = settings.razorpay_test_read_token
        authorization = request.headers.get("authorization", "")
        if not expected or not hmac.compare_digest(authorization, f"Bearer {expected}"):
            raise HTTPException(403, "Payment event records require the owner read token.")
        with store.base_scope():
            items = store.list_razorpay_events(payment_id, limit)
        if not items:
            raise HTTPException(404, "payment event history not found")
        return {"payment_id": payment_id, "items": items, "count": len(items)}

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
                "inference_latency_ms": latency_ms, "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_warnings": ["No entity IDs or labels were used as model inputs."]}

    @app.post("/api/v1/investigations")
    async def create_investigation(payload: InvestigationRequest):
        row = store.get_transaction(payload.transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        try:
            return await asyncio.to_thread(investigate, store, row, artifact, payload)
        except Exception as error:
            store.audit(None, row["transaction_id"], "investigation_failed", {"error_type": type(error).__name__})
            raise

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
    async def list_investigations(limit: int = Query(100, ge=1, le=500), transaction_id: str | None = None):
        items = store.list_investigations(limit, transaction_id=transaction_id)
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/investigations/{investigation_id}/trace")
    async def investigation_trace(investigation_id: str):
        if store.get_investigation(investigation_id) is None:
            raise HTTPException(404, "investigation not found")
        return {"investigation_id": investigation_id, "events": store.investigation_trace(investigation_id)}

    @app.post("/api/v1/cases/{case_id}/review")
    async def review_case(case_id: str, payload: ReviewRequest):
        report = store.record_review(case_id, payload.decision, payload.analyst_note)
        if report is None:
            raise HTTPException(404, "case not found")
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
        costs = PolicyCosts(payload.false_positive_cost, payload.missed_event_cost, payload.manual_review_cost,
                            payload.review_effectiveness)
        return simulate_policy(payload.probabilities, payload.alert_budget, costs)

    @app.get("/api/v1/simulation/status")
    async def simulation_status():
        return simulator.for_session(ACTIVE_SESSION_ID.get()).status()

    @app.post("/api/v1/simulation/reset")
    async def simulation_reset(scenario: str = Query("burst", pattern="^(burst|routine)$"), count: int = Query(36, ge=1, le=500)):
        active_simulator = simulator.for_session(ACTIVE_SESSION_ID.get())
        removed = store.reset_simulated_transactions()
        records = active_simulator.reset(scenario, count)
        saved = [store.add_transaction(record.model_dump(mode="python")) for record in records]
        store.audit(None, None, "demo_simulation_seeded", {"scenario": scenario, "count": len(saved), "seed": settings.demo_seed, "removed": removed})
        return {"status": active_simulator.status(), "inserted": len(saved), "scenario": scenario, "synthetic": True}

    @app.post("/api/v1/simulation/start")
    async def simulation_start():
        return simulator.for_session(ACTIVE_SESSION_ID.get()).start()

    @app.post("/api/v1/simulation/pause")
    async def simulation_pause():
        return simulator.for_session(ACTIVE_SESSION_ID.get()).pause()

    @app.post("/api/v1/simulation/step")
    async def simulation_step(count: int = Query(5, ge=1, le=50)):
        active_simulator = simulator.for_session(ACTIVE_SESSION_ID.get())
        if not active_simulator.running:
            raise HTTPException(409, "simulation is paused")
        records = active_simulator.next_batch(count)
        saved = [store.add_transaction(record.model_dump(mode="python")) for record in records]
        store.audit(None, None, "demo_simulation_step", {"count": len(saved), "seed": settings.demo_seed})
        return {"inserted": [_public_transaction(row) for row in saved], "status": active_simulator.status()}

    if PUBLIC_PATH.exists():
        app.mount("/", StaticFiles(directory=str(PUBLIC_PATH), html=True), name="frontend")
    return app


app = create_app(session_isolation=get_settings().session_isolation)
