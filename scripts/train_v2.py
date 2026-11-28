"""Train and evaluate the RiskLens v2 AML model on a frozen temporal split."""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier

from app.features import FEATURE_SCHEMA_VERSION, MODEL_FEATURES
from src.models.calibration import ProbabilityCalibrator

ROOT = Path(__file__).resolve().parents[1]
TARGET = "Is_laundering"
NUMERIC = MODEL_FEATURES[:-5]
CATEGORICAL = MODEL_FEATURES[-5:]
DEFAULT_CONFIG = ROOT / "configs/training-v2.json"
DEFAULT_FEATURES = ROOT / "data/processed/risklens-causal-v2.parquet"
DEFAULT_OUTPUT = ROOT / "build/risk_model.joblib"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def temporal_split(frame: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, ...]:
    ordered = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    unique_times = ordered["timestamp"].drop_duplicates().to_numpy()
    train_fraction = float(config["train_fraction"])
    calibration_fraction = float(config["calibration_fraction"])
    validation_fraction = float(config["validation_fraction"])
    if min(train_fraction, calibration_fraction, validation_fraction) <= 0 or sum((train_fraction, calibration_fraction, validation_fraction)) >= 1:
        raise ValueError("Temporal fractions must be positive and leave a test period.")
    if len(unique_times) < 10:
        raise ValueError("At least ten distinct event timestamps are required for temporal splitting.")
    train_end = max(1, int(len(unique_times) * train_fraction))
    calibration_end = max(train_end + 1, int(len(unique_times) * (train_fraction + calibration_fraction)))
    validation_end = max(calibration_end + 1, int(len(unique_times) * (train_fraction + calibration_fraction + validation_fraction)))
    if validation_end >= len(unique_times):
        raise ValueError("Not enough distinct timestamps for four disjoint time periods.")
    train_cut, calibration_cut, validation_cut = unique_times[[train_end, calibration_end, validation_end]]
    train = ordered[ordered.timestamp < train_cut]
    calibration = ordered[(ordered.timestamp >= train_cut) & (ordered.timestamp < calibration_cut)]
    validation = ordered[(ordered.timestamp >= calibration_cut) & (ordered.timestamp < validation_cut)]
    test = ordered[ordered.timestamp >= validation_cut]
    return tuple(part.reset_index(drop=True) for part in (train, calibration, validation, test))


def build_preprocessor(config: dict) -> ColumnTransformer:
    numeric = Pipeline([("imputer", SimpleImputer(strategy=config["preprocessing"]["numeric_imputer"]))])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy=config["preprocessing"]["categorical_imputer"])),
        ("onehot", OneHotEncoder(handle_unknown=config["preprocessing"]["one_hot_handle_unknown"],
                                 min_frequency=config["preprocessing"]["one_hot_min_frequency"])),
    ])
    return ColumnTransformer([("numeric", numeric, NUMERIC), ("categorical", categorical, CATEGORICAL)], remainder="drop")


def top_k_mask(probabilities: np.ndarray, rate: float) -> np.ndarray:
    count = max(1, int(np.ceil(len(probabilities) * rate)))
    order = np.argsort(-probabilities, kind="stable")
    mask = np.zeros(len(probabilities), dtype=bool)
    mask[order[:count]] = True
    return mask


def threshold_at_alert_budget(probabilities: np.ndarray, rate: float) -> float:
    """Choose a score cutoff from this model's validation scores at the requested capacity."""
    values = np.asarray(probabilities, dtype=float)
    threshold = float(values[top_k_mask(values, rate)].min())
    return min(threshold, float(np.nextafter(1.0, 0.0)))


def metrics(y: np.ndarray, p: np.ndarray, threshold: float, alert_rate: float) -> dict:
    p = np.clip(np.asarray(p, dtype=float), 1e-8, 1 - 1e-8)
    y = np.asarray(y, dtype=int)
    alerts = p >= threshold
    top_alerts = top_k_mask(p, alert_rate)
    tp = int(np.sum(alerts & (y == 1)))
    fp = int(np.sum(alerts & (y == 0)))
    fn = int(np.sum(~alerts & (y == 1)))
    top_tp = int(np.sum(top_alerts & (y == 1)))
    return {
        "sample_count": int(len(y)), "positive_count": int(y.sum()),
        "prevalence": float(y.mean()), "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)), "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p)), "decision_threshold": float(threshold),
        "threshold_confusion": {"true_positive": tp, "false_positive": fp, "false_negative": fn,
                                "true_negative": int(len(y) - tp - fp - fn)},
        "threshold_alert_count": int(alerts.sum()),
        "realized_threshold_alert_rate": float(alerts.mean()),
        "threshold_precision": tp / (tp + fp) if tp + fp else 0.0,
        "threshold_recall": tp / (tp + fn) if tp + fn else 0.0,
        "alert_budget": alert_rate, "top_budget_alert_count": int(top_alerts.sum()),
        "recall_at_alert_budget": top_tp / int(y.sum()) if y.sum() else None,
    }


