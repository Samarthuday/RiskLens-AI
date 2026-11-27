# Decision 0001: Keep the AML research target separate from payment risk

Status: accepted

RiskLens's research model predicts the SAML-D label `Is_laundering == 1` from
the `risklens-causal-v2` feature contract. A payment status, chargeback,
refund, dispute, or analyst escalation is not that label. Razorpay payment
events may be investigated as a distinct evidence source, but they are not
scored by the AML model unless their fields satisfy the model contract.

Missing account history, bank fields, or labels remain explicit. The system
abstains from unsupported scoring instead of manufacturing features. Any later
payment-risk model needs a declared payment target, suitable data, its own
schema, and held-out evaluation.

The upstream dataset is marked CC BY-NC-SA 4.0. Training and local evaluation
do not establish permission to redistribute derived weights or use them
commercially. Resolve that before publishing an artifact or enabling it in a
commercial setting.
