# Deployments — traceability & rollback ledger

This directory holds the **append-only deployment ledger** (`ledger.jsonl`) that
makes every policy promotion to `dev`/`uat` auditable and every rollback
deterministic. It complements — and is deliberately redundant with — GitHub
Deployments/Environments, so the audit trail lives in the repo itself.

## What is recorded

One JSON object per line (JSONL), one per `deploy` or `rollback`:

| field | meaning |
|-------|---------|
| `action` | `deploy` or `rollback` |
| `env` | target environment (`dev`, `uat`, …) |
| `policy_version` | deterministic hash of the active policy (also stamped on every routed signal as `policy.version`) |
| `git_sha` | commit that produced the compiled artifact |
| `actor` | who triggered it (CI actor or local user) |
| `timestamp` | UTC, ISO-8601 |
| `note` | optional context (e.g. "rollback to <version>") |

Because `git_sha` + `policy_version` pin an exact, versioned artifact in Git,
**rollback = redeploy a previous line** — no guesswork.

## How it gets written

- **Pipelines** (`.github/workflows/policy-dev.yml`, `policy-uat.yml`) call
  `policyctl record-deploy --env <env>` after a successful apply/smoke.
- **Locally**, `make deploy-dev` / `make deploy-uat` do the same.
- **Rollback** (`policyctl rollback --env <env> [--to <policy.version|sha>]`, or
  `make rollback-dev` / `rollback-uat`, or the `policy-rollback.yml` workflow)
  restores `policy/` + the generated artifacts from the target commit and appends
  a `rollback` record.

## Inspecting

```bash
python3 policy-compiler/policyctl.py ledger            # all environments
python3 policy-compiler/policyctl.py ledger --env uat  # one environment
```

The ledger is committed on `deploy`/`rollback` so history is shared and durable.