def block_bootstrap_ci(frame: pd.DataFrame, probabilities: np.ndarray, rate: float, seed: int, repeats: int = 100) -> dict:
    """Resample whole UTC calendar weeks to retain within-week dependence."""
    weeks = pd.to_datetime(frame.timestamp, utc=True).dt.tz_localize(None).dt.to_period("W").astype(str).to_numpy()
    unique_weeks = np.unique(weeks)
    buckets = [np.flatnonzero(weeks == week) for week in unique_weeks]
    rng = np.random.default_rng(seed)
    pr_values, recall_values = [], []
    y = frame[TARGET].to_numpy(dtype=int)
    for _ in range(repeats):
        selected = rng.integers(0, len(buckets), size=len(buckets))
        indices = np.concatenate([buckets[i] for i in selected])
        if np.unique(y[indices]).size < 2:
            continue
        p, labels = probabilities[indices], y[indices]
        pr_values.append(float(average_precision_score(labels, p)))
        alerts = top_k_mask(p, rate)
        positives = int(labels.sum())
        if positives:
            recall_values.append(float(np.sum(alerts & (labels == 1)) / positives))
    def interval(values):
        return {"lower_95": float(np.quantile(values, 0.025)), "upper_95": float(np.quantile(values, 0.975)),
                "valid_week_block_resamples": len(values)} if values else None
    return {"method": "calendar-week block bootstrap", "repeats_requested": repeats,
            "pr_auc": interval(pr_values), "recall_at_alert_budget": interval(recall_values)}


