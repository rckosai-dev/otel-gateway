<!--
Governance policy change. The dev pipeline validates this PR and comments the
compiled OTTL / cost-rules diff. Keep GitOps as the source of truth: edit
policy/*.yaml (via the web editor, policyctl, or by hand) and commit the
regenerated artifacts (`make compile-policy`).
-->

## What & why
<!-- The rule/catalog/budget change and the problem it addresses. -->

## Type of change
- [ ] New/edited routing rule
- [ ] Service catalog change (tier / team / cost_center / compliance_hold)
- [ ] Budget change
- [ ] Compiler / tooling change

## Affected services / signals
<!-- Which services or signal types (logs/traces/metrics) this changes tiering for. -->

## Cost / routing impact
<!-- Expected effect on hot/warm/drop routing and cost. The dev pipeline posts the
     compiled OTTL / cost-rules diff as a comment — reference it here. -->

## Rollback plan
<!-- Usually: revert this PR, or `make rollback-<env>` / the policy-rollback
     workflow to a previous policy.version (see deployments/ledger.jsonl). -->

## Checklist
- [ ] `make policy-validate` passes (schema + closed vocabulary + integrity)
- [ ] `make policy-tests` passes (golden / behavior-preserving)
- [ ] `make compile-policy` run and generated artifacts committed (anti-drift)
- [ ] `reason` set on every new/edited rule (audit)
