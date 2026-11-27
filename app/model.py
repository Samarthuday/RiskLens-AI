"""Trusted, checksum-aware model artifact loading and inference."""

import hashlib
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import joblib
import pandas as pd

from app.features import MODEL_FEATURES


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
    if expected_sha256 and checksum.lower() != expected_sha256.lower():
        return None, "Model artifact SHA-256 does not match RISKLENS_MODEL_SHA256.", checksum
    try:
        artifact = joblib.load(path)
        required = {"preprocessor", "model", "calibrator", "features", "decision_threshold", "alert_rate", "model_version"}
        missing = required - artifact.keys()
        if missing:
            return None, f"Model artifact is missing required keys: {sorted(missing)}", checksum
        if artifact["features"] != MODEL_FEATURES:
            return None, "Model artifact feature schema does not match the pinned research schema.", checksum
        return artifact, None, checksum
    except Exception as error:
        return None, f"Model artifact could not be loaded: {type(error).__name__}: {error}", checksum


def compatibility_warnings(artifact: dict | None) -> list[str]:
    if artifact is None:
        return []
    package_map = {"numpy": "numpy", "pandas": "pandas", "scikit-learn": "scikit-learn", "xgboost": "xgboost", "joblib": "joblib"}
    trained = artifact.get("package_versions", {})
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