def group_metrics(frame: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> dict:
    enriched = frame[[TARGET, "Payment_currency", "sender_txn_count_lifetime"]].copy()
    enriched["cold_start"] = np.where(enriched.sender_txn_count_lifetime == 0, "no_prior_sender", "prior_sender_seen")
    output = {}
    for column in ("Payment_currency", "cold_start"):
        output[column] = {}
        for group, index in enriched.groupby(column, dropna=False).groups.items():
            indices = np.asarray(list(index), dtype=int)
            labels = enriched.loc[indices, TARGET].to_numpy(dtype=int)
            scores = probabilities[indices]
            result = {"sample_count": len(indices), "positive_count": int(labels.sum()),
                      "alert_count": int(np.sum(scores >= threshold))}
            if np.unique(labels).size == 2:
                result["pr_auc"] = float(average_precision_score(labels, scores))
                result["roc_auc"] = float(roc_auc_score(labels, scores))
            else:
                result["pr_auc"] = None
                result["roc_auc"] = None
            output[column][str(group)] = result
    return output


def train(features: Path, metadata_path: Path, config_path: Path, artifact_path: Path, report_path: Path) -> dict:
    metadata = json.loads(metadata_path.read_text())
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    if metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("Feature sidecar does not declare the required RiskLens v2 schema.")
    if metadata.get("dataset_sha256") is None or metadata.get("source_research_commit") != json.loads((ROOT / "research/reported_metrics.json").read_text())["source_commit"]:
        raise ValueError("Feature sidecar must bind the dataset fingerprint and pinned research commit.")
    frame = pd.read_parquet(features)
    missing = (set(MODEL_FEATURES) | {TARGET, "timestamp"}) - set(frame.columns)
    if missing:
        raise ValueError(f"Prepared v2 features are missing columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame.timestamp, errors="raise")
    frame[TARGET] = frame[TARGET].astype(int)
    if not set(frame[TARGET].unique()).issubset({0, 1}):
        raise ValueError("Training target must contain only binary Is_laundering labels.")
    train_frame, calibration, validation, test = temporal_split(frame, config)
    for label, part in (("train", train_frame), ("calibration", calibration), ("validation", validation), ("test", test)):
        if part.empty or part[TARGET].nunique() != 2:
            raise ValueError(f"Temporal {label} period must be non-empty and contain both label values.")

    preprocessor = build_preprocessor(config)
    x_train = preprocessor.fit_transform(train_frame[MODEL_FEATURES])
    x_cal = preprocessor.transform(calibration[MODEL_FEATURES])
    x_validation = preprocessor.transform(validation[MODEL_FEATURES])
    x_test = preprocessor.transform(test[MODEL_FEATURES])
    y_train = train_frame[TARGET].to_numpy(dtype=int)
    params = dict(config["xgboost"])
    params.update({"objective": "binary:logistic", "scale_pos_weight": float((len(y_train) - y_train.sum()) / y_train.sum()),
                   "n_jobs": -1, "random_state": int(config["random_state"])})
    model = XGBClassifier(**params)
    model.fit(x_train, y_train)
    y_cal = calibration[TARGET].to_numpy(dtype=int)
    calibrator = ProbabilityCalibrator().fit(model.predict_proba(x_cal)[:, 1], y_cal)
    validation_raw = model.predict_proba(x_validation)[:, 1]
    validation_probabilities = calibrator.predict(validation_raw)
    alert_rate = float(config["alert_rate"])
    threshold = threshold_at_alert_budget(validation_probabilities, alert_rate)
    test_probabilities = calibrator.predict(model.predict_proba(x_test)[:, 1])

    baseline = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=int(config["random_state"]))
    baseline.fit(x_train, y_train)
    baseline_calibrator = ProbabilityCalibrator().fit(baseline.predict_proba(x_cal)[:, 1], y_cal)
    baseline_validation_probabilities = baseline_calibrator.predict(baseline.predict_proba(x_validation)[:, 1])
    baseline_threshold = threshold_at_alert_budget(baseline_validation_probabilities, alert_rate)
    baseline_test_probabilities = baseline_calibrator.predict(baseline.predict_proba(x_test)[:, 1])
    test_metrics = metrics(test[TARGET].to_numpy(), test_probabilities, threshold, alert_rate)
    baseline_metrics = metrics(test[TARGET].to_numpy(), baseline_test_probabilities, baseline_threshold, alert_rate)
    bootstrap = block_bootstrap_ci(test, test_probabilities, alert_rate, int(config["random_state"]))

    try:
        code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("Training requires a committed code revision so the artifact records reproducible code.") from error
    if dirty or len(code_commit) != 40:
        raise RuntimeError("Commit the training code and configuration before building an artifact.")

    packages = {name: version(name) for name in ("numpy", "pandas", "scikit-learn", "xgboost", "duckdb", "pyarrow", "joblib")}
    counts = {}
    for name, part in (("train", train_frame), ("calibration", calibration), ("validation", validation), ("test", test)):
        counts[name] = {"sample_count": len(part), "positive_count": int(part[TARGET].sum()),
                        "prevalence": float(part[TARGET].mean()), "start": str(part.timestamp.min()), "end": str(part.timestamp.max())}
    manifest = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_code_commit": code_commit,
        "source_research_commit": metadata["source_research_commit"],
        "label_definition": "Is_laundering == 1",
        "dataset_name": metadata.get("dataset_name", "SAML-D"),
        "dataset_sha256": metadata["dataset_sha256"],
        "training_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "split_definition": "Distinct timestamp boundaries: chronological train/calibration/validation/test fractions from the frozen config; equal event timestamps never cross a boundary.",
        "calibration_method": config["calibration_method"],
        "validation_metrics": metrics(validation[TARGET].to_numpy(), validation_probabilities, threshold, alert_rate),
        "training_package_versions": packages,
    }
    artifact = {
        "preprocessor": preprocessor, "model": model, "calibrator": calibrator,
        "features": MODEL_FEATURES, "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "decision_threshold": threshold, "alert_rate": alert_rate,
        "test_metrics": test_metrics, "baseline_test_metrics": baseline_metrics,
        "baseline_decision_threshold": baseline_threshold,
        "test_confidence_intervals": bootstrap,
        "validation_probability_quantiles": [float(value) for value in np.quantile(validation_probabilities, np.linspace(0, 1, 1001))],
        "training_counts": counts, "training_config": config,
        "training_config_sha256": manifest["training_config_sha256"],
        "manifest": manifest, "package_versions": packages,
        "model_version": f"risklens-causal-v2-{code_commit[:10]}",
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    summary = {"model_version": artifact["model_version"], "artifact_path": str(artifact_path),
               "artifact_sha256": sha256_file(artifact_path), "feature_schema_version": FEATURE_SCHEMA_VERSION,
               "label_definition": manifest["label_definition"], "dataset_sha256": manifest["dataset_sha256"],
               "training_code_commit": code_commit, "training_config_sha256": manifest["training_config_sha256"],
               "split_counts": counts, "decision_threshold": threshold, "alert_rate": alert_rate,
               "baseline_decision_threshold": baseline_threshold,
               "test_metrics": test_metrics, "baseline_test_metrics": baseline_metrics,
               "test_confidence_intervals": bootstrap, "subgroup_metrics": group_metrics(test, test_probabilities, threshold),
               "training_package_versions": packages, "measured_at": datetime.now(timezone.utc).isoformat(),
               "data_license_notice": metadata.get("dataset_license_notice")}
    report_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=ROOT / "build/model-evaluation-v2.json")
    args = parser.parse_args()
    sidecar = args.features.with_suffix(args.features.suffix + ".manifest.json")
    print(json.dumps(train(args.features, sidecar, args.config, args.artifact, args.report), indent=2))


if __name__ == "__main__":
    main()
