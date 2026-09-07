#!/usr/bin/env python3
"""
Policy compiler: compiles policy/service-catalog.yaml + policy/routing-policy.yaml
(+ optionally an over-budget signal from Prometheus, see policy/cost-budget.yaml)
into collector/config/otelcol-config.generated.yaml — the real config of the
OTel Gateway Collector.

This is the project's control plane: the routing policy (the "what" and the
"why") lives in readable, auditable YAML under policy/; this script
translates it into Collector OTTL/config (the "how"), deterministically and
reproducibly. Never hand-edit otelcol-config.generated.yaml.

Usage:
    python3 policy-compiler/compile.py
    python3 policy-compiler/compile.py --prometheus-url http://localhost:9090

The --prometheus-url flag is the demo's "poor man's OpAMP": it queries the
policy:over_budget:by_service recording rule and, for services flagged
over_budget=1, injects an explicit tier downgrade (budget-pressure-downgrade
rule). In production this would be replaced by a dynamic push via OpAMP to
the Gateway Collector fleet, with no need to recompile+restart — see
docs/architecture.md.
"""
import argparse
import copy
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from jsonschema import validate as jsonschema_validate

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = REPO_ROOT / "policy"
SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
OUTPUT_PATH = REPO_ROOT / "collector" / "config" / "otelcol-config.generated.yaml"
PROMETHEUS_RULES_PATH = REPO_ROOT / "prometheus" / "rules" / "cost-rules.generated.yaml"

TIER_DOWNGRADE = {"hot": "warm", "warm": "drop"}  # "drop" never goes lower

# Average size-per-record estimates, used to convert a count (what the
# countconnector actually measures) into an estimated GB. Explicitly
# documented as an approximation in docs/cost-model.md — not an exact
# measurement of network/disk bytes.
BYTES_PER_RECORD = {
    "logs": 256,
    "spans": 512,
    "datapoints": 64,
}

DEFAULT_COST_PER_GB_HOT = 0.50
DEFAULT_COST_PER_GB_WARM = 0.023


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_policies(catalog: dict, routing: dict, budget: dict) -> None:
    jsonschema_validate(catalog, load_yaml_json(SCHEMA_DIR / "service-catalog.schema.json"))
    jsonschema_validate(routing, load_yaml_json(SCHEMA_DIR / "routing-policy.schema.json"))
    jsonschema_validate(budget, load_yaml_json(SCHEMA_DIR / "cost-budget.schema.json"))

    names = [s["name"] for s in catalog["services"]]
    if len(names) != len(set(names)):
        raise ValueError("service-catalog.yaml: duplicate service names")

    budget_services = {b["service"] for b in budget["budgets"]}
    missing = set(names) - budget_services
    if missing:
        raise ValueError(f"cost-budget.yaml: services with no budget defined: {sorted(missing)}")


def load_yaml_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def policy_version(catalog: dict, routing: dict, budget: dict) -> str:
    """Deterministic hash of the active policy — becomes the policy.version
    attribute attached to every routed signal, for auditing ("under which
    policy was this data classified")."""
    blob = json.dumps([catalog, routing, budget], sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def fetch_over_budget_services(prometheus_url: str) -> set:
    query = "policy:over_budget:by_service == 1"
    url = f"{prometheus_url.rstrip('/')}/api/v1/query?query={urllib.request.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[policy-compiler] warning: could not query Prometheus ({exc}); "
              f"dynamic budget downgrade NOT applied in this compilation.", file=sys.stderr)
        return set()

    services = set()
    for result in data.get("data", {}).get("result", []):
        service = result.get("metric", {}).get("service_name")
        if service:
            services.add(service)
    return services


# ---------------------------------------------------------------------------
# Tagging: resource.attributes["service.tier"/"team"/"cost_center"/"compliance_hold"]
# from the service catalog, applied equally to logs/traces/metrics.
# ---------------------------------------------------------------------------

