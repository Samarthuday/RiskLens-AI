import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or get_settings().database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, sender_id TEXT NOT NULL,
                    receiver_id TEXT NOT NULL, amount REAL NOT NULL CHECK(amount > 0),
                    payment_currency TEXT NOT NULL, received_currency TEXT NOT NULL,
                    sender_location TEXT NOT NULL, receiver_location TEXT NOT NULL,
                    payment_type TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_transactions_sender_time ON transactions(sender_id, timestamp);
                CREATE INDEX IF NOT EXISTS ix_transactions_receiver_time ON transactions(receiver_id, timestamp);
                CREATE TABLE IF NOT EXISTS investigations (
                    investigation_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
                    created_at TEXT NOT NULL, report_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_investigations_transaction ON investigations(transaction_id, created_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, investigation_id TEXT,
                    transaction_id TEXT, event_type TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT NOT NULL,
                    model_version TEXT NOT NULL, probability REAL NOT NULL, inference_ms REAL NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def _iso(value: datetime | None = None) -> str:
        return (value or datetime.now(timezone.utc)).isoformat()

    def add_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        row["timestamp"] = self._iso(row["timestamp"] if isinstance(row["timestamp"], datetime) else datetime.fromisoformat(row["timestamp"]))
        row["created_at"] = self._iso()
        with self.connect() as db:
            db.execute("""INSERT INTO transactions VALUES (:transaction_id,:timestamp,:sender_id,:receiver_id,:amount,
                :payment_currency,:received_currency,:sender_location,:receiver_location,:payment_type,:description,:source,:created_at)""", row)
        return row

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        return dict(row) if row else None

    def list_transactions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("""SELECT t.*,
                (SELECT p.probability FROM predictions p WHERE p.transaction_id=t.transaction_id ORDER BY p.prediction_id DESC LIMIT 1) AS latest_probability
                FROM transactions t ORDER BY t.timestamp DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def history(self, *, before: str, sender_id: str | None = None, receiver_id: str | None = None) -> list[dict[str, Any]]:
        column, identity = ("sender_id", sender_id) if sender_id is not None else ("receiver_id", receiver_id)
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM transactions WHERE {column}=? AND timestamp<? ORDER BY timestamp", (identity, before)).fetchall()
        return [dict(row) for row in rows]

    def feature_history(self, transaction: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch only the event's sender and receiver histories using indexed lookups."""
        before = transaction["timestamp"]
        with self.connect() as db:
            sender_rows = db.execute(
                "SELECT * FROM transactions WHERE sender_id=? AND timestamp<? ORDER BY timestamp",
                (transaction["sender_id"], before),
            ).fetchall()
            receiver_rows = db.execute(
                "SELECT * FROM transactions WHERE receiver_id=? AND timestamp<? ORDER BY timestamp",
                (transaction["receiver_id"], before),
            ).fetchall()
        unique = {row["transaction_id"]: dict(row) for row in [*sender_rows, *receiver_rows]}
        return sorted(unique.values(), key=lambda row: row["timestamp"])

    def save_investigation(self, report: dict[str, Any]) -> None:
        created_at = self._iso(datetime.fromisoformat(report["created_at"]) if isinstance(report["created_at"], str) else report["created_at"])
        with self.connect() as db:
            db.execute("INSERT INTO investigations VALUES (?,?,?,?)", (report["investigation_id"], report["transaction_id"], created_at, json.dumps(report)))
        self.audit(report["investigation_id"], report["transaction_id"], "investigation_created", {"status": report["status"], "risk_classification": report["risk_classification"]})

    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT report_json FROM investigations WHERE investigation_id=?", (investigation_id,)).fetchone()
        return json.loads(row["report_json"]) if row else None

    def list_investigations(self, limit: int = 100, transaction_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if transaction_id:
                rows = db.execute("SELECT report_json FROM investigations WHERE transaction_id=? ORDER BY created_at DESC LIMIT ?", (transaction_id, limit)).fetchall()
            else:
                rows = db.execute("SELECT report_json FROM investigations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row["report_json"]) for row in rows]

    def investigation_trace(self, investigation_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT event_type,details_json,created_at FROM audit_events WHERE investigation_id=? AND event_type IN ('workflow_stage','workflow_complete','llm_fallback','investigation_created','tool_invocation','human_review_recorded') ORDER BY event_id", (investigation_id,)).fetchall()
        return [{"event_type": row["event_type"], "details": json.loads(row["details_json"]), "created_at": row["created_at"]} for row in rows]

    def update_investigation(self, report: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("UPDATE investigations SET report_json=? WHERE investigation_id=?", (json.dumps(report), report["investigation_id"]))

    def audit(self, investigation_id: str | None, transaction_id: str | None, event_type: str, details: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit_events (investigation_id,transaction_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)", (investigation_id, transaction_id, event_type, json.dumps(details), self._iso()))

    def record_prediction(self, transaction_id: str, model_version: str, probability: float, inference_ms: float) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO predictions (transaction_id,model_version,probability,inference_ms,created_at) VALUES (?,?,?,?,?)", (transaction_id, model_version, probability, inference_ms, self._iso()))

    def monitoring_summary(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS count, AVG(inference_ms) AS mean_ms, MAX(inference_ms) AS max_ms FROM predictions").fetchone()
            unique_scored = db.execute("SELECT COUNT(DISTINCT transaction_id) FROM predictions").fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            cases = db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
            reviewed_cases = db.execute("SELECT COUNT(*) FROM investigations WHERE json_extract(report_json,'$.status')='reviewed'").fetchone()[0]
            investigation_latencies = [row[0] for row in db.execute("SELECT CAST(json_extract(report_json,'$.latency_ms') AS REAL) FROM investigations ORDER BY CAST(json_extract(report_json,'$.latency_ms') AS REAL)") if row[0] is not None]
            events = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        p95_index = min(len(investigation_latencies) - 1, int(len(investigation_latencies) * 0.95)) if investigation_latencies else None
        return {"predictions_recorded": row["count"], "unique_scored_transactions": unique_scored, "transaction_count": total, "investigation_count": cases, "reviewed_case_count": reviewed_cases, "open_case_count": cases - reviewed_cases, "investigation_latency_p95_ms": investigation_latencies[p95_index] if p95_index is not None else None, "audit_event_count": events, "mean_inference_ms": row["mean_ms"], "max_inference_ms": row["max_ms"], "label_monitoring": "unavailable: no adjudicated outcome labels recorded"}

    def reset_simulated_transactions(self) -> int:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT transaction_id FROM transactions WHERE source='simulator'")]
            if ids:
                marks = ",".join("?" for _ in ids)
                db.execute(f"DELETE FROM investigations WHERE transaction_id IN ({marks})", ids)
                db.execute(f"DELETE FROM predictions WHERE transaction_id IN ({marks})", ids)
                db.execute(f"DELETE FROM transactions WHERE transaction_id IN ({marks})", ids)
        self.audit(None, None, "demo_transactions_reset", {"removed_transactions": len(ids)})
        return len(ids)
