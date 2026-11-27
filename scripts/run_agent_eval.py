#!/usr/bin/env python3
"""Backward-compatible entry point; evaluates a fixed workflow, not an autonomous agent."""
import json
from pathlib import Path

from app.evaluation import run_evaluation

if __name__ == "__main__":
    path = Path("evaluation/results/latest.json")
    result = run_evaluation(path)
    print(json.dumps({"output": str(path), "scenario_count": result["scenario_count"], "metrics": result["metrics"], "latency_ms": result["latency_ms"]}, indent=2))
