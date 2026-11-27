"""Measure actual feature transformation latency on reproducible synthetic records."""

import json
import platform
import statistics
import time
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.features import build_feature_vector
from app.model import load_artifact, predict
from app.simulator import Simulator


def main():
    settings = get_settings()
    artifact, error, checksum = load_artifact(settings.model_path, settings.model_sha256)
    records = [record.model_dump(mode="json") for record in Simulator(settings.demo_seed).reset("burst", 36)]
    timings = []
    vectors = []
    for index, transaction in enumerate(records):
        start = time.perf_counter()
        vector = build_feature_vector(transaction, records[:index])
        timings.append((time.perf_counter() - start) * 1000)
        vectors.append(vector)
    prediction_timings = []
    if artifact:
        for vector in vectors:
            _probability, elapsed = predict(artifact, vector)
            prediction_timings.append(elapsed)
    report = {
        "benchmark": "synthetic feature transformation and optional model inference",
        "python": platform.python_version(), "platform": platform.platform(),
        "record_count": len(records), "feature_latency_ms": {
            "mean": statistics.mean(timings), "p50": float(np.percentile(timings, 50)),
            "p95": float(np.percentile(timings, 95)), "max": max(timings)},
        "model_loaded": artifact is not None, "model_error": error, "artifact_sha256": checksum,
        "model_inference_latency_ms": ({"mean": statistics.mean(prediction_timings),
            "p50": float(np.percentile(prediction_timings, 50)),
            "p95": float(np.percentile(prediction_timings, 95))} if prediction_timings else None),
        "limitation": "Single-process local microbenchmark; not a production throughput or service latency claim.",
    }
    output = Path("evaluation/results/benchmark.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
