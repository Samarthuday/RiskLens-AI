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

At the readiness-report audit time, the source checkout had a legacy artifact that RiskLens correctly rejects. It also contains a local licensed 950 MB raw CSV and a generated feature parquet, neither of which is copied into this repository. The source `data/README.md` identifies SAML-D as CC BY-NC-SA 4.0; that does not establish unrestricted commercial use or distribution rights.

Do not interpret the research metrics or the legacy binary as proof that a v2 artifact is present. After confirming the intended local use is permitted and placing the authorized raw data at `data/raw/SAML-D.csv`, build and train with the committed RiskLens contract:

```bash
git clone https://github.com/Samarthuday/Quantitative-Transaction-Risk-Modeling.git research-source
cd research-source
git checkout bbe79212099c9d81c74c643362d52c228db7db08
python -m pip install -r requirements.lock
python scripts/build_training_features.py
python scripts/train_v2.py
shasum -a 256 build/risk_model.joblib
python scripts/verify_artifact.py --artifact build/risk_model.joblib --sha256 YOUR_SHA256
```

The batch builder uses point-in-time range windows, excludes equal timestamps, and uses the same corrected sender/currency counterparty HHI as the online feature builder. Tests compare every declared feature on a fixture. Training uses chronological train/calibration/validation/test partitions, fits preprocessing only on train, calibration only on calibration, chooses alert capacity threshold on validation, evaluates the final test once, and compares a calibrated logistic baseline. The report includes sample and positive counts, prevalence, subgroup metrics, fixed-threshold confusion counts, and calendar-week block-bootstrap intervals. The saved artifact includes a checksum-bound manifest with source/training commits, raw dataset hash, config hash, split, metrics, and package versions.

Training writes only to ignored local build/data directories. Do not redistribute the model until the SAML-D license question is resolved. Joblib/pickle artifacts must only come from trusted, pinned training runs.

Do not train a replacement on generated toy labels to make the score panel appear enabled. In the absence of the compatible binary, RiskLens returns no probability and keeps the investigation workflow operational in evidence-only mode.

## Application capability boundary

**Existing source research:** AML suspicious-event model, calibration, held-out/walk-forward metrics, feature ablations, and SHAP utility functions.

**New in RiskLens:** transaction API and simulator, SQLite storage, local online feature calculation, case investigation/state trace, deterministic policy logic, optional model loading, SHAP integration, analyst review, cost simulation, drift comparison, MCP tools, optional synthetic-only LLM narrative, and the integrity evaluation harness.

The new app has not established live-institution accuracy, real loss reduction, operational throughput, or public deployment. No live model inference can be measured until a trusted artifact is installed.
