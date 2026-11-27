"""Optional read-only MCP tools over the local RiskLens SQLite store."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.database import Store
from app.features import build_feature_vector
from app.model import load_artifact, predict
from app.policy import PolicyCosts, recommend

settings = get_settings()
store = Store()
artifact, model_error, _checksum = load_artifact(settings.model_path, settings.model_sha256)
mcp = FastMCP("RiskLens AI")


@mcp.tool()
def get_transaction(transaction_id: str) -> dict:
    """Fetch one transaction's allow-listed attributes. Free-text descriptions are omitted."""
    row = store.get_transaction(transaction_id)
    if row is None:
        return {"found": False}
    fields = ("transaction_id", "timestamp", "sender_id", "receiver_id", "amount",
              "payment_currency", "received_currency", "sender_location", "receiver_location",
              "payment_type", "source")
    return {"found": True, **{key: row[key] for key in fields}}


@mcp.tool()
def get_account_history(account_id: str, limit: int = 20) -> dict:
    """Retrieve up to 50 recent sender-side records without descriptions or arbitrary SQL."""
    if not 1 <= limit <= 50 or len(account_id) > 64:
        raise ValueError("limit must be 1–50 and account_id at most 64 characters")
    rows = store.history(before=datetime.now(timezone.utc).isoformat(), sender_id=account_id)
    rows = rows[-limit:]
    fields = ("transaction_id", "timestamp", "receiver_id", "amount", "payment_currency")
    return {"count": len(rows), "items": [{key: row[key] for key in fields} for row in rows]}


@mcp.tool()
def get_transaction_velocity(transaction_id: str) -> dict:
    """Calculate point-in-time transaction velocity from persisted history."""
    row = store.get_transaction(transaction_id)
    if row is None:
        return {"found": False}
    vector = build_feature_vector(row, store.feature_history(row))
    return {"found": True, "sender_txn_count_24h": vector["sender_txn_count_24h"],
            "receiver_txn_count_24h": vector["receiver_txn_count_24h"],
            "seconds_since_sender_txn": vector["seconds_since_sender_txn"]}


@mcp.tool()
def get_model_prediction(transaction_id: str) -> dict:
    """Return a calibrated probability only when the compatible trained model is installed."""
    if artifact is None:
        return {"available": False, "detail": model_error}
    row = store.get_transaction(transaction_id)
    if row is None:
        return {"available": False, "detail": "transaction not found"}
    vector = build_feature_vector(row, store.feature_history(row))
    probability, latency = predict(artifact, vector)
    return {"available": True, "calibrated_probability": probability,
            "model_version": artifact["model_version"], "inference_latency_ms": latency}


@mcp.tool()
def evaluate_risk_policy(transaction_id: str, threshold: float = 0.5,
                         false_positive_cost: float = 1.0,
                         missed_fraud_cost: float = 100.0,
                         manual_review_cost: float = 0.25) -> dict:
    """Score a stored transaction locally, then return a simulated human-review recommendation."""
    if artifact is None:
        return {"recommended_simulated_action": "insufficient_evidence", "human_review_required": True,
                "detail": model_error}
    if not 0 < threshold < 1:
        raise ValueError("threshold must be in (0,1)")
    row = store.get_transaction(transaction_id)
    if row is None:
        return {"recommended_simulated_action": "insufficient_evidence", "human_review_required": True,
                "detail": "transaction not found"}
    vector = build_feature_vector(row, store.feature_history(row))
    probability, _latency = predict(artifact, vector)
    action, costs = recommend(probability, threshold,
                              PolicyCosts(false_positive_cost, missed_fraud_cost, manual_review_cost))
    return {"recommended_simulated_action": action, "human_review_required": True,
            "policy_costs": costs, "assumptions": "80% manual review effectiveness; hypothetical costs"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