def build_tagging_statements(catalog: dict) -> list:
    statements = []
    for svc in catalog["services"]:
        cond = f'resource.attributes["service.name"] == "{svc["name"]}"'
        statements.append(f'set(resource.attributes["service.tier"], "{svc["tier"]}") where {cond}')
        statements.append(f'set(resource.attributes["team"], "{svc["team"]}") where {cond}')
        statements.append(f'set(resource.attributes["cost_center"], "{svc["cost_center"]}") where {cond}')
        statements.append(
            f'set(resource.attributes["compliance_hold"], {str(svc["compliance_hold"]).lower()}) where {cond}'
        )
    return statements


# ---------------------------------------------------------------------------
# telemetry.tier decision — emulates "first matching rule wins" via
# resource.attributes["telemetry.tier"] == nil guards between steps, since
# OTTL has no native if/elif.
# ---------------------------------------------------------------------------

SIGNAL_ERROR_CONDITION = {
    "log": 'severity_number >= SEVERITY_NUMBER_ERROR',
    "span": 'status.code == STATUS_CODE_ERROR or attributes["http.status_code"] >= 500',
    "metric": 'IsMatch(metric.name, "^(.*_latency_seconds|.*_error_rate|.*_request_count)$")',
}

BASE_TIER_DECISION = {"critical": "warm", "standard": "warm", "low": "drop"}
ERROR_UPGRADE_DECISION = {"critical": "hot", "standard": "hot", "low": "warm"}


def build_tier_decision_statements(signal: str, over_budget_services: set) -> list:
    error_cond = SIGNAL_ERROR_CONDITION[signal]
    stmts = []

    # 1. Compliance override — always warm, takes priority over everything.
    stmts.append(
        'set(resource.attributes["telemetry.tier"], "warm") '
        'where resource.attributes["compliance_hold"] == true'
    )

    # 2. Error/SLO-relevant signal moves up a level (only if not already decided by rule 1).
    for tier, decision in ERROR_UPGRADE_DECISION.items():
        stmts.append(
            f'set(resource.attributes["telemetry.tier"], "{decision}") '
            f'where resource.attributes["telemetry.tier"] == nil '
            f'and resource.attributes["service.tier"] == "{tier}" '
            f'and ({error_cond})'
        )

    # 3. Base classification by criticality tier (catch-all, only if not yet decided).
    for tier, decision in BASE_TIER_DECISION.items():
        stmts.append(
            f'set(resource.attributes["telemetry.tier"], "{decision}") '
            f'where resource.attributes["telemetry.tier"] == nil '
            f'and resource.attributes["service.tier"] == "{tier}"'
        )

    # 4. Dynamic downgrade under budget pressure (poor man's OpAMP): only
    #    applied to services flagged over_budget in this compilation, and
    #    never to error signals (diagnosability always beats cost).
    for service in sorted(over_budget_services):
        svc_cond = f'resource.attributes["service.name"] == "{service}"'
        for from_tier, to_tier in TIER_DOWNGRADE.items():
            stmts.append(
                f'set(resource.attributes["telemetry.tier"], "{to_tier}") '
                f'where {svc_cond} '
                f'and resource.attributes["telemetry.tier"] == "{from_tier}" '
                f'and not ({error_cond})'
            )

    return stmts


def transform_processor_block(signal_key: str, statement_group_key: str, tagging_stmts: list,
                               tier_stmts: list, version: str) -> dict:
    return {
        "error_mode": "ignore",
        statement_group_key: [
            {"context": "resource", "statements": tagging_stmts + [
                f'set(resource.attributes["policy.version"], "{version}")'
            ]},
            {"context": signal_key, "statements": tier_stmts},
        ],
    }


# ---------------------------------------------------------------------------
# Static Collector skeleton (receivers/exporters/extensions/pipelines).
# ---------------------------------------------------------------------------

