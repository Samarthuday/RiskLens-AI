"""Online, point-in-time feature transformation compatible with research commit bbe7921."""

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

MODEL_FEATURES = [
    "Amount", "log_amount", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "is_weekend", "is_night", "currency_mismatch", "cross_border", "is_round_amount",
    "sender_txn_count_24h", "sender_amount_sum_24h", "sender_amount_mean_30d", "sender_amount_std_30d",
    "sender_amount_zscore", "receiver_txn_count_24h", "receiver_amount_sum_24h", "seconds_since_sender_txn",
    "sender_txn_count_lifetime", "receiver_txn_count_lifetime", "sender_out_degree", "receiver_in_degree",
    "pair_transaction_count", "sender_counterparty_hhi", "Payment_type", "Payment_currency",
    "Received_currency", "Sender_bank_location", "Receiver_bank_location",
]


def _parse_timestamp(value: str | datetime) -> datetime:
    ts = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def build_feature_vector(transaction: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Recreate current and historical features using only records before this transaction."""
    ts = _parse_timestamp(transaction["timestamp"])
    amt = float(transaction["amount"])
    hour, dow, month = ts.hour, ts.weekday(), ts.month
    prior = [(row, _parse_timestamp(row["timestamp"])) for row in history]
    prior = [(row, time) for row, time in prior if time < ts]

    sender_currency = [row for row, _ in prior if row["sender_id"] == transaction["sender_id"] and row["payment_currency"] == transaction["payment_currency"]]
    sender_24 = [row for row, time in prior if row["sender_id"] == transaction["sender_id"] and row["payment_currency"] == transaction["payment_currency"] and ts - timedelta(hours=24) <= time < ts]
    sender_30 = [row for row, time in prior if row["sender_id"] == transaction["sender_id"] and row["payment_currency"] == transaction["payment_currency"] and ts - timedelta(days=30) <= time < ts]
    receiver_24 = [row for row, time in prior if row["receiver_id"] == transaction["receiver_id"] and row["received_currency"] == transaction["received_currency"] and ts - timedelta(hours=24) <= time < ts]
    sender_all = [row for row, _ in prior if row["sender_id"] == transaction["sender_id"]]
    receiver_all = [row for row, _ in prior if row["receiver_id"] == transaction["receiver_id"]]
    pair_all = [row for row, _ in prior if row["sender_id"] == transaction["sender_id"] and row["receiver_id"] == transaction["receiver_id"]]
    amounts_30 = np.asarray([float(row["amount"]) for row in sender_30], dtype=float)
    # The pinned batch pipeline replaces null behavioral statistics with zero.
    mean_30 = float(amounts_30.mean()) if len(amounts_30) else 0.0
    std_30 = float(amounts_30.std(ddof=1)) if len(amounts_30) > 1 else 0.0
    zscore = (amt - mean_30) / std_30 if std_30 != 0 else 0.0
    previous_sender = [time for row, time in prior if row["sender_id"] == transaction["sender_id"]]
    since_previous = int((ts - max(previous_sender)).total_seconds()) if previous_sender else -1

    currency_pairs: dict[str, float] = defaultdict(float)
    for row in sender_currency:
        currency_pairs[row["receiver_id"]] += float(row["amount"])
    historical_total = sum(currency_pairs.values())
    hhi = sum((value / historical_total) ** 2 for value in currency_pairs.values()) if historical_total else 0.0

    vector = {
        "Amount": amt, "log_amount": math.log1p(amt),
        "hour_sin": math.sin(2 * math.pi * hour / 24), "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow_sin": math.sin(2 * math.pi * dow / 7), "dow_cos": math.cos(2 * math.pi * dow / 7),
        "month_sin": math.sin(2 * math.pi * month / 12), "month_cos": math.cos(2 * math.pi * month / 12),
        "is_weekend": int(dow >= 5), "is_night": int(hour >= 22 or hour <= 6),
        "currency_mismatch": int(transaction["payment_currency"] != transaction["received_currency"]),
        "cross_border": int(transaction["sender_location"] != transaction["receiver_location"]),
        "is_round_amount": int(np.isclose(amt % 1000, 0.0)),
        "sender_txn_count_24h": len(sender_24),
        "sender_amount_sum_24h": sum(float(row["amount"]) for row in sender_24),
        "sender_amount_mean_30d": mean_30, "sender_amount_std_30d": std_30,
        "sender_amount_zscore": float(zscore), "receiver_txn_count_24h": len(receiver_24),
        "receiver_amount_sum_24h": sum(float(row["amount"]) for row in receiver_24),
        "seconds_since_sender_txn": since_previous,
        "sender_txn_count_lifetime": len(sender_all), "receiver_txn_count_lifetime": len(receiver_all),
        "sender_out_degree": len({row["receiver_id"] for row in sender_all}),
        "receiver_in_degree": len({row["sender_id"] for row in receiver_all}),
        "pair_transaction_count": len(pair_all), "sender_counterparty_hhi": float(hhi),
        "Payment_type": transaction["payment_type"], "Payment_currency": transaction["payment_currency"],
        "Received_currency": transaction["received_currency"], "Sender_bank_location": transaction["sender_location"],
        "Receiver_bank_location": transaction["receiver_location"],
    }
    if list(vector) != MODEL_FEATURES:
        return {key: vector[key] for key in MODEL_FEATURES}
    return vector


def history_signals(vector: dict[str, Any]) -> list[str]:
    signals = []
    if vector["sender_txn_count_24h"] >= 5:
        signals.append(f"Sender has {vector['sender_txn_count_24h']} prior transactions in the 24-hour window.")
    if vector["sender_amount_std_30d"] > 0 and vector["sender_amount_zscore"] >= 3:
        signals.append(f"Amount is {vector['sender_amount_zscore']:.1f} sample standard deviations above the sender's prior 30-day mean.")
    if vector["sender_txn_count_lifetime"] and vector["pair_transaction_count"] == 0:
        signals.append("This sender–receiver pair has no prior observed transaction history.")
    if vector["seconds_since_sender_txn"] >= 0 and vector["seconds_since_sender_txn"] < 300:
        signals.append(f"Only {vector['seconds_since_sender_txn']} seconds elapsed since the sender's previous transaction.")
    if vector["currency_mismatch"]:
        signals.append("Payment and received currencies differ.")
    if vector["cross_border"]:
        signals.append("Sender and receiver bank locations differ.")
    return signals
