import csv
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.features import build_feature_vector
from scripts.build_training_features import build_features
from scripts.train_v2 import metrics, temporal_split, threshold_at_alert_budget, top_k_mask


def test_v2_batch_feature_builder_matches_online_point_in_time_contract(tmp_path):
    source = tmp_path / "tiny.csv"
    output = tmp_path / "features.parquet"
    rows = [
        ["09:00:00", "2025-01-01", "sender_a", "receiver_1", "100", "USD", "USD", "US", "US", "Transfer", "0", "Normal"],
        ["09:00:00", "2025-01-01", "sender_a", "receiver_2", "50", "USD", "USD", "US", "US", "Transfer", "0", "Normal"],
        ["10:00:00", "2025-01-01", "sender_a", "receiver_3", "200", "USD", "USD", "US", "US", "Transfer", "1", "Suspicious"],
        ["10:00:00", "2025-01-01", "sender_a", "receiver_4", "300", "USD", "USD", "US", "US", "Transfer", "0", "Normal"],
    ]
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Time", "Date", "Sender_account", "Receiver_account", "Amount", "Payment_currency", "Received_currency", "Sender_bank_location", "Receiver_bank_location", "Payment_type", "Is_laundering", "Laundering_type"])
        writer.writerows(rows)
    manifest = build_features(source, output)
    frame = pd.read_parquet(output)
    online = build_feature_vector({
        "timestamp": "2025-01-01T10:00:00+00:00", "sender_id": "sender_a", "receiver_id": "receiver_3",
        "amount": 200, "payment_currency": "USD", "received_currency": "USD",
        "sender_location": "US", "receiver_location": "US", "payment_type": "Transfer",
    }, [
        {"timestamp": "2025-01-01T09:00:00+00:00", "sender_id": "sender_a", "receiver_id": "receiver_1", "amount": 100, "payment_currency": "USD", "received_currency": "USD", "sender_location": "US", "receiver_location": "US", "payment_type": "Transfer"},
        {"timestamp": "2025-01-01T09:00:00+00:00", "sender_id": "sender_a", "receiver_id": "receiver_2", "amount": 50, "payment_currency": "USD", "received_currency": "USD", "sender_location": "US", "receiver_location": "US", "payment_type": "Transfer"},
        # Equal-time rows must not leak into this transaction's prior history.
        {"timestamp": "2025-01-01T10:00:00+00:00", "sender_id": "sender_a", "receiver_id": "receiver_4", "amount": 300, "payment_currency": "USD", "received_currency": "USD", "sender_location": "US", "receiver_location": "US", "payment_type": "Transfer"},
    ])
    actual = frame.loc[frame["Amount"] == 200].iloc[0]
    for feature in online:
        value = actual[feature]
        if isinstance(value, (int, float, np.number)):
            assert value == pytest.approx(online[feature], abs=1e-8)
        else:
            assert value == online[feature]
    assert actual["Is_laundering"] == 1
    assert manifest["feature_schema_version"] == "risklens-causal-v2"
    assert manifest["timestamp_tie_policy"].startswith("All same-timestamp")
    assert json.loads(output.with_suffix(".parquet.manifest.json").read_text())["dataset_sha256"] == manifest["dataset_sha256"]


def test_temporal_split_keeps_equal_timestamps_in_one_partition():
    times = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(20)]
    frame = pd.DataFrame({"timestamp": times + [times[8]], "Is_laundering": [i % 2 for i in range(20)] + [0]})
    config = {"train_fraction": .6, "calibration_fraction": .1, "validation_fraction": .1}
    parts = temporal_split(frame, config)
    memberships = {}
    for index, part in enumerate(parts):
        for timestamp in part.timestamp:
            assert timestamp not in memberships or memberships[timestamp] == index
            memberships[timestamp] = index
    assert len(memberships) == len(times)


def test_threshold_metrics_and_top_k_counts_are_explicit():
    probabilities = np.array([.1, .9, .4, .8])
    labels = np.array([0, 1, 0, 1])
    mask = top_k_mask(probabilities, .5)
    assert mask.tolist() == [False, True, False, True]
    result = metrics(labels, probabilities, .8, .5)
    assert result["threshold_confusion"] == {"true_positive": 2, "false_positive": 0, "false_negative": 0, "true_negative": 2}
    assert result["recall_at_alert_budget"] == 1
    assert result["threshold_alert_count"] == 2
    assert result["realized_threshold_alert_rate"] == .5


def test_each_model_selects_its_threshold_from_its_own_validation_scores():
    xgboost_validation = np.array([.95, .80, .25, .10])
    baseline_validation = np.array([.61, .60, .59, .58])
    xgboost_threshold = threshold_at_alert_budget(xgboost_validation, .25)
    baseline_threshold = threshold_at_alert_budget(baseline_validation, .25)

    assert xgboost_threshold == .95
    assert baseline_threshold == .61
    assert xgboost_threshold != baseline_threshold
    test_result = metrics(np.array([1, 0, 1, 0]), baseline_validation, baseline_threshold, .25)
    assert test_result["decision_threshold"] == baseline_threshold
    assert test_result["realized_threshold_alert_rate"] == .25
