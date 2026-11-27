"""Trusted, checksum-aware model artifact loading and inference."""

import hashlib
import json
import math
import re
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import joblib
import pandas as pd

from app.features import FEATURE_SCHEMA_VERSION, MODEL_FEATURES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_artifact(path: Path, expected_sha256: str | None = None) -> tuple[dict | None, str | None, str | None]:
    if not path.is_file():
        return None, "No trained model artifact installed.", None
    checksum = sha256_file(path)
    if not expected_sha256:
        return None, "RISKLENS_MODEL_SHA256 must be configured before loading a model artifact.", checksum
    if checksum.lower() != expected_sha256.lower():
        return None, "Model artifact SHA-256 does not match RISKLENS_MODEL_SHA256.", checksum
    try:
        artifact = joblib.load(path)
        required = {"preprocessor", "model", "calibrator", "features", "feature_schema_version", "decision_threshold", "alert_rate", "model_version"}
        missing = required - artifact.keys()
        if missing:
            return None, f"Model artifact is missing required keys: {sorted(missing)}", checksum
        if artifact["feature_schema_version"] != FEATURE_SCHEMA_VERSION or artifact["features"] != MODEL_FEATURES:
            return None, f"Model artifact must declare feature schema {FEATURE_SCHEMA_VERSION} with the exact ordered feature list.", checksum
        if "manifest" not in artifact:
            return None, "Model artifact must include the reproducibility manifest.", checksum
        manifest = artifact["manifest"]
        if not isinstance(manifest, dict):
            return None, "Model manifest must be a JSON-compatible object.", checksum
        manifest_fields = {"feature_schema_version", "training_code_commit", "source_research_commit", "label_definition", "dataset_name", "dataset_sha256", "training_config_sha256", "split_definition", "calibration_method", "validation_metrics", "training_package_versions"}
        missing_manifest = manifest_fields - manifest.keys()
        if missing_manifest:
            return None, f"Model manifest is missing required fields: {sorted(missing_manifest)}", checksum
        if manifest["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
            return None, "Model manifest feature schema does not match the application contract.", checksum
        pinned_source = json.loads((Path(__file__).resolve().parents[1] / "research/reported_metrics.json").read_text())["source_commit"]
        if manifest["source_research_commit"] != pinned_source:
            return None, "Model manifest does not reference the pinned research commit.", checksum
        if manifest["label_definition"] != "Is_laundering == 1":
            return None, "Model target must be explicitly defined as Is_laundering == 1.", checksum
        for key in ("training_code_commit", "source_research_commit"):
            if not isinstance(manifest[key], str) or not re.fullmatch(r"[0-9a-f]{40}", manifest[key]):
                return None, f"Model manifest has an invalid {key}.", checksum
        for key in ("dataset_sha256", "training_config_sha256"):
            if not isinstance(manifest[key], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest[key]):
                return None, f"Model manifest has an invalid {key}.", checksum
        for key in ("label_definition", "dataset_name", "split_definition", "calibration_method"):
            if not isinstance(manifest[key], str) or not manifest[key].strip():
                return None, f"Model manifest has an invalid {key}.", checksum
        if not isinstance(manifest["validation_metrics"], dict) or not manifest["validation_metrics"]:
            return None, "Model manifest must include validation metrics.", checksum
        if not isinstance(manifest["training_package_versions"], dict):
            return None, "Model manifest must include training package versions.", checksum
        if not isinstance(artifact["decision_threshold"], (int, float)) or not math.isfinite(artifact["decision_threshold"]) or not 0 < artifact["decision_threshold"] < 1:
            return None, "Model decision threshold must be between zero and one.", checksum
        if not isinstance(artifact["alert_rate"], (int, float)) or not math.isfinite(artifact["alert_rate"]) or not 0 <= artifact["alert_rate"] <= 1:
            return None, "Model alert rate must be between zero and one.", checksum
        if not isinstance(artifact["model_version"], str) or not artifact["model_version"].strip():
            return None, "Model version must be a non-empty string.", checksum
        if any(artifact[key] is None for key in ("preprocessor", "model", "calibrator")):
            return None, "Model artifact components cannot be null.", checksum
        return artifact, None, checksum
    except Exception as error:
        return None, f"Model artifact could not be loaded: {type(error).__name__}: {error}", checksum


def compatibility_warnings(artifact: dict | None) -> list[str]:
    if artifact is None:
        return []
    package_map = {"numpy": "numpy", "pandas": "pandas", "scikit-learn": "scikit-learn", "xgboost": "xgboost", "joblib": "joblib"}
    trained = artifact.get("package_versions", artifact.get("manifest", {}).get("training_package_versions", {}))
    warnings = []
    for recorded_name, package_name in package_map.items():
        source_version = trained.get(recorded_name)
        if not source_version:
            continue
        try:
            installed_version = version(package_name)
        except PackageNotFoundError:
            continue
        if installed_version != source_version:
            warnings.append(f"{package_name} runtime {installed_version} differs from artifact training version {source_version}.")
    return warnings


def predict(artifact: dict, vector: dict) -> tuple[float, float]:
    frame = pd.DataFrame([{name: vector[name] for name in artifact["features"]}])
    started = time.perf_counter()
    transformed = artifact["preprocessor"].transform(frame)
    raw_probability = artifact["model"].predict_proba(transformed)[:, 1]
    calibrated = float(artifact["calibrator"].predict(raw_probability)[0])
    return calibrated, (time.perf_counter() - started) * 1000


def score_with_version(artifact: dict | None, vector: dict) -> tuple[float | None, float, str | None]:
    if artifact is None:
        return None, 0.0, None
    probability, elapsed = predict(artifact, vector)
    return probability, elapsed, artifact.get("model_version", "unknown")


def explain(artifact: dict | None, vector: dict) -> list[dict] | None:
    if artifact is None:
        return None
    try:
        import numpy as np
        import pandas as pd
        import shap

        frame = pd.DataFrame([{name: vector[name] for name in artifact["features"]}])
        transformed = artifact["preprocessor"].transform(frame)
        values = np.asarray(shap.TreeExplainer(artifact["model"]).shap_values(transformed))
        contributions = values[0, :, -1] if values.ndim == 3 else values.reshape(-1)
        names = artifact["preprocessor"].get_feature_names_out().tolist()
        if len(names) != len(contributions) or not np.isfinite(contributions).all():
            return None
        order = np.argsort(np.abs(contributions))[::-1][:8]
        return [{"feature": names[index], "contribution": float(contributions[index]),
                 "direction": "risk_increasing" if contributions[index] > 0 else "risk_decreasing"}
                for index in order]
    except Exception:
        return None
