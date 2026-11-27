"""Deterministic risk policy and cost-sensitive alert-budget simulation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyCosts:
    false_positive: float = 1.0
    missed_event: float = 100.0
    manual_review: float = 0.25
    review_effectiveness: float = 0.80


def cost_optimal_review_threshold(costs: PolicyCosts) -> float:
    """Break-even p where review beats allow under an explicit review-effectiveness assumption."""
    denominator = costs.review_effectiveness * costs.missed_event + costs.false_positive
    if denominator <= 0:
        return 1.0
    return min(1.0, max(0.0, (costs.manual_review + costs.false_positive) / denominator))


def recommend(probability: float | None, threshold: float, costs: PolicyCosts) -> tuple[str, dict[str, float | str]]:
    if probability is None:
        return "insufficient_evidence", {"policy": "unavailable_without_model_probability", "threshold": threshold}
    break_even = cost_optimal_review_threshold(costs)
    review_threshold = max(threshold, break_even)
    threshold_basis = "configured_model_threshold" if threshold >= break_even else "cost_break_even_threshold"
    allow_cost = probability * costs.missed_event
    review_cost = costs.manual_review + (1 - probability) * costs.false_positive + probability * (1 - costs.review_effectiveness) * costs.missed_event
    if probability < review_threshold:
        return "allow_simulated", {"policy": "threshold_constrained_cost_review", "threshold": review_threshold, "model_threshold": threshold, "cost_break_even_threshold": break_even, "threshold_basis": threshold_basis, "estimated_allow_cost": allow_cost, "estimated_review_cost": review_cost, "cost_unit": "user-defined abstract units"}
    return "manual_review", {"policy": "threshold_constrained_cost_review", "threshold": review_threshold, "model_threshold": threshold, "cost_break_even_threshold": break_even, "threshold_basis": threshold_basis, "estimated_allow_cost": allow_cost, "estimated_review_cost": review_cost, "cost_unit": "user-defined abstract units"}


def simulate_policy(probabilities: list[float], alert_budget: float, costs: PolicyCosts) -> dict:
    """Estimate costs without labels; never report precision/recall from probabilities alone."""
    ranked = sorted(range(len(probabilities)), key=lambda index: (-probabilities[index], index))
    capacity = max(1, int(len(probabilities) * alert_budget + 0.999999))
    break_even = cost_optimal_review_threshold(costs)
    candidates = [index for index in ranked[:capacity] if probabilities[index] >= break_even]
    reviewed = set(candidates)
    expected_before = sum(p * costs.missed_event for p in probabilities)
    expected_after = 0.0
    for index, probability in enumerate(probabilities):
        if index in reviewed:
            expected_after += costs.manual_review + (1 - probability) * costs.false_positive + probability * (1 - costs.review_effectiveness) * costs.missed_event
        else:
            expected_after += probability * costs.missed_event
    return {
        "population": len(probabilities), "alert_capacity": capacity, "review_count": len(reviewed),
        "review_fraction": len(reviewed) / len(probabilities), "cost_optimal_threshold": break_even,
        "expected_cost_without_review": expected_before, "expected_cost_with_policy": expected_after,
        "estimated_cost_difference": expected_before - expected_after,
        "cost_assumptions": {"false_positive_cost": costs.false_positive, "missed_event_cost": costs.missed_event, "manual_review_cost": costs.manual_review, "review_effectiveness_assumption": costs.review_effectiveness, "cost_unit": "user-defined abstract units"},
        "capacity_rounding": "alert_capacity uses ceiling(population × alert_budget), with a minimum capacity of one",
        "scope_note": "Hypothetical expected cost from model probabilities and user assumptions; no outcomes or realized losses are present.",
    }
