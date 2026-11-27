import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.features import FEATURE_SCHEMA_VERSION, MODEL_FEATURES, build_feature_vector
from app.investigation import validate_report
from app.main import create_app
from app.model import load_artifact, sha256_file
from app.policy import PolicyCosts, cost_optimal_review_threshold, recommend, simulate_policy
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
    costs = PolicyCosts(false_positive=1, missed_event=100, manual_review=0.25)
    threshold = cost_optimal_review_threshold(costs)
    assert 0 < threshold < 1
    result = simulate_policy([0.01, 0.8, 0.5, 0.02], 0.5, costs)
    assert result["review_count"] <= 2
    assert "precision" not in result and "recall" not in result
    assert result["scope_note"].startswith("Hypothetical")
    assert "ceiling" in result["capacity_rounding"]


def test_model_threshold_constraint_is_visible_when_costs_favor_review():
    action, details = recommend(0.05, 0.20, PolicyCosts(false_positive=1, missed_event=100, manual_review=0.25))
    assert action == "allow_simulated"
    assert details["estimated_allow_cost"] > details["estimated_review_cost"]
    assert details["threshold_basis"] == "configured_model_threshold"
    assert details["policy"] == "threshold_constrained_cost_review"


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
    target_time = datetime.fromisoformat(target["timestamp"])
    app.state.store.add_transaction(TransactionCreate(
        transaction_id="foreign_incoming", timestamp=target_time - timedelta(minutes=5),
        sender_id="different_sender", receiver_id=target["receiver_id"], amount=5,
    ).model_dump(mode="python"))
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
    forged = dict(report)
    forged["evidence"] = [dict(item) for item in report["evidence"]]
    forged["evidence"][1]["statement"] = "999 prior sender transactions in the preceding 24 hours."
    forged["evidence"][1]["numeric_value"] = 999
    with pytest.raises(ValueError, match="stored tool result"):
        validate_report(forged, app.state.store)
    wrong_account = dict(report)
    wrong_account["evidence"] = [dict(item) for item in report["evidence"]]
    wrong_account["evidence"][1]["source_transaction_ids"] = ["foreign_incoming"]
    with pytest.raises(ValueError, match="different sender"):
        validate_report(wrong_account, app.state.store)
    assert client.get(f"/api/v1/investigations/{report['investigation_id']}").status_code == 200
    reviewed = client.post(f"/api/v1/cases/{report['investigation_id']}/review", json={"decision": "escalated", "analyst_note": "Reviewed sender history."})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_decision"] == "escalated"
    assert reviewed.json()["analyst_note"] == "Reviewed sender history."
    trace = client.get(f"/api/v1/investigations/{report['investigation_id']}/trace").json()["events"]
    assert any(event["event_type"] == "human_review_recorded" for event in trace)
    assert any(event["event_type"] == "tool_invocation" and event["details"].get("result_summary") for event in trace)
    reopened = client.get(f"/api/v1/investigations?transaction_id={target['transaction_id']}&limit=1").json()
    assert reopened["items"][0]["investigation_id"] == report["investigation_id"]
    assert client.get("/api/v1/monitoring/metrics").json()["investigation_count"] == 1


