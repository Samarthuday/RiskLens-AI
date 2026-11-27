"""Build SAML-D point-in-time features under the RiskLens v2 batch contract."""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from app.features import FEATURE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "bbe79212099c9d81c74c643362d52c228db7db08"

FEATURE_QUERY = r"""
WITH raw AS (
  SELECT
    CAST(strptime("Date" || ' ' || "Time", '%Y-%m-%d %H:%M:%S') AS TIMESTAMP) AS timestamp,
    CAST(Sender_account AS VARCHAR) AS Sender_account,
    CAST(Receiver_account AS VARCHAR) AS Receiver_account,
    CAST(Amount AS DOUBLE) AS Amount,
    CAST(Payment_currency AS VARCHAR) AS Payment_currency,
    CAST(Received_currency AS VARCHAR) AS Received_currency,
    CAST(Sender_bank_location AS VARCHAR) AS Sender_bank_location,
    CAST(Receiver_bank_location AS VARCHAR) AS Receiver_bank_location,
    CAST(Payment_type AS VARCHAR) AS Payment_type,
    CAST(Is_laundering AS TINYINT) AS Is_laundering
  FROM read_csv_auto(__RAW_PATH__, header=true, all_varchar=true)
),
base AS (
  SELECT *,
    hour(timestamp) AS hour_of_day,
    dayofweek(timestamp) AS duck_day_of_week,
    month(timestamp) AS month_of_year
  FROM raw
  WHERE timestamp IS NOT NULL AND Amount IS NOT NULL
),
history AS (
  SELECT *,
    COUNT(*) OVER (PARTITION BY Sender_account, Payment_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 24 HOURS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS sender_txn_count_24h,
    COALESCE(SUM(Amount) OVER (PARTITION BY Sender_account, Payment_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 24 HOURS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING), 0) AS sender_amount_sum_24h,
    AVG(Amount) OVER (PARTITION BY Sender_account, Payment_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 30 DAYS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS sender_amount_mean_30d,
    STDDEV_SAMP(Amount) OVER (PARTITION BY Sender_account, Payment_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 30 DAYS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS sender_amount_std_30d,
    COUNT(*) OVER (PARTITION BY Receiver_account, Received_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 24 HOURS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS receiver_txn_count_24h,
    COALESCE(SUM(Amount) OVER (PARTITION BY Receiver_account, Received_currency ORDER BY timestamp RANGE BETWEEN INTERVAL 24 HOURS PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING), 0) AS receiver_amount_sum_24h,
    MAX(timestamp) OVER (PARTITION BY Sender_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS previous_sender_timestamp,
    COUNT(*) OVER (PARTITION BY Sender_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS sender_txn_count_lifetime,
    COUNT(*) OVER (PARTITION BY Receiver_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS receiver_txn_count_lifetime,
    COUNT(DISTINCT Receiver_account) OVER (PARTITION BY Sender_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS sender_out_degree,
    COUNT(DISTINCT Sender_account) OVER (PARTITION BY Receiver_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS receiver_in_degree,
    COUNT(*) OVER (PARTITION BY Sender_account, Receiver_account ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING) AS pair_transaction_count
  FROM base
),
pair_history AS (
  SELECT Sender_account, Payment_currency, Receiver_account, timestamp, SUM(Amount) AS pair_amount
  FROM base GROUP BY Sender_account, Payment_currency, Receiver_account, timestamp
),
pair_cumulative AS (
  SELECT *, COALESCE(SUM(pair_amount) OVER (
    PARTITION BY Sender_account, Payment_currency, Receiver_account
    ORDER BY timestamp RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING
  ), 0) AS historical_pair_amount FROM pair_history
),
pair_hhi_deltas AS (
  SELECT Sender_account, Payment_currency, timestamp,
    SUM(pair_amount) AS amount_delta,
    SUM(POWER(pair_amount, 2)) + 2 * SUM(historical_pair_amount * pair_amount) AS squared_amount_delta
  FROM pair_cumulative GROUP BY Sender_account, Payment_currency, timestamp
),
sender_hhi AS (
  SELECT Sender_account, Payment_currency, timestamp,
    CASE WHEN COALESCE(SUM(amount_delta) OVER (
      PARTITION BY Sender_account, Payment_currency ORDER BY timestamp
      RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING
    ), 0) = 0 THEN 0 ELSE
      COALESCE(SUM(squared_amount_delta) OVER (
        PARTITION BY Sender_account, Payment_currency ORDER BY timestamp
        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING
      ), 0) / POWER(SUM(amount_delta) OVER (
        PARTITION BY Sender_account, Payment_currency ORDER BY timestamp
        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MICROSECOND PRECEDING
      ), 2)
    END AS sender_counterparty_hhi
  FROM pair_hhi_deltas
),
joined AS (
  SELECT history.*, COALESCE(sender_hhi.sender_counterparty_hhi, 0) AS sender_counterparty_hhi
  FROM history LEFT JOIN sender_hhi USING (Sender_account, Payment_currency, timestamp)
)
SELECT
  Amount,
  ln(1 + Amount) AS log_amount,
  sin(2 * pi() * hour_of_day / 24) AS hour_sin,
  cos(2 * pi() * hour_of_day / 24) AS hour_cos,
  sin(2 * pi() * (((duck_day_of_week + 6) % 7) / 7.0)) AS dow_sin,
  cos(2 * pi() * (((duck_day_of_week + 6) % 7) / 7.0)) AS dow_cos,
  sin(2 * pi() * month_of_year / 12) AS month_sin,
  cos(2 * pi() * month_of_year / 12) AS month_cos,
  CAST(((duck_day_of_week + 6) % 7) >= 5 AS TINYINT) AS is_weekend,
  CAST(hour_of_day >= 22 OR hour_of_day <= 6 AS TINYINT) AS is_night,
  CAST(Payment_currency != Received_currency AS TINYINT) AS currency_mismatch,
  CAST(Sender_bank_location != Receiver_bank_location AS TINYINT) AS cross_border,
  CAST(abs(Amount % 1000) < 1e-8 AS TINYINT) AS is_round_amount,
  COALESCE(sender_txn_count_24h, 0) AS sender_txn_count_24h,
  COALESCE(sender_amount_sum_24h, 0) AS sender_amount_sum_24h,
  COALESCE(sender_amount_mean_30d, 0) AS sender_amount_mean_30d,
  COALESCE(sender_amount_std_30d, 0) AS sender_amount_std_30d,
  CASE WHEN sender_amount_std_30d IS NULL OR sender_amount_std_30d = 0 THEN 0
    ELSE (Amount - sender_amount_mean_30d) / sender_amount_std_30d END AS sender_amount_zscore,
  COALESCE(receiver_txn_count_24h, 0) AS receiver_txn_count_24h,
  COALESCE(receiver_amount_sum_24h, 0) AS receiver_amount_sum_24h,
  COALESCE(date_diff('second', previous_sender_timestamp, timestamp), -1) AS seconds_since_sender_txn,
  COALESCE(sender_txn_count_lifetime, 0) AS sender_txn_count_lifetime,
  COALESCE(receiver_txn_count_lifetime, 0) AS receiver_txn_count_lifetime,
  COALESCE(sender_out_degree, 0) AS sender_out_degree,
  COALESCE(receiver_in_degree, 0) AS receiver_in_degree,
  COALESCE(pair_transaction_count, 0) AS pair_transaction_count,
  sender_counterparty_hhi,
  Payment_type, Payment_currency, Received_currency, Sender_bank_location, Receiver_bank_location,
  timestamp, Is_laundering
FROM joined ORDER BY timestamp
"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_features(source: Path, destination: Path) -> dict:
    if not source.is_file():
        raise FileNotFoundError(f"Licensed raw SAML-D CSV not found: {source}")
    with source.open("rb") as stream:
        if stream.read(64).startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError("Input is a Git LFS pointer, not the licensed dataset.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(source.resolve()).replace("'", "''")
    query = FEATURE_QUERY.replace("__RAW_PATH__", f"'{escaped}'")
    con = duckdb.connect()
    con.execute("SET threads TO 4")
    con.execute(f"COPY ({query}) TO '{str(destination.resolve()).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{str(destination.resolve())}')").fetchone()[0]
    bounds = con.execute(f"SELECT MIN(timestamp), MAX(timestamp), SUM(Is_laundering) FROM read_parquet('{str(destination.resolve())}')").fetchone()
    con.close()
    metadata = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "source_research_commit": SOURCE_COMMIT,
        "dataset_name": "SAML-D",
        "dataset_sha256": file_sha256(source),
        "row_count": rows,
        "positive_count": int(bounds[2]),
        "start_timestamp": str(bounds[0]),
        "end_timestamp": str(bounds[1]),
        "target": "Is_laundering == 1",
        "timestamp_tie_policy": "All same-timestamp observations are excluded from prior history.",
        "hhi_definition": "Prior sender and payment-currency amounts aggregated by receiver; concentration over historical amount.",
        "dataset_license_notice": "Upstream data README identifies CC BY-NC-SA 4.0; verify intended-use rights before model distribution.",
    }
    sidecar = destination.with_suffix(destination.suffix + ".manifest.json")
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/SAML-D.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/risklens-causal-v2.parquet")
    args = parser.parse_args()
    print(json.dumps(build_features(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
