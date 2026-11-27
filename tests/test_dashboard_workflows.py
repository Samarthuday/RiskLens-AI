from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import TransactionCreate


def workspace(tmp_path):
    app = create_app(tmp_path / "missing.joblib", tmp_path / "workspace.sqlite3")
    return app, TestClient(app)


def test_review_note_and_revisions_survive_reopen_and_appear_in_trace(tmp_path):
    app, client = workspace(tmp_path)
    client.post("/api/v1/simulation/reset?count=36")
    transaction = client.get("/api/v1/transactions").json()["items"][0]
    case = client.post("/api/v1/investigations", json={"transaction_id": transaction["transaction_id"]}).json()
    path = f"/api/v1/cases/{case['investigation_id']}/review"
    first = client.post(path, json={"decision": "escalated", "analyst_note": "  Confirm merchant activity.  "})
    assert first.status_code == 200
    assert first.json()["analyst_note"] == "Confirm merchant activity."
    client.post(path, json={"decision": "dismissed", "analyst_note": "Merchant activity verified."})
    reopened = TestClient(create_app(tmp_path / "missing.joblib", app.state.store.path))
    saved = reopened.get(f"/api/v1/investigations/{case['investigation_id']}").json()
    assert saved["review_decision"] == "dismissed"
    assert saved["reviewed_at"]
    assert [row["analyst_note"] for row in saved["review_history"]] == [
        "Confirm merchant activity.", "Merchant activity verified."
    ]
    trace = reopened.get(f"/api/v1/investigations/{case['investigation_id']}/trace").json()["events"]
    reviews = [e for e in trace if e["event_type"] == "human_review_recorded"]
    assert len(reviews) == 2
    assert reviews[0]["details"]["analyst_note"] == "Confirm merchant activity."
    assert reviews[0]["event_id"] < reviews[1]["event_id"]
    metrics = reopened.get("/api/v1/monitoring/metrics").json()
    assert metrics["reviewed_cases"] == 1
    assert metrics["open_cases"] == 0
    assert metrics["escalated_cases"] == 0


def test_transaction_queue_retains_latest_prediction_and_case_after_reload(tmp_path):
    app, client = workspace(tmp_path)
    client.post("/api/v1/simulation/reset?count=4")
    transaction = client.get("/api/v1/transactions").json()["items"][0]
    transaction_id = transaction["transaction_id"]
    # Persist test observations directly: this verifies storage behavior, not model accuracy.
    app.state.store.record_prediction(transaction_id, "test-observation-v1", .1, 2.0)
    app.state.store.record_prediction(transaction_id, "test-observation-v2", .2, 3.0)
    case = client.post("/api/v1/investigations", json={"transaction_id": transaction_id}).json()
    client.post(f"/api/v1/cases/{case['investigation_id']}/review", json={"decision": "escalated", "analyst_note": "Needs context."})
    listing = client.get("/api/v1/transactions?limit=1").json()
    assert listing["total"] == 4
    assert listing["count"] == 1
    latest = listing["items"][0]
    assert latest["model_probability"] == .2
    assert latest["scored_model_version"] == "test-observation-v2"
    assert latest["investigation_id"] == case["investigation_id"]
    assert latest["case_status"] == "reviewed"
    assert latest["review_decision"] == "escalated"
    metrics = client.get("/api/v1/monitoring/metrics").json()
    assert metrics["predictions_recorded"] == 2
    assert metrics["unique_transactions_scored"] == 1


def test_account_history_excludes_current_future_and_unrelated_records(tmp_path):
    app, client = workspace(tmp_path)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = [
        ("history_early", -2, "sender_a", "other_receiver"),
        ("history_receiver", -1, "other_sender", "receiver_a"),
        ("current_event", 0, "sender_a", "receiver_a"),
        ("future_event", 1, "sender_a", "receiver_a"),
        ("unrelated_event", -1, "unrelated_sender", "unrelated_receiver"),
        ("tied_event", 0, "sender_a", "receiver_a"),
    ]
    for transaction_id, hour, sender, receiver in records:
        record = TransactionCreate(transaction_id=transaction_id, timestamp=base + timedelta(hours=hour),
                                   sender_id=sender, receiver_id=receiver, amount=10)
        app.state.store.add_transaction(record.model_dump(mode="python"))
    history = client.get("/api/v1/transactions/current_event/history?limit=1").json()
    assert history["total"] == 2
    assert [r["transaction_id"] for r in history["items"]] == ["history_receiver"]
    assert client.get("/api/v1/transactions/nonexistent/history").status_code == 404
    assert client.get("/api/v1/transactions/current_event/history?limit=101").status_code == 422


def test_dashboard_assets_are_served_and_missing_review_does_not_create_audit(tmp_path):
    app, client = workspace(tmp_path)
    for path, marker in [("/", "Risk overview"), ("/app.js", "renderOverview"), ("/styles.css", ".sidebar")]:
        response = client.get(path)
        assert response.status_code == 200
        if path != "/":
            assert marker in response.text
    before = app.state.store.monitoring_summary()["audit_event_count"]
    assert client.post("/api/v1/cases/missing/review", json={"decision": "dismissed"}).status_code == 404
    assert app.state.store.monitoring_summary()["audit_event_count"] == before
