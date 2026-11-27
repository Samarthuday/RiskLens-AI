from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(default_factory=lambda: f"txn_{uuid4().hex[:12]}", min_length=4, max_length=64)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sender_id: str = Field(min_length=2, max_length=64)
    receiver_id: str = Field(min_length=2, max_length=64)
    amount: float = Field(gt=0, le=1_000_000_000)
    payment_currency: str = Field(default="USD", min_length=3, max_length=3)
    received_currency: str = Field(default="USD", min_length=3, max_length=3)
    sender_location: str = Field(default="US", min_length=2, max_length=8)
    receiver_location: str = Field(default="US", min_length=2, max_length=8)
    payment_type: str = Field(default="Transfer", max_length=32)
    description: str = Field(default="Synthetic demo transfer", max_length=500)
    source: Literal["simulator", "manual", "replay"] = "manual"

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @field_validator("payment_currency", "received_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class TransactionView(TransactionCreate):
    created_at: datetime
    simulated: bool = True


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=4, max_length=64)
    false_positive_cost: float = Field(default=1.0, ge=0)
    missed_fraud_cost: float = Field(default=100.0, ge=0)
    manual_review_cost: float = Field(default=0.25, ge=0)
    review_threshold: float | None = Field(default=None, gt=0, lt=1)


class EvidenceItem(BaseModel):
    evidence_id: str
    tool: str
    statement: str
    numeric_value: float | int | None = None
    source_transaction_ids: list[str] = Field(default_factory=list)


class Contribution(BaseModel):
    feature: str
    contribution: float
    direction: Literal["risk_increasing", "risk_decreasing"]


class InvestigationReport(BaseModel):
    investigation_id: str
    transaction_id: str
    created_at: datetime
    data_mode: Literal["synthetic_demo", "replay", "manual"]
    model_version: str | None = None
    model_risk_probability: float | None = Field(default=None, ge=0, le=1)
    model_risk_score: float | None = Field(default=None, ge=0, le=100, description="Operational display score (calibrated probability multiplied by 100).")
    risk_classification: Literal["low", "medium", "high", "critical", "unavailable"]
    contributions: list[Contribution] | None = None
    explanation_status: Literal["available", "unavailable", "not_requested"]
    evidence: list[EvidenceItem]
    supporting_indicators: list[str]
    counter_evidence: list[str]
    applied_policy: dict[str, float | str | int]
    unresolved_uncertainties: list[str]
    missing_information: list[str]
    recommended_action: Literal["allow_simulated", "request_verification", "manual_review", "simulated_hold", "insufficient_evidence"]
    rationale: str
    narrative_summary: str | None = None
    cited_evidence_ids: list[str] = Field(default_factory=list)
    llm_provider: str | None = None
    llm_latency_ms: float | None = None
    llm_token_usage: int | None = None
    llm_estimated_cost: float | None = None
    status: Literal["open", "reviewed"] = "open"
    human_review_required: bool = True
    review_decision: Literal["accepted", "dismissed", "escalated"] | None = None
    tool_calls: int = 0
    latency_ms: float = 0
    report_mode: Literal["deterministic_template", "llm_assisted"] = "deterministic_template"


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "dismissed", "escalated"]
    analyst_note: str = Field(default="", max_length=1000)


class TransactionScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=4, max_length=64)


class PolicySimulationRequest(BaseModel):
    probabilities: list[float] = Field(min_length=1, max_length=10000)
    alert_budget: float = Field(default=0.005, gt=0, le=1)
    false_positive_cost: float = Field(default=1.0, ge=0)
    missed_fraud_cost: float = Field(default=100.0, ge=0)
    manual_review_cost: float = Field(default=0.25, ge=0)

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(cls, values: list[float]) -> list[float]:
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("probabilities must be between 0 and 1")
        return values