def build_config(catalog: dict, routing: dict, budget: dict, version: str,
                  over_budget_services: set) -> dict:
    tagging = build_tagging_statements(catalog)

    tag_logs = transform_processor_block("log", "log_statements", tagging,
                                          build_tier_decision_statements("log", over_budget_services), version)
    tag_traces = transform_processor_block("span", "trace_statements", tagging,
                                            build_tier_decision_statements("span", over_budget_services), version)
    tag_metrics = transform_processor_block("metric", "metric_statements", tagging,
                                             build_tier_decision_statements("metric", over_budget_services), version)

    def routing_table(signal_pipeline_prefix: str) -> dict:
        return {
            "default_pipelines": [f"{signal_pipeline_prefix}/warm"],
            "error_mode": "ignore",
            "table": [
                {"statement": 'route() where resource.attributes["telemetry.tier"] == "hot"',
                 "pipelines": [f"{signal_pipeline_prefix}/hot"]},
                {"statement": 'route() where resource.attributes["telemetry.tier"] == "warm"',
                 "pipelines": [f"{signal_pipeline_prefix}/warm"]},
                {"statement": 'route() where resource.attributes["telemetry.tier"] == "drop"',
                 "pipelines": [f"{signal_pipeline_prefix}/drop"]},
            ],
        }

    cost_dimensions = [{"key": k} for k in ("service.name", "team", "cost_center", "telemetry.tier")]

    def count_connector(signal_key: str, metric_name: str) -> dict:
        # Real countconnector (contrib) schema: top-level "spans"/"logs"/"datapoints",
        # each mapping a metric name -> {description, attributes}.
        return {signal_key: {metric_name: {
            "description": f"Count of routed {signal_key}, by service/team/cost_center/tier",
            "attributes": cost_dimensions,
        }}}

    config = {
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": "0.0.0.0:4317"},
                    "http": {"endpoint": "0.0.0.0:4318"},
                }
            }
        },
        "processors": {
            "batch": {},
            "transform/tag_logs": tag_logs,
            "transform/tag_traces": tag_traces,
            "transform/tag_metrics": tag_metrics,
            "tail_sampling": {
                "decision_wait": "5s",
                "policies": [
                    {"name": "always-sample-errors", "type": "status_code",
                     "status_code": {"status_codes": ["ERROR"]}},
                    {"name": "sample-slow-traces", "type": "latency",
                     "latency": {"threshold_ms": 500}},
                    {"name": "probabilistic-rest", "type": "probabilistic",
                     "probabilistic": {"sampling_percentage": 20}},
                ],
            },
        },
        "connectors": {
            "routing/logs": routing_table("logs"),
            "routing/traces": routing_table("traces"),
            "routing/metrics": routing_table("metrics"),
            "count/logs_all": count_connector("logs", "logs.count.by_service"),
            "count/traces_all": count_connector("spans", "spans.count.by_service"),
            "count/metrics_all": count_connector("datapoints", "datapoints.count.by_service"),
        },
        "exporters": {
            "otlp/tempo": {"endpoint": "tempo:4317", "tls": {"insecure": True}},
            "otlphttp/loki": {"endpoint": "http://loki:3100/otlp"},
            "prometheusremotewrite/hot": {"endpoint": "http://prometheus:9090/api/v1/write"},
            "awss3/warm": {
                "s3uploader": {
                    "region": "us-east-1",
                    "s3_bucket": "warm-tier",
                    "s3_prefix": "otel",
                    "s3_partition": "minute",
                    "endpoint": "http://minio:9000",
                    "s3_force_path_style": True,
                    "disable_ssl": True,
                },
                "marshaler": "otlp_json",
            },
            "debug/audit": {"verbosity": "basic", "sampling_initial": 1, "sampling_thereafter": 1000},
            "prometheus/self": {"endpoint": "0.0.0.0:8889"},
        },
        "extensions": {"health_check": {"endpoint": "0.0.0.0:13133"}},
        "service": {
            "extensions": ["health_check"],
            "telemetry": {"metrics": {"level": "detailed", "address": "0.0.0.0:8888"}},
            "pipelines": {
                "logs/in": {"receivers": ["otlp"], "processors": ["transform/tag_logs"],
                            "exporters": ["routing/logs"]},
                "logs/hot": {"receivers": ["routing/logs"], "processors": ["batch"],
                             "exporters": ["otlphttp/loki", "count/logs_all"]},
                "logs/warm": {"receivers": ["routing/logs"], "processors": ["batch"],
                              "exporters": ["awss3/warm", "count/logs_all"]},
                "logs/drop": {"receivers": ["routing/logs"], "processors": ["batch"],
                              "exporters": ["debug/audit", "count/logs_all"]},

                "traces/in": {"receivers": ["otlp"], "processors": ["transform/tag_traces"],
                              "exporters": ["routing/traces"]},
                "traces/hot": {"receivers": ["routing/traces"], "processors": ["tail_sampling", "batch"],
                               "exporters": ["otlp/tempo", "count/traces_all"]},
                "traces/warm": {"receivers": ["routing/traces"], "processors": ["batch"],
                                "exporters": ["awss3/warm", "count/traces_all"]},
                "traces/drop": {"receivers": ["routing/traces"],
                                 "processors": ["batch"],
                                 "exporters": ["debug/audit", "count/traces_all"]},

                "metrics/in": {"receivers": ["otlp"], "processors": ["transform/tag_metrics"],
                               "exporters": ["routing/metrics"]},
                "metrics/hot": {"receivers": ["routing/metrics"], "processors": ["batch"],
                                "exporters": ["prometheusremotewrite/hot", "count/metrics_all"]},
                "metrics/warm": {"receivers": ["routing/metrics"], "processors": ["batch"],
                                 "exporters": ["awss3/warm", "count/metrics_all"]},
                "metrics/drop": {"receivers": ["routing/metrics"],
                                  "processors": ["batch"],
                                  "exporters": ["debug/audit", "count/metrics_all"]},

                # Destination pipelines for the count connectors (logs/traces/metrics ->
                # count metrics by service/team/cost_center/tier). This is the series
                # that feeds the cost showback (see docs/cost-model.md).
                "metrics/cost_from_logs": {"receivers": ["count/logs_all"], "processors": ["batch"],
                                           "exporters": ["prometheus/self"]},
                "metrics/cost_from_traces": {"receivers": ["count/traces_all"], "processors": ["batch"],
                                             "exporters": ["prometheus/self"]},
                "metrics/cost_from_metrics": {"receivers": ["count/metrics_all"], "processors": ["batch"],
                                              "exporters": ["prometheus/self"]},
            },
        },
    }
    return config


