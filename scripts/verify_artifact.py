"""Exercise actual preprocessing, estimator, calibration, and SHAP for a trusted artifact."""

import argparse
import json
import math
from pathlib import Path

from app.features import build_feature_vector
from app.model import explain, load_artifact, predict


def known_fixture() -> tuple[dict, list[dict]]:
    transaction = {
        "transaction_id": "artifact_smoke_current", "timestamp": "2025-01-15T12:00:00+00:00",
        "sender_id": "smoke_sender", "receiver_id": "smoke_receiver_new", "amount": 725.0,
        "payment_currency": "USD", "received_currency": "USD", "sender_location": "US",
        "receiver_location": "US", "payment_type": "Transfer",
    }
    history = [
        {**transaction, "transaction_id": f"artifact_smoke_{i}",
         "timestamp": f"2025-01-{day:02d}T12:00:00+00:00", "receiver_id": receiver,
         "amount": amount}
        for i, (day, receiver, amount) in enumerate(((2, "smoke_receiver_1", 90.0),
                                                     (4, "smoke_receiver_2", 115.0),
                                                     (7, "smoke_receiver_1", 105.0)))
    ]
    return transaction, history


def verify(path: Path, expected_sha256: str) -> dict:
    artifact, error, actual_sha256 = load_artifact(path, expected_sha256)
    if artifact is None:
        raise RuntimeError(error)
    transaction, history = known_fixture()
    vector = build_feature_vector(transaction, history)
    probability, latency_ms = predict(artifact, vector)
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise RuntimeError("Known fixture did not produce a finite probability in [0, 1].")
    contributions = explain(artifact, vector)
    if not contributions:
        raise RuntimeError("Known fixture did not produce a valid local SHAP explanation.")
    return {"status": "passed", "artifact_sha256": actual_sha256,
            "model_version": artifact["model_version"],
            "feature_schema_version": artifact["feature_schema_version"],
            "fixture_probability": probability, "decision_threshold": artifact["decision_threshold"],
            "model_inference_ms": latency_ms, "shap_contribution_count": len(contributions),
            "explanation_scale": "underlying estimator output; not additive in calibrated probability",
            "feature_warnings": ["Synthetic smoke fixture; verifies code path, not model quality."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.artifact, args.sha256), indent=2))


if __name__ == "__main__":
    main()
