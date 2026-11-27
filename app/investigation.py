"""Bounded, deterministic investigation workflow over typed local tools."""

import re
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np

from app.config import get_settings
from app.features import build_feature_vector, history_signals
from app.llm import OpenAICompatibleProvider, validate_narrative
from app.schemas import InvestigationReport
from app.tools import build_tool_registry

ALLOWED_TOOLS = {
    "get_transaction", "get_feature_history", "get_transaction_velocity",
    "calculate_statistical_deviation", "get_network_risk_features",
    "get_model_prediction", "compute_shap_contributions", "evaluate_risk_policy",
}


def validate_report(report: dict, store) -> None:
    """Validate report structure, evidence references, and model claims before persistence."""
    validated = InvestigationReport.model_validate(report)
    evidence_ids = [item.evidence_id for item in validated.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence identifiers must be unique")
    model_evidence = [item for item in validated.evidence if item.tool == "get_model_prediction"]
    if validated.model_risk_probability is None:
        if validated.risk_classification != "unavailable" or validated.recommended_action != "insufficient_evidence" or validated.contributions is not None:
            raise ValueError("model-unavailable report contains unsupported model outputs")
    elif len(model_evidence) != 1 or not np.isclose(model_evidence[0].numeric_value, validated.model_risk_probability):
        raise ValueError("probability must match the retrieved model evidence")
    elif validated.model_risk_score is None or not np.isclose(validated.model_risk_score, validated.model_risk_probability * 100):
        raise ValueError("display score must be calibrated probability multiplied by 100")
    trace_events = store.investigation_trace(validated.investigation_id)
    tool_calls = {event["details"].get("call_id"): event["details"] for event in trace_events if event["event_type"] == "tool_invocation"}
    claim_contracts = {
        "transaction_amount": ("get_transaction", "amount"),
        "sender_velocity_24h": ("get_transaction_velocity", "sender_txn_count_24h"),
        "sender_amount_zscore": ("calculate_statistical_deviation", "sender_amount_zscore"),
        "sender_out_degree": ("get_network_risk_features", "sender_out_degree"),
        "pair_transaction_count": ("get_network_risk_features", "pair_transaction_count"),
        "calibrated_probability": ("get_model_prediction", "probability"),
    }
    current = store.get_transaction(validated.transaction_id)
    if current is None:
        raise ValueError("investigation transaction is missing")
    current_time = datetime.fromisoformat(current["timestamp"])
    for item in validated.evidence:
        if item.tool not in ALLOWED_TOOLS:
            raise ValueError(f"unregistered evidence tool: {item.tool}")
        if any(store.get_transaction(source_id) is None for source_id in item.source_transaction_ids):
            raise ValueError(f"evidence {item.evidence_id} references a missing transaction")
        call = tool_calls.get(item.tool_call_id)
        if call is None or call.get("tool") != item.tool or not call.get("success"):
            raise ValueError(f"evidence {item.evidence_id} is not bound to a successful matching tool call")
        source_call = tool_calls.get(item.source_call_id or item.tool_call_id)
        if source_call is None:
            raise ValueError(f"evidence {item.evidence_id} has no retrieved source record")
        if source_call.get("tool") == "get_feature_history":
            retrieved_history = store.feature_history(current)
            if source_call.get("result_summary", {}).get("record_count") != len(retrieved_history):
                raise ValueError(f"evidence {item.evidence_id} history result changed after retrieval")
            source_ids = {row["transaction_id"] for row in retrieved_history}
        else:
            source_ids = set(source_call.get("result_summary", {}).get("transaction_ids", []))
        if not set(item.source_transaction_ids).issubset(source_ids):
            raise ValueError(f"evidence {item.evidence_id} cites records outside its retrieved result")
        if item.claim_key:
            contract = claim_contracts.get(item.claim_key)
            if contract is None:
                raise ValueError(f"unsupported evidence claim key: {item.claim_key}")
            expected_tool, result_key = contract
            if call["tool"] != expected_tool or result_key not in call.get("result_summary", {}):
                raise ValueError(f"evidence {item.evidence_id} does not match its tool result")
            expected_value = call["result_summary"][result_key]
            if item.numeric_value is None or expected_value is None or not np.isclose(float(item.numeric_value), float(expected_value), rtol=1e-8, atol=1e-10):
                raise ValueError(f"evidence {item.evidence_id} numeric value does not match the stored tool result")
            source_rows = [store.get_transaction(source_id) for source_id in item.source_transaction_ids]
            for row in source_rows:
                row_time = datetime.fromisoformat(row["timestamp"])
                if row_time >= current_time and item.claim_key not in {"transaction_amount", "calibrated_probability"}:
                    raise ValueError(f"evidence {item.evidence_id} cites a same-time or future transaction")
                if item.claim_key in {"sender_velocity_24h", "sender_amount_zscore", "sender_out_degree", "pair_transaction_count"} and row["sender_id"] != current["sender_id"]:
                    raise ValueError(f"evidence {item.evidence_id} cites a different sender")
                if item.claim_key == "sender_velocity_24h" and (row["payment_currency"] != current["payment_currency"] or row_time < current_time - timedelta(hours=24)):
                    raise ValueError(f"evidence {item.evidence_id} cites a transaction outside the velocity window")
                if item.claim_key == "sender_amount_zscore" and (row["payment_currency"] != current["payment_currency"] or row_time < current_time - timedelta(days=30)):
                    raise ValueError(f"evidence {item.evidence_id} cites a transaction outside the deviation window")
                if item.claim_key == "pair_transaction_count" and row["receiver_id"] != current["receiver_id"]:
                    raise ValueError(f"evidence {item.evidence_id} cites a different sender-receiver pair")
            if item.claim_key == "sender_velocity_24h" and int(item.numeric_value) != len(source_rows):
                raise ValueError(f"evidence {item.evidence_id} count does not match its cited records")
            if item.claim_key == "pair_transaction_count" and int(item.numeric_value) != len(source_rows):
                raise ValueError(f"evidence {item.evidence_id} count does not match its cited records")
            if item.claim_key == "sender_out_degree" and int(item.numeric_value) != len({row["receiver_id"] for row in source_rows}):
                raise ValueError(f"evidence {item.evidence_id} degree does not match its cited records")
        if item.numeric_value is not None and "unavailable" not in item.statement.lower():
            claims = [float(value) for value in re.findall(r"(?<![A-Za-z])(-?\d+(?:\.\d+)?)", item.statement)]
            if not any(np.isclose(value, item.numeric_value, rtol=1e-5, atol=5e-4) for value in claims):
                raise ValueError(f"numeric claim in {item.evidence_id} does not match its tool output")
    if validated.cited_evidence_ids and not set(validated.cited_evidence_ids).issubset(evidence_ids):
        raise ValueError("report cites evidence that was not retrieved")
    if validated.narrative_summary:
        try:
            validate_narrative(validated.narrative_summary, validated.cited_evidence_ids, set(evidence_ids))
        except ValueError as error:
            raise ValueError(f"invalid AI narrative: {error}") from error


def investigate(store, transaction: dict, artifact: dict | None, request) -> dict:
    started = time.perf_counter()
    created = datetime.now(timezone.utc)
    investigation_id = f"inv_{uuid4().hex[:12]}"
    timestamp = transaction["timestamp"]
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "validate_request", "status": "completed"})
    review_threshold = request.review_threshold if request.review_threshold is not None else (float(artifact["decision_threshold"]) if artifact is not None else 0.5)
    registry = build_tool_registry(store, artifact, review_threshold=review_threshold)
    stage_start = time.perf_counter()
    transaction_data = registry.call("get_transaction", {"transaction_id": transaction["transaction_id"]})
    history = registry.call("get_feature_history", {"transaction_id": transaction["transaction_id"]})
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "retrieve_history", "status": "completed", "duration_ms": (time.perf_counter() - stage_start) * 1000})
    stage_start = time.perf_counter()
    vector = build_feature_vector(transaction_data, history)
    indicators = history_signals(vector)
    velocity = registry.call("get_transaction_velocity", {"feature_vector": vector})
    deviation = registry.call("calculate_statistical_deviation", {"feature_vector": vector})
    network = registry.call("get_network_risk_features", {"feature_vector": vector})
    current_time = datetime.fromisoformat(timestamp)
    sender_24_records = [row for row in history if row["sender_id"] == transaction["sender_id"] and row["payment_currency"] == transaction["payment_currency"] and current_time - timedelta(hours=24) <= datetime.fromisoformat(row["timestamp"]) < current_time]
    sender_30_records = [row for row in history if row["sender_id"] == transaction["sender_id"] and row["payment_currency"] == transaction["payment_currency"] and current_time - timedelta(days=30) <= datetime.fromisoformat(row["timestamp"]) < current_time]
    sender_records = [row for row in history if row["sender_id"] == transaction["sender_id"]]
    pair_records = [row for row in history if row["sender_id"] == transaction["sender_id"] and row["receiver_id"] == transaction["receiver_id"]]
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "compute_features", "status": "completed", "duration_ms": (time.perf_counter() - stage_start) * 1000})
    evidence = [
        {"evidence_id": "E-01", "tool": "get_transaction", "statement": f"Synthetic transaction amount is {transaction_data['amount']:.2f} {transaction_data['payment_currency']}.", "numeric_value": float(transaction_data["amount"]), "source_transaction_ids": [transaction_data["transaction_id"]], "tool_call_id": "TC-01", "source_call_id": "TC-01", "claim_key": "transaction_amount"},
        {"evidence_id": "E-02", "tool": "get_transaction_velocity", "statement": f"{velocity['sender_txn_count_24h']} prior sender transactions in the preceding 24 hours.", "numeric_value": int(velocity["sender_txn_count_24h"]), "source_transaction_ids": [row["transaction_id"] for row in sender_24_records], "tool_call_id": "TC-03", "source_call_id": "TC-02", "claim_key": "sender_velocity_24h"},
        {"evidence_id": "E-03", "tool": "calculate_statistical_deviation", "statement": "Sender amount z-score against the prior 30-day history is unavailable." if deviation["sender_amount_std_30d"] == 0 else f"Sender amount z-score against prior 30-day history is {deviation['sender_amount_zscore']:.3f}.", "numeric_value": float(deviation["sender_amount_zscore"]), "source_transaction_ids": [row["transaction_id"] for row in sender_30_records], "tool_call_id": "TC-04", "source_call_id": "TC-02", "claim_key": "sender_amount_zscore"},
        {"evidence_id": "E-04", "tool": "get_network_risk_features", "statement": f"Prior sender out-degree is {network['sender_out_degree']}.", "numeric_value": int(network["sender_out_degree"]), "source_transaction_ids": [row["transaction_id"] for row in sender_records], "tool_call_id": "TC-05", "source_call_id": "TC-02", "claim_key": "sender_out_degree"},
        {"evidence_id": "E-05", "tool": "get_network_risk_features", "statement": f"Historical transaction count for this sender-receiver pair is {network['pair_transaction_count']}.", "numeric_value": int(network["pair_transaction_count"]), "source_transaction_ids": [row["transaction_id"] for row in pair_records], "tool_call_id": "TC-05", "source_call_id": "TC-02", "claim_key": "pair_transaction_count"},
    ]
    if vector["sender_txn_count_24h"] == 0:
        evidence[1]["source_transaction_ids"] = []
    stage_start = time.perf_counter()
    score_result = registry.call("get_model_prediction", {"feature_vector": vector})
    probability, inference_ms, model_version = score_result["probability"], score_result["latency_ms"], score_result["model_version"]
    explanations = registry.call("compute_shap_contributions", {"feature_vector": vector})
    action, policy = registry.call("evaluate_risk_policy", {
        "probability": probability, "threshold": review_threshold,
        "false_positive_cost": request.false_positive_cost,
        "missed_event_cost": request.missed_event_cost,
        "manual_review_cost": request.manual_review_cost,
    })
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "score_and_explain", "status": "completed", "duration_ms": (time.perf_counter() - stage_start) * 1000, "model_loaded": artifact is not None, "explanation_available": explanations is not None})
    if probability is not None:
        evidence.append({"evidence_id": "E-06", "tool": "get_model_prediction", "statement": f"Calibrated model probability is {probability:.6f}; model version {model_version}.", "numeric_value": probability, "source_transaction_ids": [transaction["transaction_id"]], "tool_call_id": "TC-06", "source_call_id": "TC-01", "claim_key": "calibrated_probability"})
        if explanations is not None:
            evidence.append({"evidence_id": "E-07", "tool": "compute_shap_contributions", "statement": "Local SHAP feature contributions were calculated from the loaded model.", "numeric_value": None, "source_transaction_ids": [transaction["transaction_id"]], "tool_call_id": "TC-07", "source_call_id": "TC-01"})
        store.record_prediction(transaction["transaction_id"], model_version or "unknown", probability, inference_ms)
        risk_class = "critical" if probability >= 0.5 else "high" if probability >= 0.2 else "medium" if probability >= 0.05 else "low"
        explanation_status = "available" if explanations is not None else "unavailable"
        missing = [] if vector["sender_txn_count_lifetime"] else ["No prior sender history was available."]
        uncertainties = ["Model probability is not proof of fraud.", "The simulator has no adjudicated outcomes or realized loss labels."]
        rationale = f"The calibrated score is {probability:.1%}; the deterministic cost-sensitive policy recommends {action.replace('_', ' ')}. A human must review the supporting evidence."
    else:
        risk_class = "unavailable"
        action = "insufficient_evidence"
        policy = {"policy": "unavailable_without_model_probability", "threshold": review_threshold}
        explanation_status = "unavailable"
        missing = ["A trusted, compatible trained model artifact is not installed.", "No adjudicated labels or independent fraud evidence are available in the synthetic demo."]
        uncertainties = ["The deterministic indicators are screening signals, not a suspicious-activity probability.", "No conclusion about laundering, fraud, or intent can be made without an appropriate validated model and human review."]
        rationale = "The trained model artifact is unavailable, so no probability or model attribution was generated. The synthetic history can be inspected, but evidence is insufficient for a model-based risk recommendation."
    counter_evidence = []
    if vector["sender_txn_count_24h"] < 5:
        counter_evidence.append("Observed sender velocity is below the demo investigation rule of five prior transactions in 24 hours.")
    if vector["sender_amount_zscore"] <= 1:
        counter_evidence.append("Observed amount is not more than one standard deviation above the sender's prior 30-day mean, where history permits comparison.")
    report = InvestigationReport(
        investigation_id=investigation_id, transaction_id=transaction["transaction_id"], created_at=created,
        data_mode="synthetic_demo" if transaction["source"] == "simulator" else transaction["source"],
        model_version=model_version, model_risk_probability=probability,
        model_risk_score=(probability * 100 if probability is not None else None),
        risk_classification=risk_class, contributions=explanations, explanation_status=explanation_status,
        evidence=evidence, supporting_indicators=indicators, counter_evidence=counter_evidence,
        applied_policy={**policy, "false_positive_cost": request.false_positive_cost,
                        "missed_event_cost": request.missed_event_cost,
                        "manual_review_cost": request.manual_review_cost},
        unresolved_uncertainties=uncertainties, missing_information=missing,
        recommended_action=action, rationale=rationale, tool_calls=len(registry.trace),
        latency_ms=(time.perf_counter() - started) * 1000,
    ).model_dump(mode="json")
    settings = get_settings()
    if transaction["source"] == "simulator" and settings.allow_synthetic_llm and settings.llm_base_url and settings.llm_api_key and settings.llm_model:
        try:
            synthesis = OpenAICompatibleProvider(settings.llm_base_url, settings.llm_api_key, settings.llm_model).synthesize(evidence)
            report.update({"narrative_summary": synthesis["summary"], "cited_evidence_ids": synthesis["evidence_ids"],
                           "llm_provider": synthesis["provider"], "llm_latency_ms": synthesis["latency_ms"],
                           "llm_token_usage": synthesis["token_usage"], "llm_estimated_cost": synthesis["estimated_cost"],
                           "report_mode": "llm_assisted"})
        except Exception as error:
            store.audit(investigation_id, transaction["transaction_id"], "llm_fallback", {"error_type": type(error).__name__})
    report["latency_ms"] = (time.perf_counter() - started) * 1000
    stage_start = time.perf_counter()
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "evaluate_policy", "status": "completed", "recommendation": action})
    for call in registry.trace:
        store.audit(investigation_id, transaction["transaction_id"], "tool_invocation", call)
    validate_report(report, store)
    store.audit(investigation_id, transaction["transaction_id"], "workflow_stage", {"stage": "validate_report", "status": "completed", "duration_ms": (time.perf_counter() - stage_start) * 1000})
    store.save_investigation(report)
    return report
