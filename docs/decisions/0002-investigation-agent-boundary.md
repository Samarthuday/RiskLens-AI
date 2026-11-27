# Decision 0002: One bounded read-only investigation assistant

Status: accepted

Keep feature calculation, scoring, policy math, and evidence persistence
deterministic. A single optional investigation agent may select from a narrow
read-only tool allowlist within configured call, turn, wall-time, and cost
budgets. The agent can draft a cited review package; only an analyst can save a
disposition. It cannot change model probabilities or execute payment actions.

Tool arguments are schema-validated. Results are persisted with call IDs,
durations, status, time scope, and source record IDs. Factual claims must be
checked against stored results. Failed or unsupported narrative generation
leaves the deterministic evidence available and records a visible fallback.

The adaptive path remains optional until a frozen comparison shows value over
the deterministic workflow and fixed-tool summary. No multi-agent framework is
needed for the current task.
