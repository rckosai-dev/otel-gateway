# Routing policy — how the decision is made

Source of truth: `policy/routing-policy.yaml` + `policy/service-catalog.yaml`
+ `policy/cost-budget.yaml`. Compiled by `policy-compiler/compile.py` into
OTTL (see `docs/architecture.md`). This document explains the *why* behind
each rule, in the order they're evaluated (first match wins).

## 1. Compliance / legal-retention override

Services with `compliance_hold: true` in the catalog (e.g.,
`payment-gateway`, `auth-service`) always go to `warm`, **never** `drop`,
regardless of tier, error status, or budget. This is non-negotiable at any
real company with an audit obligation — the policy has to express that
explicitly, not as a manual exception.

## 2. Upgrade by severity/SLO relevance

An error signal (an `ERROR`/`FATAL` log, a span with
`status.code=ERROR` or `http.status_code >= 500`, an SLO-relevant metric)
moves up one tier:

| Service tier | Base decision | With error/SLO relevance |
|---|---|---|
| critical | warm | **hot** |
| standard | warm | **hot** |
| low | drop | **warm** |

This is the core of the "no SLO fidelity lost" argument: even a
`low`-tier service has its errors preserved (they become warm, not
dropped) — only low-value noise (DEBUG/INFO without an error) is a drop
candidate.

## 3. Base classification by criticality tier

Without an error/SLO relevance, the decision comes purely from the
service's criticality in the catalog: `critical`/`standard` → `warm`;
`low` → `drop`. Note that **not every signal from a critical service goes
to hot** — that's deliberate: hot is expensive, and most of a critical
service's "normal" traffic (no error, no SLO at risk) doesn't need
second-level query latency or expensive retention.

## 4. Dynamic downgrade under budget pressure

If a service's volume over the last `window` (default 1h, see
`policy/cost-budget.yaml`) exceeds `budget_gb`, non-critical signals from
that service drop one tier (hot→warm, warm→drop) until it normalizes —
except error signals, which never get downgraded for budget pressure. It's
a cost circuit breaker: the policy reacts to real volume pressure, not just
static rules — the same principle behind adaptive sampling used by
commercial observability platforms.

## Concrete examples (from the demo's services.yaml)

- `checkout-api` (critical, 5% error rate): mostly hot (high error rate +
  critical), high volume — a good example of "residual cost concentrated
  where it matters."
- `recommendation-engine` (low, very high volume): almost all warm/drop —
  the main source of "avoided cost" in the dashboard.
- `payment-gateway` (critical + compliance_hold): never dropped, even if it
  exceeds budget — demonstrates rule 1 in practice.

## Known limitation of this model

The matrix is evaluated deterministically and statically at compile time —
the dynamic downgrade (rule 4) is only re-evaluated when someone runs
`make recompile-policy-with-budget`. That's acceptable for a demo, and it's
exactly the gap the OpAMP production roadmap (`docs/architecture.md`)
closes.
