# Authoring governance rules

Three ways to interact with the governance layer — all converge on the same
GitOps source of truth (`policy/*.yaml`) and the same compiler, so a rule
authored visually, by CLI, or by hand is identical downstream.

```
   web editor ─┐
   policyctl  ─┼─▶  policy/*.yaml  ──(compile.py)──▶  otelcol-config.generated.yaml
   hand-edit  ─┘     (source of truth,               + cost-rules.generated.yaml
                      reviewed via PR)                        │
                                                     dev pipeline → uat (gated) → ledger
```

The compiler interprets the routing rules **generically** from a closed
vocabulary declared in [`policy-compiler/conditions.json`](../policy-compiler/conditions.json).
Adding a rule that composes existing conditions never requires touching Python —
that is the whole point of this layer.

## The rule model (recap)

`policy/routing-policy.yaml` is an ordered, first-match-wins decision matrix. Each
rule has an `id`, a `when` (match conditions), a `decision` (flat `hot|warm|drop|
downgrade_one_level`) or `decision_by_tier`, and a mandatory `reason` (audit).

`when` keys come from the closed vocabulary (`conditions.json`):

| condition | signals | value | notes |
|-----------|---------|-------|-------|
| `compliance_hold` | log/span/metric | bool | from the service catalog |
| `service_tier` | log/span/metric | list of tiers | criticality match |
| `log_severity` | log | severity list | threshold: "at or above" the lowest listed |
| `span_status` | span | OK/ERROR/UNSET | |
| `http_status_gte` | span | int | e.g. 500 |
| `metric_is_slo_relevant` | metric | bool | latency/error-rate/request-count names |
| `env` | all | list | match `deployment.environment` (e.g. prod, staging) |
| `region` | all | list | match `cloud.region` (e.g. us-east-1) |
| `metric_name_matches` | metric | string (regex) | RE2 match on the metric name |
| `http_route_matches` | span | string (regex) | RE2 match on `http.route` (e.g. `^/healthz$`) |
| `over_budget` | all | bool | resolved at compile time (budget circuit breaker) |
| `log_severity_not_in` / `span_status_not` | log / span | — | negate the error/SLO family (safe-downgrade guard) |

`any_of` / `all_of` group atoms; the literal `true` in an `any_of` is a catch-all.
A condition that does not apply to a signal (e.g. `http_status_gte` for logs) is
simply skipped for that signal — rules are **signal-aware**.

## 1. Visual editor (simplest to see)

Two ways to run it:

```bash
make policy-editor        # static, offline, no backend
# open http://localhost:8000/tools/policy-editor/

make policy-serve         # same editor + live OTTL preview (POST /api/compile)
# open http://localhost:8000/tools/policy-editor/ and use "Preview compiled OTTL"

make policy-serve-apply   # also enables "Compile & Save" and "Apply (dev)" buttons
```

Compose rules with the decision-matrix builder (add/reorder, condition picker,
per-tier decisions), see live validation and the resulting `routing-policy.yaml`,
then **Copy/Download YAML** (commit it) or **Copy selected rule (JSON)** to hand
to `policyctl` below. Under `make policy-serve`, the **Preview compiled OTTL**
button shows the authoritative compiled OTTL diff (the same compiler the CI uses);
with the plain static server that button explains it needs `policyctl serve`.

Under `make policy-serve-apply` (i.e. `policyctl serve --apply`) two more buttons
appear — **Compile & Save** (writes `routing-policy.yaml` + regenerates the OTTL in
the working tree) and **Apply (dev)** (also restarts the local collector and records
a dev deploy). These edit local files only — **localhost-only, no push, no PR bypass**:
you still commit and open a PR for governance, and saving does not preserve inline YAML
comments (review the diff before committing).

## 2. CLI — `policyctl`

```bash
make new-rule                          # interactive wizard
# or non-interactive (e.g. from the editor's rule JSON):
python3 policy-compiler/policyctl.py new-rule --from-json rule.json --before base-tier-classification

python3 policy-compiler/policyctl.py validate           # schema + vocabulary + integrity
python3 policy-compiler/policyctl.py compile --dry-run   # OTTL/cost diff, no write
python3 policy-compiler/policyctl.py add-service --name checkout-v2 --tier critical \
    --team payments --cost-center CC-1001 --budget-gb 5
python3 policy-compiler/policyctl.py set-budget --service batch-etl-job --budget-gb 2
```

## 3. Hand-edit + PR

Edit `policy/*.yaml`, run `make compile-policy`, commit both the policy and the
regenerated artifacts, open a PR. The **dev pipeline** validates it and comments
the compiled OTTL/cost diff (see below).

## Promotion, traceability & rollback

```
PR ──▶ dev pipeline (validate, tests, anti-drift, OTTL diff comment, smoke)
   ──▶ merge ──▶ uat pipeline (approval gate) ──▶ apply + smoke + ledger record
```

- **dev**: `.github/workflows/policy-dev.yml` runs on every PR. Locally: `make deploy-dev`.
- **uat**: `.github/workflows/policy-uat.yml`, gated by the `uat` GitHub Environment
  (required reviewers — configure under Settings → Environments → uat). Locally: `make deploy-uat`.
- **traceability**: every apply is recorded in
  [`deployments/ledger.jsonl`](../deployments/README.md) (env, `policy.version`,
  git sha, actor, timestamp) and via GitHub Deployments. `policy.version` is also
  stamped on every routed signal.
- **rollback**: `make rollback-uat [TO=<policy.version|sha>]`, or the
  `policy-rollback.yml` workflow, or `policyctl rollback --env uat`. Deterministic
  because each deploy pins a git sha + `policy.version`.

## Guardrails

- Closed `when` vocabulary enforced at compile time (unknown condition / wrong
  type fails validation) — see `compile.build_when_schema`.
- **Anti-drift**: CI recompiles and fails if the committed generated artifacts
  don't match the policy.
- **Golden tests** (`policy-compiler/tests/`) lock the compiler's output so
  refactors stay behavior-preserving.
- **CODEOWNERS** routes policy changes to the platform/observability team.

## Extending the vocabulary (phase 2)

To add a brand-new condition *primitive* (not just a new rule): add an entry to
`conditions.json` (label, signals, value, `render`) and implement its `render` in
`compile._render_atom`. Everything else — schema validation, the editor's field,
the CLI wizard — picks it up from `conditions.json` automatically.
