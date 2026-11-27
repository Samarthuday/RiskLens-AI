#!/usr/bin/env python3
"""Run the deterministic investigation integrity evaluation."""

import json
from pathlib import Path

from app.evaluation import run_evaluation

if __name__ == "__main__":
    path = Path("evaluation/results/latest.json")
    result = run_evaluation(path)
    print(json.dumps({
        "output": str(path),
        "scenario_count": result["scenario_count"],
        "metrics": result["metrics"],
        "metric_denominators": result["metric_denominators"],
        "latency_ms": result["latency_ms"],
    }, indent=2))