def test_api_policy_simulator_does_not_claim_supervised_metrics(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    response = client.post("/api/v1/policies/simulate", json={"probabilities": [.01, .6, .4], "alert_budget": .5})
    assert response.status_code == 200
    assert "expected_cost_with_policy" in response.json()
    assert "recall" not in response.json()


def test_policy_simulator_accepts_bounded_review_effectiveness(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    response = client.post("/api/v1/policies/simulate", json={
        "probabilities": [.1, .8], "review_effectiveness": .45,
    })
    assert response.status_code == 200
    assert response.json()["cost_assumptions"]["review_effectiveness_assumption"] == .45
    invalid = client.post("/api/v1/policies/simulate", json={"probabilities": [.1], "review_effectiveness": 1.1})
    assert invalid.status_code == 422


def test_model_unavailable_returns_explicit_503(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    assert client.get("/api/v1/health").json()["model_loaded"] is False
    assert client.post("/api/v1/risk/score", json={"transaction_id": "sim_41_00001"}).status_code == 503


def test_model_loader_rejects_same_names_without_exact_feature_version(tmp_path):
    import joblib

    path = tmp_path / "legacy.joblib"
    joblib.dump({"preprocessor": None, "model": None, "calibrator": None,
                 "features": MODEL_FEATURES, "decision_threshold": 0.5,
                 "alert_rate": 0.01, "model_version": "source-v1",
                 "feature_schema_version": "research-bbe7921-v1"}, path)
    artifact, error, _ = load_artifact(path, sha256_file(path))
    assert artifact is None
    assert FEATURE_SCHEMA_VERSION in error


def test_model_loader_requires_integrity_hash_and_reproducibility_manifest(tmp_path):
    import joblib

    path = tmp_path / "v2.joblib"
    manifest = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_code_commit": "a" * 40,
        "source_research_commit": "bbe79212099c9d81c74c643362d52c228db7db08",
        "label_definition": "Is_laundering == 1",
        "dataset_name": "authorized-evaluation-fixture",
        "dataset_sha256": "c" * 64,
        "training_config_sha256": "d" * 64,
        "split_definition": "chronological 70/10/10/10",
        "calibration_method": "logistic calibration",
        "validation_metrics": {"pr_auc": 0.5},
        "training_package_versions": {"numpy": "2.5.5"},
    }
    joblib.dump({"preprocessor": "preprocessor", "model": "model", "calibrator": "calibrator",
                 "features": MODEL_FEATURES, "feature_schema_version": FEATURE_SCHEMA_VERSION,
                 "decision_threshold": 0.5, "alert_rate": 0.01, "model_version": "v2-test",
                 "manifest": manifest}, path)
    artifact, error, _ = load_artifact(path)
    assert artifact is None and "RISKLENS_MODEL_SHA256 must" in error
    artifact, error, _ = load_artifact(path, sha256_file(path))
    assert error is None
    assert artifact["manifest"]["feature_schema_version"] == FEATURE_SCHEMA_VERSION


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


def test_api_cannot_forge_simulator_provenance(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    response = client.post("/api/v1/transactions", json={
        "transaction_id": "txn_source_1", "sender_id": "acct_1", "receiver_id": "acct_2",
        "amount": 10, "source": "simulator",
    })
    assert response.status_code == 201
    assert response.json()["transaction"]["source"] == "manual"
    assert response.json()["transaction"]["simulated"] is False
    client.app.state.store.record_prediction("txn_source_1", "test-model", 0.25, 2.0)
    listed = client.get("/api/v1/transactions?limit=1").json()["items"][0]
    assert listed["latest_probability"] == 0.25
    assert client.get("/api/v1/monitoring/metrics").json()["unique_scored_transactions"] == 1


def test_chunked_request_body_over_limit_is_rejected(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.joblib", tmp_path / "db.sqlite3"))
    chunks = iter([b" " * 600_000, b" " * 400_001])
    response = client.post("/api/v1/transactions", content=chunks, headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_online_counterparty_hhi_is_prior_value_share_by_payment_currency():
    now = datetime(2025, 5, 1, tzinfo=timezone.utc)
    history = [
        tx("hhi_b", now - timedelta(hours=2), amount=300).model_copy(update={"receiver_id": "receiver_b"}).model_dump(mode="json"),
        tx("hhi_c", now - timedelta(hours=1), amount=100).model_copy(update={"receiver_id": "receiver_c"}).model_dump(mode="json"),
        tx("hhi_eur", now - timedelta(minutes=30), amount=1000).model_copy(update={"receiver_id": "receiver_eur", "payment_currency": "EUR"}).model_dump(mode="json"),
    ]
    current = tx("hhi_current", now, amount=25).model_dump(mode="json")
    result = build_feature_vector(current, history)
    assert result["sender_counterparty_hhi"] == pytest.approx(0.625)


def test_online_features_cover_exact_window_boundaries_ties_and_missing_history():
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    current = tx("boundary_current", now, amount=200).model_dump(mode="json")
    history = [
        tx("boundary_24h", now - timedelta(hours=24), amount=100).model_dump(mode="json"),
        tx("boundary_30d", now - timedelta(days=30), amount=300).model_dump(mode="json"),
        tx("outside_30d", now - timedelta(days=30, seconds=1), amount=900).model_dump(mode="json"),
        tx("tie_current", now, amount=5000).model_dump(mode="json"),
    ]
    result = build_feature_vector(current, history)
    assert result["sender_txn_count_24h"] == 1
    assert result["sender_amount_mean_30d"] == pytest.approx(200)
    assert result["sender_amount_std_30d"] == pytest.approx(100 * 2**0.5)
    assert result["sender_txn_count_lifetime"] == 3
    empty = build_feature_vector(current, [])
    assert empty["sender_txn_count_24h"] == 0
    assert empty["sender_counterparty_hhi"] == 0


def test_all_online_feature_values_match_hand_checked_source_transform_fixture():
    now = datetime(2025, 3, 1, 12, tzinfo=timezone.utc)
    current = tx("parity_current", now, amount=250).model_copy(update={
        "receiver_id": "receiver_target", "received_currency": "EUR",
        "sender_location": "US", "receiver_location": "GB", "payment_type": "Card",
    }).model_dump(mode="json")
    history = [
        tx("parity_b0", now - timedelta(hours=24), amount=10).model_copy(update={"receiver_id": "receiver_b"}),
        tx("parity_b1", now - timedelta(hours=1), amount=20).model_copy(update={"receiver_id": "receiver_b"}),
        tx("parity_c", now - timedelta(hours=2), amount=30).model_copy(update={"receiver_id": "receiver_c"}),
        tx("parity_eur", now - timedelta(minutes=30), amount=999).model_copy(update={"receiver_id": "receiver_e", "payment_currency": "EUR", "received_currency": "EUR"}),
        tx("parity_incoming", now - timedelta(minutes=10), sender="other_sender", amount=5).model_copy(update={"receiver_id": "receiver_target", "received_currency": "EUR"}),
    ]
    vector = build_feature_vector(current, [row.model_dump(mode="json") for row in history])
    expected_numeric = {
        "Amount": 250.0, "log_amount": np.log1p(250.0),
        "hour_sin": 0.0, "hour_cos": -1.0,
        "dow_sin": np.sin(2 * np.pi * 5 / 7), "dow_cos": np.cos(2 * np.pi * 5 / 7),
        "month_sin": 1.0, "month_cos": 0.0,
        "is_weekend": 1, "is_night": 0, "currency_mismatch": 1, "cross_border": 1,
        "is_round_amount": 0, "sender_txn_count_24h": 3, "sender_amount_sum_24h": 60.0,
        "sender_amount_mean_30d": 20.0, "sender_amount_std_30d": 10.0,
        "sender_amount_zscore": 23.0, "receiver_txn_count_24h": 1,
        "receiver_amount_sum_24h": 5.0, "seconds_since_sender_txn": 1800,
        "sender_txn_count_lifetime": 4, "receiver_txn_count_lifetime": 1,
        "sender_out_degree": 3, "receiver_in_degree": 1,
        "pair_transaction_count": 0, "sender_counterparty_hhi": 0.5,
    }
    for feature, expected in expected_numeric.items():
        assert vector[feature] == pytest.approx(expected), feature
    assert {key: vector[key] for key in MODEL_FEATURES if key not in expected_numeric} == {
        "Payment_type": "Card", "Payment_currency": "USD", "Received_currency": "EUR",
        "Sender_bank_location": "US", "Receiver_bank_location": "GB",
    }


def test_investigation_eval_suite_reports_applicable_denominators():
    from app.evaluation import run_evaluation

    report = run_evaluation()
    assert report["scenario_count"] == 18
    assert report["metrics"]["report_valid"] == 1.0
    assert report["metrics"]["model_claims_absent"] == 1.0
    assert report["metrics"]["injection_text_excluded"] == 1.0
    assert report["metric_denominators"]["expected_indicator_found"] == 6
