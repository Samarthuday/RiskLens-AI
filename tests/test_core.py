import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.features import MODEL_FEATURES, build_feature_vector
from app.investigation import validate_report
from app.main import create_app
from app.policy import PolicyCosts, cost_optimal_review_threshold, simulate_policy
from app.schemas import TransactionCreate
from app.simulator import Simulator
from app.tools import FeatureInput, ToolRegistry, ToolSpec


def tx(transaction_id: str, timestamp: datetime, sender: str = "sender_a", amount: float = 100.0) -> TransactionCreate:
    return TransactionCreate(transaction_id=transaction_id, timestamp=timestamp, sender_id=sender,
                             receiver_id=f"receiver_{transaction_id}", amount=amount,
                             source="simulator", description="synthetic test")


def test_feature_schema_order_and_strict_point_in_time():
    current_time = datetime(2025, 1, 2, tzinfo=timezone.utc)
    history = [
        tx("prior", current_time - timedelta(hours=1), amount=10.0).model_dump(mode="json"),
        tx("same_timestamp", current_time, amount=999.0).model_dump(mode="json"),
    ]
    current = tx("current", current_time, amount=20.0).model_dump(mode="json")
    vector = build_feature_vector(current, history)
    assert list(vector) == MODEL_FEATURES
    assert vector["sender_txn_count_24h"] == 1
    assert vector["sender_amount_sum_24h"] == 10.0
    assert vector["pair_transaction_count"] == 0
    schema = json.loads((Path(__file__).parents[1] / "research/feature_schema.json").read_text())
    assert schema["feature_names"] == MODEL_FEATURES


def test_simulator_reproducibility():
    first = Simulator(12).reset("burst", 36)
    second = Simulator(12).reset("burst", 36)
    assert [x.model_dump(mode="json") for x in first] == [x.model_dump(mode="json") for x in second]
    assert all("fraud" not in row.model_dump(mode="json") for row in first)


def test_policy_costs_are_bounded_and_budgeted():
    costs = PolicyCosts(false_positive=1, missed_fraud=100, manual_review=0.25)
    threshold = cost_optimal_review_threshold(costs)
    assert 0 < threshold < 1
    result = simulate_policy([0.01, 0.8, 0.5, 0.02], 0.5, costs)
    assert result["review_count"] <= 2
    assert "precision" not in result and "recall" not in result
    assert result["scope_note"].startswith("Hypothetical")


def test_tool_registry_enforces_allow_list_schema_and_call_budget():
    class Input(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int

    registry = ToolRegistry(max_calls=1)
    registry.register(ToolSpec("double", "double a value", Input, lambda args: args["value"] * 2))
    assert registry.call("double", {"value": 4}) == 8
    try:
        registry.call("double", {"value": 2})
        raise AssertionError("call budget should be enforced")
    except RuntimeError as error:
        assert "limit" in str(error)
    try:
        registry.call("unknown", {})
        raise AssertionError("unknown tools should be rejected")
    except ValueError as error:
        assert "allow-listed" in str(error)
    with pytest.raises(ValueError, match="feature vector schema mismatch"):
        FeatureInput(feature_vector={"Sender_account": "must-not-enter-model"})


def test_transaction_investigation_and_review_persist(tmp_path):
    app = create_app(tmp_path / "missing.joblib", tmp_path / "risklens.sqlite3")
    client = TestClient(app)
    seeded = client.post("/api/v1/simulation/reset?scenario=burst&count=36")
    assert seeded.status_code == 200
    transactions = client.get("/api/v1/transactions").json()["items"]
    target = next(item for item in transactions if item["transaction_id"].endswith("00025"))
    response = client.post("/api/v1/investigations", json={"transaction_id": target["transaction_id"]})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["model_risk_probability"] is None
    assert report["risk_classification"] == "unavailable"
    assert report["recommended_action"] == "insufficient_evidence"
    assert report["explanation_status"] == "unavailable"
    invalid = dict(report)
    invalid["evidence"] = [dict(item) for item in report["evidence"]]
    invalid["evidence"][1]["statement"] = "999 prior sender transactions in the preceding 24 hours."
    with pytest.raises(ValueError, match="numeric claim"):
        validate_report(invalid, app.state.store)
    assert client.get(f"/api/v1/investigations/{report['investigation_id']}").status_code == 200
    reviewed = client.post(f"/api/v1/cases/{report['investigation_id']}/review", json={"decision": "escalated"})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_decision"] == "escalated"
    assert client.get("/api/v1/monitoring/metrics").json()["investigation_count"] == 1


def test_api_policy_simulator_does_not_claim_supervised_metrics(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    response = client.post("/api/v1/policies/simulate", json={"probabilities": [.01, .6, .4], "alert_budget": .5})
    assert response.status_code == 200
    assert "expected_cost_with_policy" in response.json()
    assert "recall" not in response.json()


def test_model_unavailable_returns_explicit_503(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    assert client.get("/api/v1/health").json()["model_loaded"] is False
    assert client.post("/api/v1/risk/score", json={"transaction_id": "sim_41_00001"}).status_code == 503


def test_transaction_ingestion_is_idempotent_and_rejects_conflicting_reuse(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    payload = {
        "transaction_id": "txn_idem_1", "timestamp": "2025-03-01T13:45:00Z",
        "sender_id": "acct_1", "receiver_id": "acct_2", "amount": 100,
        "description": " synthetic test ", "source": "manual",
    }
    first = client.post("/api/v1/transactions", json=payload)
    second = client.post("/api/v1/transactions", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["idempotent_replay"] is True
    payload["amount"] = 101
    assert client.post("/api/v1/transactions", json=payload).status_code == 409


def test_eval_suite_has_30_integrity_scenarios():
    from app.evaluation import run_evaluation

    report = run_evaluation()
    assert report["scenario_count"] == 30
    assert report["metrics"]["report_valid"] == 1.0
    assert report["metrics"]["model_claims_absent"] == 1.0
    assert report["metrics"]["injection_text_excluded"] == 1.0
