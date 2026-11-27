# Research foundation and model provenance

## Source audit

RiskLens AI reuses the quantitative research design from [Samarthuday/Quantitative-Transaction-Risk-Modeling](https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling), pinned at commit `bbe79212099c9d81c74c643362d52c228db7db08` (checked 2026-11-27). This keeps the research repository unchanged and makes source assumptions reviewable.

The pinned code implements point-in-time transaction and behavioral/network feature engineering, chronological train/calibration/validation/test splits, XGBoost classification, logistic probability calibration, validation-set alert-threshold selection, top-K alert-budget evaluation, feature ablations, walk-forward evaluation, unseen-entity analysis, SHAP helpers, and FastAPI inference over a full precomputed feature vector.

## Verified historical metrics

We independently compared `reports/model_metrics.json` and `docs/assets/model_metrics.json` in the pinned repository; their JSON contents are identical. RiskLens stores the selected reported metrics in `research/reported_metrics.json` with the exact commit and source path.

| Source held-out test metric | Value |
|---|---:|
| PR-AUC | 0.9859286355765932 |
| ROC-AUC | 0.9998338278230887 |
| Precision at 0.1% alert budget | 1.0 |
| Recall at 0.1% alert budget | 0.8388429752066116 |
| Recall at 0.5% alert budget | 0.9929161747343566 |
| Recall at 1.0% alert budget | 0.9946871310507674 |
| Brier score | 0.0000991499618976377 |
| Log loss | 0.00044060166692361236 |

These are offline results on the synthetic SAML-D held-out test split. They are neither application measurements nor performance guarantees. The 100% precision at one alert budget is an outcome on that split, not a generalizable claim.

## Reused compatibility surface

- Model inputs retain the original ordered schema from `src/models/train.py:MODEL_FEATURES` at the pinned commit.
- `app/features.py` preserves the ordered source feature names but uses the versioned online contract `risklens-causal-v2`. For each online transaction, the current event is excluded from historical windows. Most encodings and behavioral/network calculations match the pinned source, subject to the explicit differences below.
- `src/models/calibration.py` retains the exact class import path (`src.models.calibration.ProbabilityCalibrator`) and the original logistic-on-logit calibration implementation needed to deserialize joblib artifacts.
- Inference uses the artifact's own preprocessor, model, calibrator, feature order, version, and validation-selected decision threshold. It also requires the exact `feature_schema_version`; matching names alone is not accepted.
- SHAP is computed against the preprocessed input and XGBoost model. If SHAP fails or cannot align feature names, the report says explanation unavailable rather than filling in guessed values.

**Do not load the source research artifact directly.** The source `sender_counterparty_hhi` calculation groups historical pair balances by the timestamp at which each counterparty is active, so it is not the historical sender/currency concentration that an online transaction can calculate. RiskLens v2 instead computes value-share HHI over all prior counterparties for the same sender and payment currency. The features share a name but do not share semantics. In addition, simultaneous transactions are excluded from one another's online history; the source lag feature orders only by timestamp, so tied-row behavior can depend on input ordering. Artifacts trained with `research-bbe7921-v1` are therefore rejected even when their feature names match.

The contract test suite covers point-in-time exclusion, 24-hour/30-day boundaries, mixed currencies, ties, missing history, HHI behavior, and rejection of an unversioned/legacy artifact. A future `risklens-causal-v2` artifact must be trained and evaluated with this application feature implementation and a licensed dataset before enabling inference. There is currently no such artifact in either checkout, and the SAML-D license does not permit assuming unrestricted deployment use.

## Artifact availability and recovery

At audit time, the research checkout had **no** `artifacts/risk_model.joblib` and no processed feature set. A 950 MB CSV object existed in local Git LFS storage, but the source `data/README.md` identifies SAML-D as CC BY-NC-SA 4.0 and says the raw dataset is intentionally not committed. RiskLens does not copy or redistribute it.

There is therefore no existing model artifact checksum to publish. Do not interpret the research metrics as proof that the binary is present. To recover an artifact, obtain the licensed dataset under the applicable terms and follow the pinned repository's documented run:

```bash
git clone https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling.git research-source
cd research-source
git checkout bbe79212099c9d81c74c643362d52c228db7db08
# Place an authorized SAML-D.csv at data/raw/SAML-D.csv.
python -m pip install -e .
python scripts/run_experiments.py
# Source pipeline writes artifacts/risk_model.joblib.
shasum -a 256 artifacts/risk_model.joblib
```

That source command creates a legacy artifact and is useful for reproducing the historical research result only. It is **not** loadable by RiskLens v2. To enable RiskLens inference, retrain using an authorized dataset and the v2 online feature builder as the single training and inference transformation, then package an artifact with `feature_schema_version="risklens-causal-v2"`, the exact ordered `features`, and a manifest conforming to [the JSON schema](model-artifact-manifest.schema.json). Record the artifact SHA-256 and configure the required `RISKLENS_MODEL_SHA256`. The loader rejects artifacts without the v2 contract, complete manifest, or matching checksum. Joblib/pickle artifacts must only come from trusted, pinned training runs.

Do not train a replacement on generated toy labels to make the score panel appear enabled. In the absence of the compatible binary, RiskLens returns no probability and keeps the investigation workflow operational in evidence-only mode.

## Application capability boundary

**Existing source research:** AML suspicious-event model, calibration, held-out/walk-forward metrics, feature ablations, and SHAP utility functions.

**New in RiskLens:** transaction API and simulator, SQLite storage, local online feature calculation, case investigation/state trace, deterministic policy logic, optional model loading, SHAP integration, analyst review, cost simulation, drift comparison, MCP tools, optional synthetic-only LLM narrative, and the integrity evaluation harness.

The new app has not established live-institution accuracy, real loss reduction, operational throughput, or public deployment. No live model inference can be measured until a trusted artifact is installed.
