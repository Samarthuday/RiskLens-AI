"""Typed, bounded tool registry for deterministic investigation components."""

import time
from dataclasses import dataclass
from typing import Any, Callable, Type

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features import MODEL_FEATURES
from app.model import explain as explain_model
from app.model import score_with_version
from app.policy import PolicyCosts, recommend


class TransactionLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=4, max_length=64)


class FeatureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_vector: dict[str, Any]

    @field_validator("feature_vector")
    @classmethod
    def require_model_schema(cls, values: dict[str, Any]) -> dict[str, Any]:
        supplied = set(values)
        expected = set(MODEL_FEATURES)
        if supplied != expected:
            raise ValueError(f"feature vector schema mismatch: missing={sorted(expected-supplied)}, extra={sorted(supplied-expected)}")
        return values


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probability: float | None = Field(ge=0, le=1)
    threshold: float = Field(gt=0, lt=1)
    false_positive_cost: float = Field(ge=0)
    missed_fraud_cost: float = Field(ge=0)
    manual_review_cost: float = Field(ge=0)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: Type[BaseModel]
    handler: Callable[[dict], Any]


class ToolRegistry:
    """Explicit allow-list; bounded calls, validated arguments, no SQL/code/filesystem tool."""

    def __init__(self, max_calls: int = 8):
        self.max_calls = max_calls
        self.specs: dict[str, ToolSpec] = {}
        self.trace: list[dict[str, Any]] = []

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self.specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self.specs[spec.name] = spec

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.specs:
            raise ValueError(f"tool is not allow-listed: {name}")
        if len(self.trace) >= self.max_calls:
            raise RuntimeError("investigation tool-call limit reached")
        spec = self.specs[name]
        params = spec.input_model.model_validate(arguments)
        started = time.perf_counter()
        try:
            result = spec.handler(params.model_dump())
        except Exception as error:
            self.trace.append({"tool": name, "duration_ms": (time.perf_counter() - started) * 1000, "success": False, "error_type": type(error).__name__})
            raise
        self.trace.append({"tool": name, "duration_ms": (time.perf_counter() - started) * 1000, "success": True})
        return result


def build_tool_registry(store, artifact, review_threshold: float) -> ToolRegistry:
    registry = ToolRegistry(max_calls=8)

    def get_transaction(args):
        row = store.get_transaction(args["transaction_id"])
        if row is None:
            raise ValueError("transaction not found")
        return {key: row[key] for key in ("transaction_id", "timestamp", "sender_id", "receiver_id", "amount", "payment_currency", "received_currency", "sender_location", "receiver_location", "payment_type", "source")}

    def get_history(args):
        row = store.get_transaction(args["transaction_id"])
        if row is None:
            raise ValueError("transaction not found")
        return store.feature_history(row)

    def velocity(args):
        values = args["feature_vector"]
        return {key: values[key] for key in ("sender_txn_count_24h", "receiver_txn_count_24h", "seconds_since_sender_txn")}

    def deviation(args):
        values = args["feature_vector"]
        return {key: values[key] for key in ("sender_amount_mean_30d", "sender_amount_std_30d", "sender_amount_zscore")}

    def network(args):
        values = args["feature_vector"]
        return {key: values[key] for key in ("sender_txn_count_lifetime", "sender_out_degree", "receiver_in_degree", "pair_transaction_count", "sender_counterparty_hhi")}

    def score(args):
        probability, latency_ms, version = score_with_version(artifact, args["feature_vector"])
        return {"probability": probability, "latency_ms": latency_ms, "model_version": version}

    def explain(args):
        return explain_model(artifact, args["feature_vector"])

    def policy(args):
        return recommend(args["probability"], args["threshold"], PolicyCosts(args["false_positive_cost"], args["missed_fraud_cost"], args["manual_review_cost"]))

    for spec in (
        ToolSpec("get_transaction", "Retrieve allow-listed transaction fields.", TransactionLookup, get_transaction),
        ToolSpec("get_feature_history", "Retrieve only indexed sender/receiver records before the event.", TransactionLookup, get_history),
        ToolSpec("get_transaction_velocity", "Read calculated point-in-time velocity features.", FeatureInput, velocity),
        ToolSpec("calculate_statistical_deviation", "Read 30-day deviation features computed from prior history.", FeatureInput, deviation),
        ToolSpec("get_network_risk_features", "Read prior network counts and concentration features.", FeatureInput, network),
        ToolSpec("get_model_prediction", "Run calibrated inference when a compatible artifact exists.", FeatureInput, score),
        ToolSpec("compute_shap_contributions", "Calculate real SHAP contributions or return unavailable.", FeatureInput, explain),
        ToolSpec("evaluate_risk_policy", "Apply deterministic thresholds and explicit cost assumptions.", PolicyInput, policy),
    ):
        registry.register(spec)
    return registry
