# Cutting observability cost without losing SLO fidelity

*A vendor-neutral, policy-driven telemetry routing architecture built on the
OpenTelemetry Collector — reference implementation:
[otel-gateway](https://github.com/) (this repository).*

## The problem with "sample everything the same"

Every team that has run Splunk, Datadog, or any pay-per-GB observability
backend at scale eventually hits the same wall: ingest volume grows faster
than the budget, and the two obvious responses both fail.

- **Sample uniformly** (e.g. "keep 10% of everything") destroys SLO
  fidelity: the 10% you keep is statistically unlikely to include the
  handful of error traces from your highest-value service during an
  incident.
- **Route everything to the expensive backend** preserves fidelity but
  makes cost linear with volume, which is not a strategy — it's a bill.

The alternative this project implements is **routing by value**: a
telemetry pipeline that classifies every log, span, and metric by business
criticality, signal severity, and cost pressure — not just its type — and
sends it to the tier that matches what it's actually worth.

## Why this had to be a policy, not a config file

The first version of this idea is always "add an `if severity == ERROR`
to the collector config." That breaks the moment you have more than one
collector, more than one team touching the config, or a compliance
requirement that doesn't fit an ad-hoc `if`. The three things that actually
make routing-by-value defensible at scale are:

1. **A service catalog** that says what a service *is* (criticality tier,
   owning team, cost center, compliance obligations) — not inferred from
   naming conventions, but declared and owned by the platform team.
2. **A routing policy** that combines that catalog with signal-level
   criteria (severity, SLO relevance, error status) into an ordered
   decision table — auditable, versioned, and reviewable in a pull request
   like any other infrastructure change.
3. **A compiler**, not hand-edited YAML per collector, translating that
   policy into the actual OpenTelemetry Collector configuration (OTTL
   expressions, `routingconnector` tables). This is the same separation of
   concerns as "declarative infra + a controller that reconciles it" —
   applied to telemetry governance instead of Kubernetes resources.

This repository implements exactly that: `policy/*.yaml` is the source of
truth, `policy-compiler/compile.py` is the controller, and
`collector/config/otelcol-config.generated.yaml` is the reconciled output —
never edited by hand.

## The routing matrix

Four rules, evaluated in order, first match wins:

1. **Compliance override.** A service flagged `compliance_hold: true`
   always lands in the queryable warm tier, regardless of tier or budget.
   Never dropped. This has to be rule #1 — no cost optimization is allowed
   to violate a retention obligation.
2. **Error/SLO-relevance upgrade.** An error log, an error-status span, or
   an SLO-tagged metric moves up a tier — even for a low-criticality
   service, an error is never silently dropped; it lands in warm at worst.
3. **Base classification by service tier.** Absent an error, a critical
   service's normal traffic goes to *warm*, not hot — a deliberate choice.
   Most of what a critical service emits under normal operation doesn't
   need second-latency query or premium retention.
4. **Budget-pressure downgrade.** A cost-aware circuit breaker: when a
   service's volume exceeds its configured budget over a rolling window,
   its non-error signals get pushed down a tier until volume normalizes.
   Error signals are exempt — diagnosability never loses to a budget line.

The full rationale for each rule, with the exact OTTL it compiles to, is in
[`docs/routing-policy.md`](routing-policy.md).

## What this looks like on synthetic load

The demo ships with an 8-service synthetic load generator
(`telemetry-generator/`) mirroring a realistic service mix: a payments path
(`checkout-api`, `payment-gateway`, `auth-service`) at `critical` tier with
low-to-moderate error rates, and a data/batch path
(`recommendation-engine`, `batch-etl-job`) at `low` tier with high volume
and near-zero error rates — the shape most orgs actually have, where a
minority of services carry most of the diagnostic value and a minority of
*other* services carry most of the volume.

In the demo's `services.yaml` configuration, `recommendation-engine` and
`batch-etl-job` alone account for **~63% of total configured log volume**
(1,700 of 2,710 log events/min across all 8 services), while sitting at
`tier: low` with sub-1% error rates. Under the routing policy, that volume
is almost entirely classified `drop` or `warm` rather than `hot` — which is
the whole point: the pipeline doesn't need to *guess* this is low-value
traffic, the policy already knows it from the service catalog.

*(This is a configuration-level statistic from the reference demo, not a
measured production outcome. Section "Using this with your own numbers"
below explains how to replace it with real, anonymized figures.)*

## Showback, not just a drop counter

A dashboard that only shows "GB dropped" answers the wrong question for a
FinOps conversation. What a team/cost-center owner actually wants to know
is: *how much would this have cost if we hadn't done this, broken down by
where the saving came from.* The showback dashboard
(`dashboards/cost-showback.json`) separates three numbers per
service/cost-center:

- **Residual cost** — what's still being paid (hot + warm).
- **Downgrade saving** — the delta from routing something to warm instead
  of hot.
- **Drop saving** — the full avoided cost of discarded low-value signals.

Both saving metrics are estimated from record counts × an average
bytes-per-record constant, not from measured network bytes — an
approximation stated explicitly in
[`docs/cost-model.md`](cost-model.md), because a portfolio project claiming
false precision is worse than one that's honest about its assumptions.

## The part that's easy to forget: querying it back later

A warm tier nobody can query cheaply isn't a warm tier, it's a write-only
cost sink with extra steps. Athena (or any engine that charges per TB
scanned) makes partitioning a first-class design decision, not an
afterthought: the Glue table in
`terraform/modules/glue-catalog` partitions by `cost_center` / `dt` /
`service_name`, matching the two query patterns that actually get used in
practice — incident investigation ("show me this service's warm logs for
this window") and monthly cost reconstruction by team. Get the partitioning
wrong and the query cost eats the ingestion saving.

## What's deliberately out of scope (and the honest next step)

This is a local, Docker Compose–based reference implementation — MinIO
stands in for S3, and the Grafana stack (Tempo/Loki/Prometheus) stands in
for a commercial "hot" backend. The Terraform in `terraform/` describes the
real AWS infrastructure this maps to but is never applied in the demo
environment.

The other deliberate gap is **dynamic policy distribution**. This demo
recompiles the policy into a static Collector config and restarts it
(`make recompile-policy-with-budget`) — a "poor man's control plane." At
fleet scale, the real answer is
[OpAMP](https://opentelemetry.io/docs/specs/opamp/) (Open Agent Management
Protocol), which lets a control plane push configuration to a fleet of
Gateway Collectors without restarts and report per-collector policy version
and health back. The compiler in this project already emits a versioned,
self-contained artifact — the natural next step is an OpAMP server
distributing that artifact instead of a file copied by `docker compose
restart`.

## Using this with your own numbers

If you're adapting this for a real cost-reduction narrative (which is
exactly why this project exists — turning a Splunk/SmartStore cost
reduction effort into a reusable, vendor-neutral architecture): replace the
synthetic `telemetry-generator/services.yaml` distribution with your own
service mix's real (anonymized) volume and error-rate profile, run the same
pipeline, and pull the actual numbers from
`dashboards/cost-showback.json` and `scripts/cost-report.sh`. The
architecture and the honesty about what's measured vs. estimated should
travel with the numbers.

## Repository map

| Path | What it is |
|---|---|
| `policy/` | Routing policy, service catalog, cost budgets (source of truth) |
| `policy-compiler/` | Compiles policy into Collector config + Prometheus rules |
| `collector/config/` | Generated OTel Collector config (never hand-edited) |
| `telemetry-generator/` | Synthetic load, 8 services mirroring a realistic tier mix |
| `dashboards/`, `prometheus/rules/` | Cost showback + pipeline health, as code |
| `terraform/` | Real-AWS infrastructure for the warm tier (written, not applied here) |
| `docs/` | Architecture, routing rationale, cost model, runbook |
