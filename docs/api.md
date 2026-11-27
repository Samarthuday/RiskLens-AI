# API examples

All transaction and case writes are local to the configured SQLite database. The simulator and demo UI use synthetic data only.

## Seed the demo

```bash
curl -X POST 'http://localhost:7860/api/v1/simulation/reset?scenario=burst&count=36'
curl 'http://localhost:7860/api/v1/transactions?limit=20'
```

## Ingest one transaction

```bash
curl -X POST http://localhost:7860/api/v1/transactions \
  -H 'Content-Type: application/json' \
  -d '{
    "transaction_id":"txn_demo_001",
    "timestamp":"2025-03-01T13:45:00Z",
    "sender_id":"acct_demo_1",
    "receiver_id":"merchant_demo_1",
    "amount":120.00,
    "payment_currency":"USD",
    "received_currency":"USD",
    "sender_location":"US",
    "receiver_location":"US",
    "payment_type":"Transfer",
    "description":"Synthetic demo payment",
    "source":"manual"
  }'
```

Posting the same ID and identical content returns an idempotent replay. Reusing an ID with different fields returns HTTP 409. Entity fields are only used to retrieve past data and are excluded from model input.

## Investigate and review

```bash
curl -X POST http://localhost:7860/api/v1/investigations \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"txn_demo_001","false_positive_cost":1,"missed_event_cost":100,"manual_review_cost":0.25}'
curl http://localhost:7860/api/v1/investigations/inv_<id>/trace
curl -X POST http://localhost:7860/api/v1/cases/inv_<id>/review \
  -H 'Content-Type: application/json' -d '{"decision":"escalated","analyst_note":"Request supporting documentation"}'
```

Without a compatible model, the report contains `model_risk_probability: null`, `risk_classification: "unavailable"`, and `recommended_action: "insufficient_evidence"`. With a model installed, `POST /api/v1/risk/score` takes `{"transaction_id":"..."}` and returns the calibrated probability, threshold, model version, warnings, and measured inference latency.

## Cost simulator

```bash
curl -X POST http://localhost:7860/api/v1/policies/simulate \
  -H 'Content-Type: application/json' \
  -d '{"probabilities":[0.02,0.31,0.81],"alert_budget":0.34,"false_positive_cost":1,"missed_event_cost":100,"manual_review_cost":0.25}'
```

Probabilities should come from a compatible `risklens-causal-v2` model. This endpoint does not calculate precision/recall because it receives no outcome labels. Cost inputs are abstract user-defined units, not currency or realized loss.

API transaction ingestion always records source provenance as `manual`; clients cannot mark a row as trusted simulator output. `GET /api/v1/investigations?transaction_id=...` returns saved cases so a client can reopen the existing workflow.
