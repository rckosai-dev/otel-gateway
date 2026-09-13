# Governance control plane: GitOps vs. a dedicated product

How this project distributes and governs policy today, and when to adopt an
OpAMP-based control plane. Written to be honest about trade-offs, not to sell one
answer.

## The key idea: they are layers, not competitors

- **GitOps (policy-as-code)** answers *what & why*: which rule, who approved it,
  under which `policy.version` a signal was classified. It is the source of truth,
  the audit trail, and the review gate. This repo already does this
  (`policy/*.yaml` → `compile.py` → versioned artifact).
- **A control plane (OpAMP)** answers *how to distribute*: push config to a fleet
  of collectors without restarts, see per-collector health and the active policy
  version (drift), roll back centrally, plus a visual authoring UI.

The mature pattern used at scale (CNCF/KubeCon NA 2025 talks, Bindplane, Grafana
Labs) is **GitOps as source of truth + OpAMP as the distribution mechanism + a UI
that commits back to Git** — never a UI that becomes a second, diverging source
of truth.

## Trade-off matrix

| Dimension | GitOps + CI (this repo) | Control plane (Bindplane / Grafana Fleet Mgmt / Cribl) |
|-----------|-------------------------|--------------------------------------------------------|
| Source of truth | Git (YAML, PR, `git blame`) | Product DB (unless GitOps-synced) |
| Authoring | text/UI → commit; PR review | native visual, drag-and-drop |
| Applying a change | recompile + redeploy/restart | live push via **OpAMP** (no restart) |
| Fleet view / drift | not built-in (you build it) | native: health, active version, rollback |
| Audit / compliance | excellent (`policy.version` + Git history) | product-dependent; risk of UI↔Git drift |
| Lock-in / cost | ~zero (Git + CI) | SaaS cost or a stateful service to operate |
| Scale | great for what/why; distribution is on you | proven at 500k+ agents (Bindplane) |
| Effort for this repo | low (fits the compiler) | high (changes the architecture) |
| Standard maturity | Git/CI = commodity | **OpAMP is beta**, stabilizing; Grafana Fleet Mgmt is GA |

## Where each fits

- **Stay GitOps-only** when: a small set of expert authors, change cadence
  tolerates redeploy, auditability and zero lock-in matter most. (This project.)
- **Add OpAMP / a control plane** when: many heterogeneous collectors, many
  authors including non-experts, or you need no-restart dynamic changes, fleet
  drift visibility, and central rollback.

## The productionization path for this repo

The demo already ships a versioned, distribution-independent artifact
(`policy.version`), so OpAMP is a drop-in *distribution* upgrade rather than a
rewrite:

1. Keep `policy/*.yaml` + `compile.py` as the source of truth and CI gate.
2. Introduce an **OpAMP server** (e.g. the OpenTelemetry OpAMP supervisor, or an
   open-source control plane such as Bindplane) that serves the compiled config
   to the Gateway Collector fleet.
3. CI publishes the compiled artifact to the OpAMP server on merge to `uat`/`prod`
   instead of restarting a container; the server pushes it with no restart and
   reports the active `policy.version` per collector.
4. Rollback becomes "serve a previous `policy.version`" — the ledger already
   pins each one.

This preserves the audit/review strengths of GitOps while gaining live
distribution, drift visibility, and central rollback.

## Reference tools (2026)

- **OpAMP** — CNCF/OpenTelemetry Open Agent Management Protocol (beta): remote
  config, health/version reporting, package management. In-process or via a
  supervisor.
- **Bindplane (observIQ)** — OpAMP-based control plane + visual pipeline builder;
  GitOps sync; proven at large fleets.
- **Grafana Fleet Management** — GA control plane for Grafana Alloy collectors
  (Terraform/K8s support, pipeline catalog).
- **Cribl Stream/Edge**, **Dash0**, and OSS control planes (Squadron, LinkMesh,
  Telflo) — visual telemetry-pipeline management with a cost/governance focus.

## Sources

- OpenTelemetry — Collector management & OpAMP spec: <https://opentelemetry.io/docs/collector/management/>, <https://opentelemetry.io/docs/specs/opamp/>
- CNCF — Operating OpenTelemetry at scale with OpAMP: <https://www.cncf.io/blog/2026/07/13/operating-opentelemetry-at-scale-with-opamp/>
- Bindplane — OpAMP for OpenTelemetry / managing collector fleets: <https://bindplane.com/blog/opamp-for-opentelemetry-managing-collector-fleets-and-introducing-the-new-opamp-gateway-extension>
- Grafana Labs — Fleet Management GA: <https://grafana.com/blog/telemetry-pipeline-management-at-any-scale-fleet-management-in-grafana-cloud-is-generally-available/>
- Honeycomb — OpAMP explained: <https://www.honeycomb.io/blog/opamp-explained-why-opentelemetry-needed-agent-management-protocol>
