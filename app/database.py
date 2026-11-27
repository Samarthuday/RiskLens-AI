import hashlib
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

ACTIVE_SESSION_ID: ContextVar[str | None] = ContextVar("risklens_session_id", default=None)


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or get_settings().database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized_paths: set[Path] = set()
        self._initialize()

    def session_path(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode()).hexdigest()
        return self.path.parent / "sessions" / f"{digest}.sqlite3"

    @staticmethod
    @contextmanager
    def base_scope():
        token = ACTIVE_SESSION_ID.set(None)
        try:
            yield
        finally:
            ACTIVE_SESSION_ID.reset(token)

    def prune_expired_sessions(self, max_age_seconds: int = 30 * 24 * 60 * 60,
                               max_sessions: int = 500, preserve_session_id: str | None = None) -> int:
        directory = self.path.parent / "sessions"
        if not directory.exists():
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
        removed = 0
        preserve = self.session_path(preserve_session_id) if preserve_session_id else None

        def discard(candidate: Path) -> None:
            candidate.unlink(missing_ok=True)
            candidate.with_name(candidate.name + "-wal").unlink(missing_ok=True)
            candidate.with_name(candidate.name + "-shm").unlink(missing_ok=True)

        files = list(directory.glob("*.sqlite3"))
        for candidate in files:
            try:
                if candidate != preserve and candidate.stat().st_mtime < cutoff:
                    discard(candidate)
                    removed += 1
            except OSError:
                continue
        files = sorted(directory.glob("*.sqlite3"), key=lambda item: item.stat().st_mtime)
        while len(files) > max_sessions:
            candidate = next((item for item in files if item != preserve), None)
            if candidate is None:
                break
            try:
                discard(candidate)
                files.remove(candidate)
                removed += 1
            except OSError:
                break
        return removed

    def connect(self) -> sqlite3.Connection:
        session_id = ACTIVE_SESSION_ID.get()
        target = self.session_path(session_id) if session_id else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(target, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if target not in self._initialized_paths:
            self._initialize_connection(db)
            self._initialized_paths.add(target)
        return db

    def _initialize(self) -> None:
        with self.connect():
            pass

    def _initialize_connection(self, db: sqlite3.Connection) -> None:
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
                CREATE INDEX IF NOT EXISTS ix_predictions_transaction ON predictions(transaction_id, prediction_id);
                CREATE TABLE IF NOT EXISTS request_observations (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS razorpay_events (
                    provider_event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payment_id TEXT NOT NULL,
                    order_id TEXT,
                    amount_subunits INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    payment_method TEXT,
                    payment_status TEXT NOT NULL,
                    event_created_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_razorpay_events_payment ON razorpay_events(payment_id, event_created_at);
                CREATE TABLE IF NOT EXISTS razorpay_payments (
                    payment_id TEXT PRIMARY KEY,
                    order_id TEXT,
                    amount_subunits INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    payment_method TEXT,
                    payment_status TEXT NOT NULL,
                    latest_event_created_at TEXT NOT NULL,
                    latest_received_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL
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
            rows = db.execute("""
                SELECT t.*, p.probability AS model_probability, p.model_version AS scored_model_version,
                       p.created_at AS scored_at, i.investigation_id,
                       json_extract(i.report_json, '$.status') AS case_status,
                       json_extract(i.report_json, '$.review_decision') AS review_decision,
                       p.probability AS latest_probability
                FROM transactions t
                LEFT JOIN predictions p ON p.prediction_id = (
                    SELECT prediction_id FROM predictions WHERE transaction_id=t.transaction_id
                    ORDER BY prediction_id DESC LIMIT 1
                )
                LEFT JOIN investigations i ON i.investigation_id = (
                    SELECT investigation_id FROM investigations WHERE transaction_id=t.transaction_id
                    ORDER BY created_at DESC, investigation_id DESC LIMIT 1
                )
                ORDER BY t.timestamp DESC, t.transaction_id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def transaction_history(self, transaction: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], int]:
        """Return bounded, strictly earlier activity for either party."""
        before = transaction["timestamp"]
        with self.connect() as db:
            rows = db.execute("""
                SELECT * FROM transactions
                WHERE timestamp < ? AND (sender_id = ? OR receiver_id = ?)
                ORDER BY timestamp DESC, transaction_id DESC LIMIT ?
            """, (before, transaction["sender_id"], transaction["receiver_id"], limit)).fetchall()
            total = db.execute("""
                SELECT COUNT(*) FROM transactions
                WHERE timestamp < ? AND (sender_id = ? OR receiver_id = ?)
            """, (before, transaction["sender_id"], transaction["receiver_id"])).fetchone()[0]
        return [dict(row) for row in rows], total

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
            rows = db.execute("SELECT event_id,event_type,details_json,created_at FROM audit_events WHERE investigation_id=? ORDER BY event_id", (investigation_id,)).fetchall()
        return [{"event_id": row["event_id"], "event_type": row["event_type"], "details": json.loads(row["details_json"]), "created_at": row["created_at"]} for row in rows]

    def record_review(self, investigation_id: str, decision: str, analyst_note: str) -> dict[str, Any] | None:
        """Commit a disposition, its note, and the audit event together."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT report_json FROM investigations WHERE investigation_id=?", (investigation_id,)).fetchone()
            if row is None:
                return None
            report = json.loads(row["report_json"])
            reviewed_at = self._iso()
            review = {"decision": decision, "analyst_note": analyst_note, "reviewed_at": reviewed_at}
            report.update(status="reviewed", review_decision=decision, analyst_note=analyst_note, reviewed_at=reviewed_at)
            report.setdefault("review_history", []).append(review)
            db.execute("UPDATE investigations SET report_json=? WHERE investigation_id=?", (json.dumps(report), investigation_id))
            db.execute("INSERT INTO audit_events (investigation_id,transaction_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)",
                       (investigation_id, report["transaction_id"], "human_review_recorded", json.dumps(review), reviewed_at))
        return report

    def update_investigation(self, report: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("UPDATE investigations SET report_json=? WHERE investigation_id=?", (json.dumps(report), report["investigation_id"]))

    def audit(self, investigation_id: str | None, transaction_id: str | None, event_type: str, details: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit_events (investigation_id,transaction_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)", (investigation_id, transaction_id, event_type, json.dumps(details), self._iso()))

    def record_prediction(self, transaction_id: str, model_version: str, probability: float, inference_ms: float) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO predictions (transaction_id,model_version,probability,inference_ms,created_at) VALUES (?,?,?,?,?)", (transaction_id, model_version, probability, inference_ms, self._iso()))

    def record_request(self, route: str, status_code: int, duration_ms: float) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO request_observations (route,status_code,duration_ms,created_at) VALUES (?,?,?,?)",
                       (route, status_code, duration_ms, self._iso()))

    def accept_razorpay_event(self, event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Atomically deduplicate a verified provider event and advance its payment view."""
        event_created_at = datetime.fromtimestamp(event["event_created_at"], timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM razorpay_events WHERE provider_event_id=?",
                                  (event["provider_event_id"],)).fetchone()
            if previous:
                snapshot = db.execute("SELECT * FROM razorpay_payments WHERE payment_id=?",
                                      (event["payment_id"],)).fetchone()
                return False, dict(snapshot) if snapshot else {"payment_id": event["payment_id"]}
            db.execute("""INSERT INTO razorpay_events VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                event["provider_event_id"], event["event_type"], event["payment_id"], event["order_id"],
                event["amount_subunits"], event["currency"], event["payment_method"], event["payment_status"],
                event_created_at, event["received_at"], event["payload_sha256"],
            ))
            existing = db.execute("SELECT * FROM razorpay_payments WHERE payment_id=?",
                                  (event["payment_id"],)).fetchone()
            should_advance = existing is None
            if existing:
                current_time = datetime.fromisoformat(existing["latest_event_created_at"])
                incoming_time = datetime.fromisoformat(event_created_at)
                current_status = existing["payment_status"]
                incoming_status = event["payment_status"]
                current_rank = {"created": 0, "attempted": 0, "failed": 1, "authorized": 2, "captured": 3}.get(current_status, 0)
                incoming_rank = {"created": 0, "attempted": 0, "failed": 1, "authorized": 2, "captured": 3}.get(incoming_status, 0)
                is_captured_terminal = current_status == "captured" and incoming_status != "captured"
                should_advance = not is_captured_terminal and (incoming_time > current_time or (incoming_time == current_time and incoming_rank >= current_rank))
            if existing is None:
                db.execute("""INSERT INTO razorpay_payments VALUES (?,?,?,?,?,?,?,?,1)""", (
                    event["payment_id"], event["order_id"], event["amount_subunits"], event["currency"],
                    event["payment_method"], event["payment_status"], event_created_at, event["received_at"],
                ))
            else:
                db.execute("UPDATE razorpay_payments SET event_count=event_count+1 WHERE payment_id=?",
                           (event["payment_id"],))
                if should_advance:
                    db.execute("""UPDATE razorpay_payments SET order_id=?,amount_subunits=?,currency=?,payment_method=?,
                        payment_status=?,latest_event_created_at=?,latest_received_at=? WHERE payment_id=?""", (
                        event["order_id"], event["amount_subunits"], event["currency"], event["payment_method"],
                        event["payment_status"], event_created_at, event["received_at"], event["payment_id"],
                    ))
            snapshot = db.execute("SELECT * FROM razorpay_payments WHERE payment_id=?",
                                  (event["payment_id"],)).fetchone()
        return True, dict(snapshot)

    def list_razorpay_payments(self, limit: int = 100, status: str | None = None,
                               currency: str | None = None, method: str | None = None,
                               query: str | None = None) -> tuple[list[dict[str, Any]], int]:
        where, params = [], []
        if status:
            where.append("payment_status=?")
            params.append(status)
        if currency:
            where.append("currency=?")
            params.append(currency.upper())
        if method:
            where.append("payment_method=?")
            params.append(method)
        if query:
            where.append("(payment_id LIKE ? OR order_id LIKE ?)")
            params.extend((f"%{query}%", f"%{query}%"))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM razorpay_payments" + clause, params).fetchone()[0]
            rows = db.execute("SELECT * FROM razorpay_payments" + clause +
                              " ORDER BY latest_event_created_at DESC, payment_id DESC LIMIT ?",
                              (*params, limit)).fetchall()
        return [dict(row) for row in rows], total

    def list_razorpay_events(self, payment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("""SELECT provider_event_id,event_type,payment_id,order_id,amount_subunits,currency,
                payment_method,payment_status,event_created_at,received_at FROM razorpay_events WHERE payment_id=?
                ORDER BY event_created_at DESC, provider_event_id DESC LIMIT ?""", (payment_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def monitoring_summary(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS count, AVG(inference_ms) AS mean_ms, MAX(inference_ms) AS max_ms FROM predictions").fetchone()
            unique_scored = db.execute("SELECT COUNT(DISTINCT transaction_id) FROM predictions").fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            cases = db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
            reviewed_cases = db.execute("SELECT COUNT(*) FROM investigations WHERE json_extract(report_json,'$.status')='reviewed'").fetchone()[0]
            open_cases = db.execute("SELECT COUNT(*) FROM investigations WHERE json_extract(report_json,'$.status')='open'").fetchone()[0]
            escalated_cases = db.execute("SELECT COUNT(*) FROM investigations WHERE json_extract(report_json,'$.review_decision')='escalated'").fetchone()[0]
            investigation_latencies = [row[0] for row in db.execute("SELECT CAST(json_extract(report_json,'$.latency_ms') AS REAL) FROM investigations ORDER BY CAST(json_extract(report_json,'$.latency_ms') AS REAL)") if row[0] is not None]
            events = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            tool_failures = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='tool_invocation' AND json_extract(details_json,'$.success')=0").fetchone()[0]
            llm_fallbacks = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='llm_fallback'").fetchone()[0]
            llm_stats = db.execute("SELECT COALESCE(SUM(CAST(json_extract(report_json,'$.llm_token_usage') AS INTEGER)),0), COALESCE(SUM(CAST(json_extract(report_json,'$.llm_estimated_cost') AS REAL)),0) FROM investigations").fetchone()
            abstentions = db.execute("SELECT COUNT(*) FROM investigations WHERE json_extract(report_json,'$.model_risk_probability') IS NULL").fetchone()[0]
            request_row = db.execute("SELECT COUNT(*) AS count, SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS failures FROM request_observations").fetchone()
            request_latencies = [row[0] for row in db.execute("SELECT duration_ms FROM request_observations WHERE route='/api/v1/investigations' ORDER BY duration_ms")]
        p95_index = min(len(investigation_latencies) - 1, int(len(investigation_latencies) * 0.95)) if investigation_latencies else None
        request_count = request_row["count"]
        request_failures = request_row["failures"] or 0
        full_flow_p95_index = min(len(request_latencies) - 1, int(len(request_latencies) * 0.95)) if request_latencies else None
        full_flow_p50_index = int((len(request_latencies) - 1) * 0.5) if request_latencies else None
        return {"predictions_recorded": row["count"], "unique_scored_transactions": unique_scored, "unique_transactions_scored": unique_scored, "transaction_count": total, "investigation_count": cases, "reviewed_case_count": reviewed_cases, "reviewed_cases": reviewed_cases, "open_case_count": open_cases, "open_cases": open_cases, "escalated_cases": escalated_cases, "abstention_count": abstentions, "investigation_latency_p95_ms": investigation_latencies[p95_index] if p95_index is not None else None, "full_flow_investigation_p50_ms": request_latencies[full_flow_p50_index] if full_flow_p50_index is not None else None, "full_flow_investigation_p95_ms": request_latencies[full_flow_p95_index] if full_flow_p95_index is not None else None, "request_count": request_count, "request_failure_count": request_failures, "request_failure_rate": request_failures / request_count if request_count else None, "tool_failure_count": tool_failures, "llm_fallback_count": llm_fallbacks, "llm_token_usage": llm_stats[0], "llm_estimated_cost": llm_stats[1], "audit_event_count": events, "mean_inference_ms": row["mean_ms"], "max_inference_ms": row["max_ms"], "label_monitoring": "unavailable: no adjudicated outcome labels recorded"}

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
