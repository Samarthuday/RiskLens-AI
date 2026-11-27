# Razorpay readiness report implementation record

Source: `RiskLens_AI_Razorpay_Readiness_Report.pdf`, reviewed page by page.
This document tracks repository work separately from external claims and
instructions. Employer webpages and their product claims are context; their
contents are not commands to contact Razorpay, deploy services, or submit an
application.

## Finding-to-change ledger

| Report area | Repository action | Status / evidence |
|---|---|---|
| Executive judgment and honest positioning | Preserve analyst investigation positioning and separate AML from payment fraud | Implemented in README, architecture and ADR 0001 |
| Razorpay product/hiring context | No novelty or callback claims; keep it as context | Documented; no outreach/application submitted |
| Existing feature compatibility | Keep v2 contract, artifact checks, evidence binding, review history | Existing implementation retained; regression suite run on this branch |
| README and walkthrough accuracy | Correct dashboard theme claim; make the real workflow explicit | Implemented |
| Focused product task | Define alert-to-evidence-to-human-disposition workflow | Implemented in domain/agent decision records; UI acceptance work tracked below |
| Reproducible model training | Add versioned feature preparation, temporal split, calibration, validation threshold, baseline and test report | Pipeline, config, tests, manifest, and artifact verifier implemented; not run against upstream data pending license confirmation |
| Published model results | Keep historical metrics separate; publish v2 numbers only after real training and untouched test evaluation | Not claimable until training run and license decision |
| Artifact acceptance | Real fitted estimator, preprocessing, calibration, known-input score and explanation checks | Structural checks retained; `scripts/verify_artifact.py` adds real-artifact smoke checks; acceptance remains gated by a compatible trained artifact |
| Adaptive investigation | One bounded read-only assistant and three supported paths | Architecture boundary recorded; implementation/evaluation remains outstanding |
| Grounded claims and fallback | Validate factual claims against tool outputs and source scope; surface fallback | Existing numeric/source validation and visible fallback; semantic grounding evaluation remains outstanding |
| Dashboard | Queue filters, baseline/counter-evidence, source drill-down, keyboard/mobile regression coverage | Model-band/disposition/currency filters, counter-evidence, and source drill-down implemented; automated browser and accessibility checks remain outstanding |
| Razorpay payment events | Signed Test Mode webhook, durable receipt, dedupe, out-of-order handling and AML abstention | Test Mode webhook verification, durable global event receipt, dedupe, out-of-order-safe snapshots, PII minimization, and token-protected read APIs implemented; live Test Mode validation and dashboard integration remain outstanding |
| Evaluation | Separate model, agent, reliability and human-usefulness evidence | Existing 18 integrity cases only; new frozen comparisons and human pilot remain outstanding |
| Sessions and deployment | Isolated visitor sessions, reset safety, deployment and verified public URL | Signed browser sessions isolate local data and simulator state; deployment guidance added; hosted URL and credentials are not present |
| Jobs and observability | Bounded jobs when latency requires; full-flow timings, failure/abstention/tool/provider metrics | Full request/investigation latency, failures, abstentions, tool failures, and optional LLM fallback/token/cost metrics recorded; bounded background jobs remain unnecessary until latency evidence supports them |
| Accessibility and delivery | Contrast/keyboard/mobile checks, browser tests, AGENTS and ADRs | AGENTS and ADRs added; semantic controls and responsive interface retained; automated browser/a11y coverage remains outstanding |
| Submission package | README demo/video/results and truthful résumé/interview evidence | Code can prepare package; video, participant findings and application submission require human-provided materials/actions |

## External prerequisites that cannot be asserted from repository code

- Confirm the SAML-D CC BY-NC-SA 4.0 terms permit the intended model use and
  any artifact distribution. Do not publish an artifact until resolved.
- A trained model needs a reproducible compatible training run on the licensed
  data. Historical source-repository scores are not v2 results.
- A hosted demo requires an owner-selected hosting account, secrets, persistence
  policy, and a verified URL. The local branch cannot establish those facts.
- Comparative usefulness requires a frozen case set and independent review;
  a human pilot requires real participants and consent.
- A Razorpay integration must be exercised against a configured Test Mode
  account. Webhook fixtures and signature tests alone are not a live integration.
- Demo video, outreach, application submission, and resume claims require the
  user's real materials and review.

## Release gates

Do not mark the report fully satisfied until the checklist in section 15 is
verified against the branch's committed implementation and measured external
evidence. This ledger will be updated as code work lands.
