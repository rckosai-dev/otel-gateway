"""Tests for the policy compiler.

The most important test here is the GOLDEN test: the generalized (data-driven)
compiler must reproduce the committed generated artifacts byte-for-byte from the
current policies. That is what proves the generalization refactor is
behavior-preserving, and it is the same invariant the CI anti-drift check
enforces on every PR.
"""
import copy
import importlib.util
import io
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILE_PY = REPO_ROOT / "policy-compiler" / "compile.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_compiler():
    spec = importlib.util.spec_from_file_location("compile_mod", COMPILE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load_compiler()


def _policies():
    catalog = m.load_yaml(m.POLICY_DIR / "service-catalog.yaml")
    routing = m.load_yaml(m.POLICY_DIR / "routing-policy.yaml")
    budget = m.load_yaml(m.POLICY_DIR / "cost-budget.yaml")
    return catalog, routing, budget


def _dump(obj):
    buf = io.StringIO()
    yaml.safe_dump(obj, buf, sort_keys=False, default_flow_style=False, width=100)
    return buf.getvalue()


def _strip_header(text):
    """Drop the leading AUTO-GENERATED comment block (comment + blank lines)."""
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        i += 1
    return "".join(lines[i:])


# --------------------------------------------------------------------------- #
# Golden: the compiler reproduces the committed generated files exactly.
# --------------------------------------------------------------------------- #

def test_default_collector_config_matches_committed_golden():
    catalog, routing, budget = _policies()
    result = m.compile_all(catalog, routing, budget)
    committed = (REPO_ROOT / "collector" / "config" / "otelcol-config.generated.yaml").read_text()
    assert _dump(result["config"]) == _strip_header(committed)


def test_default_prometheus_rules_match_committed_golden():
    catalog, routing, budget = _policies()
    result = m.compile_all(catalog, routing, budget)
    committed = (REPO_ROOT / "prometheus" / "rules" / "cost-rules.generated.yaml").read_text()
    assert _dump(result["prometheus_rules"]) == _strip_header(committed)


def test_budget_downgrade_path_matches_fixture():
    """The --prometheus-url dynamic-downgrade path is not in the committed golden
    (no service is over budget by default); this fixture locks its output."""
    catalog, routing, budget = _policies()
    version = m.policy_version(catalog, routing, budget)
    over_budget = {"recommendation-engine", "batch-etl-job"}
    cfg = m.build_config(catalog, routing, budget, version, over_budget)
    expected = _strip_header((FIXTURES / "expected-budget-downgrade.yaml").read_text())
    assert _dump(cfg) == expected


# --------------------------------------------------------------------------- #
# Generic engine: new rules compile from config alone, signal-aware.
# --------------------------------------------------------------------------- #

def test_new_span_rule_compiles_generically_and_is_signal_aware():
    _, routing, _ = _policies()
    new = copy.deepcopy(routing)
    new["rules"].insert(2, {
        "id": "rate-limit-429-warm",
        "when": {"any_of": [{"http_status_gte": 429}]},
        "decision_by_tier": {"critical": "warm", "standard": "warm", "low": "warm"},
        "reason": "Rate-limit responses: keep warm.",
    })
    span_stmts = m.build_tier_decision_statements(new, "span", set())
    assert any('attributes["http.status_code"] >= 429' in s for s in span_stmts)
    # span-only condition must not leak into the log pipeline
    log_stmts = m.build_tier_decision_statements(new, "log", set())
    assert not any("429" in s for s in log_stmts)


def test_drop_candidate_decision_alias_resolves_to_drop():
    _, routing, _ = _policies()
    log_stmts = m.build_tier_decision_statements(routing, "log", set())
    # base-tier rule maps low -> drop-candidate, which must render as "drop"
    assert any('"drop"' in s and 'service.tier"] == "low"' in s for s in log_stmts)
    assert not any("drop-candidate" in s for s in log_stmts)


def test_compliance_rule_has_no_nil_guard_but_later_rules_do():
    _, routing, _ = _policies()
    stmts = m.build_tier_decision_statements(routing, "log", set())
    compliance = next(s for s in stmts if "compliance_hold" in s)
    assert "telemetry.tier\"] == nil" not in compliance
    guarded = [s for s in stmts if "service.tier" in s]
    assert all('telemetry.tier"] == nil' in s for s in guarded)


# --------------------------------------------------------------------------- #
# Vocabulary enforcement (the closed `when` contract).
# --------------------------------------------------------------------------- #

def test_unknown_condition_is_rejected():
    catalog, routing, budget = _policies()
    bad = copy.deepcopy(routing)
    bad["rules"][0]["when"] = {"not_a_real_condition": True}
    with pytest.raises(ValueError):
        m.validate_policies(catalog, bad, budget)


def test_wrong_value_type_is_rejected():
    catalog, routing, budget = _policies()
    bad = copy.deepcopy(routing)
    # http_status_gte expects an integer, not a string
    bad["rules"][1]["when"] = {"any_of": [{"http_status_gte": "five hundred"}]}
    with pytest.raises(ValueError):
        m.validate_policies(catalog, bad, budget)


def test_current_policies_validate_clean():
    catalog, routing, budget = _policies()
    m.validate_policies(catalog, routing, budget)  # must not raise


def test_empty_rule_id_raises_friendly_valueerror():
    """Regression: an empty rule id must surface as a clean ValueError, not a raw
    jsonschema.ValidationError traceback (as the new-rule wizard once produced)."""
    catalog, routing, budget = _policies()
    bad = copy.deepcopy(routing)
    bad["rules"].append({"id": "", "when": {"span_status": "ERROR"},
                         "decision": "warm", "reason": "x"})
    with pytest.raises(ValueError):
        m.validate_policies(catalog, bad, budget)


def test_invalid_enum_value_raises_valueerror():
    catalog, routing, budget = _policies()
    bad = copy.deepcopy(routing)
    bad["rules"].append({"id": "x", "when": {"span_status": "info"},
                         "decision": "warm", "reason": "x"})
    with pytest.raises(ValueError):
        m.validate_policies(catalog, bad, budget)