def build_prometheus_rules(budget: dict, cost_per_gb_hot: float, cost_per_gb_warm: float) -> dict:
    """Recording rules derived from the same policy:
    - policy:volume_gb:by_service_tier  -> estimated volume (GB) by service/team/cost_center/tier
    - policy:volume_gb:by_service       -> aggregated by service, compared against budget_gb
    - policy:over_budget:by_service     -> 1/0 per service, consumed by compile.py --prometheus-url
    - cost:downgrade_saving_usd:*       -> saving from reclassifying hot->warm
    - cost:drop_saving_usd:*            -> saving from discarding (drop branch)
    - cost:residual_usd:*               -> cost still being paid (hot+warm)

    Documented approximation: volume in GB is estimated from record counts
    x an average size per signal type (BYTES_PER_RECORD), not from an exact
    measurement of network/disk bytes — see docs/cost-model.md.
    """
    # Note: direct addition assumes the three count connectors share the
    # same label set (service_name/team/cost_center/telemetry_tier) — true
    # in this config, since they use the same cost_dimensions. A series
    # only appears once at least one signal of that type has been emitted;
    # that's acceptable for the demo (see docs/cost-model.md).
    volume_expr = (
        "(\n"
        f"    logs_count_by_service_total * {BYTES_PER_RECORD['logs']}\n"
        f"  + spans_count_by_service_total * {BYTES_PER_RECORD['spans']}\n"
        f"  + datapoints_count_by_service_total * {BYTES_PER_RECORD['datapoints']}\n"
        ") / 1e9"
    )

    rules = [
        {"record": "policy:volume_gb:by_service_tier", "expr": volume_expr},
        {"record": "policy:volume_gb:by_service",
         "expr": "sum by (service_name) (policy:volume_gb:by_service_tier)"},
        {"record": "cost:downgrade_saving_usd:by_service",
         "expr": f'policy:volume_gb:by_service_tier{{telemetry_tier="warm"}} * '
                 f'({cost_per_gb_hot} - {cost_per_gb_warm})'},
        {"record": "cost:drop_saving_usd:by_service",
         "expr": f'policy:volume_gb:by_service_tier{{telemetry_tier="drop"}} * {cost_per_gb_hot}'},
        {"record": "cost:residual_usd:by_service_tier",
         "expr": f'(policy:volume_gb:by_service_tier{{telemetry_tier="hot"}} * {cost_per_gb_hot})\n'
                 f'  or (policy:volume_gb:by_service_tier{{telemetry_tier="warm"}} * {cost_per_gb_warm})'},
    ]

    for b in budget["budgets"]:
        rules.append({
            "record": "policy:over_budget:by_service",
            "expr": f'policy:volume_gb:by_service{{service_name="{b["service"]}"}} > bool {b["budget_gb"]}',
        })

    return {"groups": [{"name": "otel-cost-governance", "interval": "30s", "rules": rules}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", default=None,
                         help="If given, queries policy:over_budget:by_service and applies "
                              "a dynamic tier downgrade to over-budget services.")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--prometheus-rules-output", default=str(PROMETHEUS_RULES_PATH))
    parser.add_argument("--cost-per-gb-hot", type=float, default=DEFAULT_COST_PER_GB_HOT,
                         help="Should mirror COST_PER_GB_HOT from .env")
    parser.add_argument("--cost-per-gb-warm", type=float, default=DEFAULT_COST_PER_GB_WARM,
                         help="Should mirror COST_PER_GB_WARM from .env")
    args = parser.parse_args()

    catalog = load_yaml(POLICY_DIR / "service-catalog.yaml")
    routing = load_yaml(POLICY_DIR / "routing-policy.yaml")
    budget = load_yaml(POLICY_DIR / "cost-budget.yaml")

    validate_policies(catalog, routing, budget)
    version = policy_version(catalog, routing, budget)

    over_budget_services = set()
    if args.prometheus_url:
        over_budget_services = fetch_over_budget_services(args.prometheus_url)
        if over_budget_services:
            print(f"[policy-compiler] dynamic downgrade applied to: {sorted(over_budget_services)}")

    config = build_config(catalog, routing, budget, version, over_budget_services)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# AUTO-GENERATED by policy-compiler/compile.py — DO NOT HAND-EDIT.\n"
        f"# policy.version={version}\n"
        f"# Source: policy/service-catalog.yaml, policy/routing-policy.yaml, policy/cost-budget.yaml\n"
        f"# Dynamic downgrade applied in this compilation: {sorted(over_budget_services) or 'none'}\n\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False, width=100)

    print(f"[policy-compiler] OK — policy.version={version} -> {output_path.relative_to(REPO_ROOT)}")

    rules = build_prometheus_rules(budget, args.cost_per_gb_hot, args.cost_per_gb_warm)
    rules_path = Path(args.prometheus_rules_output)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_header = (
        "# AUTO-GENERATED by policy-compiler/compile.py — DO NOT HAND-EDIT.\n"
        f"# policy.version={version}  cost_per_gb_hot={args.cost_per_gb_hot}  "
        f"cost_per_gb_warm={args.cost_per_gb_warm}\n\n"
    )
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(rules_header)
        yaml.safe_dump(rules, f, sort_keys=False, default_flow_style=False, width=100)

    print(f"[policy-compiler] OK -> {rules_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
