#!/usr/bin/env python3
"""policyctl — author and operate the governance policy.

A thin, dependency-light CLI (stdlib only, reusing policy-compiler/compile.py) that
gives a simple/scriptable surface to the same GitOps policy the web editor edits
visually. Everything it does ends as an edit to policy/*.yaml (the source of
truth) plus a compiled artifact — never a second source of truth.

Commands:
  validate                    Validate the three policies (schema + vocabulary + integrity).
  compile [--dry-run]         Compile; --dry-run prints the OTTL/rules diff + a policy
                              summary instead of writing (what CI comments on a PR).
  new-rule                    Add a routing rule (interactive wizard, or --from-json for
                              the web editor / automation), validate, show the OTTL diff.
  add-service                 Add a service to the catalog (+ its budget).
  set-budget                  Set a service's volume budget (GB).
  record-deploy --env E       Append a deployment record to deployments/ledger.jsonl
                              (traceability). Called by the dev/uat pipelines and make deploy-*.
  ledger [--env E]            Show the deployment ledger.
  rollback --env E [--to REF] Roll policy + generated artifacts back to a previous
                              policy.version / git SHA and record the rollback.
  serve [--port 8000] [--apply]  Serve the web editor + /api/compile (OTTL preview).
                              With --apply also enable /api/save (write + compile) and
                              /api/apply (also restart the local collector) — localhost only.

See docs/governance-authoring.md.
"""
import argparse
import datetime as _dt
import difflib
import io
import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

# compile.py lives next to this file; sys.path[0] is this dir when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile as compiler  # noqa: E402  (local module, not the builtin)

REPO_ROOT = compiler.REPO_ROOT
POLICY_DIR = compiler.POLICY_DIR
LEDGER_PATH = REPO_ROOT / "deployments" / "ledger.jsonl"
COLLECTOR_OUT = REPO_ROOT / "collector" / "config" / "otelcol-config.generated.yaml"
PROM_OUT = REPO_ROOT / "prometheus" / "rules" / "cost-rules.generated.yaml"
ROUTING_PATH = POLICY_DIR / "routing-policy.yaml"
CATALOG_PATH = POLICY_DIR / "service-catalog.yaml"
BUDGET_PATH = POLICY_DIR / "cost-budget.yaml"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _load_all():
    return (
        compiler.load_yaml(CATALOG_PATH),
        compiler.load_yaml(ROUTING_PATH),
        compiler.load_yaml(BUDGET_PATH),
    )


def _dump_yaml(obj):
    buf = io.StringIO()
    yaml.safe_dump(obj, buf, sort_keys=False, default_flow_style=False, width=100)
    return buf.getvalue()


def _strip_header(text):
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        i += 1
    return "".join(lines[i:])


def _committed_version():
    try:
        for line in COLLECTOR_OUT.read_text().splitlines():
            if line.startswith("# policy.version="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return "(none)"


def _git(*args, check=True, capture=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, text=True,
                          capture_output=capture, check=check)


def _print_diff(old_body, new_body, label):
    diff = list(difflib.unified_diff(old_body.splitlines(), new_body.splitlines(),
                                     fromfile=f"a/{label}", tofile=f"b/{label}", lineterm=""))
    if not diff:
        print(f"  (no change in {label})")
        return False
    for line in diff:
        print(line)
    return True


def _policy_summary(catalog, routing, budget):
    tiers = {}
    for s in catalog["services"]:
        tiers[s["tier"]] = tiers.get(s["tier"], 0) + 1
    total_budget = sum(b["budget_gb"] for b in budget["budgets"])
    holds = [s["name"] for s in catalog["services"] if s.get("compliance_hold")]
    return (
        f"  services: {len(catalog['services'])}  "
        f"(by tier: {', '.join(f'{k}={v}' for k, v in sorted(tiers.items()))})\n"
        f"  routing rules: {len(routing['rules'])}   compliance holds: {len(holds)}\n"
        f"  total budget: {total_budget:g} GB / {budget.get('window', '?')}"
    )


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #

def cmd_validate(_args):
    catalog, routing, budget = _load_all()
    compiler.validate_policies(catalog, routing, budget)
    version = compiler.policy_version(catalog, routing, budget)
    print(f"[policyctl] OK — policies valid. policy.version={version}")
    print(_policy_summary(catalog, routing, budget))
    return 0


# --------------------------------------------------------------------------- #
# compile (--dry-run prints diff + summary; otherwise delegates to compile.py)
# --------------------------------------------------------------------------- #

def cmd_compile(args):
    catalog, routing, budget = _load_all()
    if not args.dry_run:
        cmd = [sys.executable, str(REPO_ROOT / "policy-compiler" / "compile.py")]
        if args.prometheus_url:
            cmd += ["--prometheus-url", args.prometheus_url]
        return subprocess.run(cmd, cwd=REPO_ROOT).returncode

    result = compiler.compile_all(catalog, routing, budget)
    new_collector = _dump_yaml(result["config"])
    new_prom = _dump_yaml(result["prometheus_rules"])
    old_collector = _strip_header(COLLECTOR_OUT.read_text()) if COLLECTOR_OUT.exists() else ""
    old_prom = _strip_header(PROM_OUT.read_text()) if PROM_OUT.exists() else ""

    print(f"[policyctl] dry-run — committed policy.version={_committed_version()} "
          f"-> new policy.version={result['version']}\n")
    print("Policy summary:")
    print(_policy_summary(catalog, routing, budget), "\n")
    print("=== collector OTTL diff ===")
    c1 = _print_diff(old_collector, new_collector, "otelcol-config.generated.yaml")
    print("\n=== prometheus rules diff ===")
    c2 = _print_diff(old_prom, new_prom, "cost-rules.generated.yaml")
    if not (c1 or c2):
        print("\n[policyctl] no changes — generated artifacts already up to date.")
    else:
        print("\n[policyctl] run `make compile-policy` to write these changes.")
    return 0


# --------------------------------------------------------------------------- #
# new-rule
# --------------------------------------------------------------------------- #

def _prompt(msg, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{msg}{suffix}: ").strip()
    return val or (default if default is not None else "")


def _prompt_nonempty(msg):
    while True:
        v = input(f"{msg}: ").strip()
        if v:
            return v
        print("  required — please enter a value")


def _prompt_choice(msg, options, default=None):
    joined = "/".join(options)
    while True:
        raw = input(f"{msg} ({joined}){f' [{default}]' if default else ''}: ").strip()
        val = raw or default
        if val in options:
            return val
        print(f"  must be one of: {', '.join(options)}")


def _prompt_value(key, spec):
    """Prompt for a condition value and validate it against conditions.json
    (enum / type / list membership), re-prompting until it is valid."""
    v = spec["value"]
    t = v["type"]
    enum = v.get("enum")
    item_enum = v.get("item_enum")
    if enum:
        hint = "/".join(enum)
    elif item_enum:
        hint = f"any of {', '.join(item_enum)} (space/comma-separated)"
    else:
        hint = t
    while True:
        raw = input(f"  value for {key} ({hint}): ").strip()
        if t == "boolean":
            low = raw.lower()
            if low in ("true", "1", "yes", "y"):
                return True
            if low in ("false", "0", "no", "n"):
                return False
            print("  enter true or false"); continue
        if not raw and t != "array":
            print("  required"); continue
        try:
            val = _coerce_value(v, raw)
        except (ValueError, TypeError):
            print(f"  invalid {t}"); continue
        if t == "string" and enum and val not in enum:
            print(f"  must be one of: {', '.join(enum)}"); continue
        if t == "array":
            if not val:
                print("  select at least one value"); continue
            if item_enum and [x for x in val if x not in item_enum]:
                print(f"  must be from: {', '.join(item_enum)}"); continue
        return val


def _wizard_build_rule(conditions, existing_ids):
    print("\n-- New routing rule --")
    existing = set(existing_ids)
    while True:
        rule_id = _prompt_nonempty("rule id (kebab-case)")
        if rule_id in existing:
            print(f"  a rule with id '{rule_id}' already exists — choose another"); continue
        break
    reason = _prompt_nonempty("reason (human-readable, required for audit)")

    cond_keys = [k for k, s in conditions["conditions"].items()
                 if not s.get("compile_time") and not s.get("negates_family")]
    print("\nAvailable conditions:")
    for i, k in enumerate(cond_keys):
        spec = conditions["conditions"][k]
        print(f"  [{i}] {k} — {spec['label']} (signals: {', '.join(spec['signals'])})")

    atoms = []
    while True:
        raw = input("add condition # (blank to finish): ").strip()
        if raw == "":
            if not atoms:
                print("  add at least one condition (or use '(always match)' via any_of in the editor)")
                # allow a deliberate catch-all: confirm empty
                if input("  create rule with NO conditions (matches nothing useful)? (y/N): ").strip().lower() != "y":
                    continue
            break
        try:
            key = cond_keys[int(raw)]
        except (ValueError, IndexError):
            print("  invalid selection"); continue
        atoms.append({key: _prompt_value(key, conditions["conditions"][key])})

    when = {}
    if len(atoms) == 1:
        when = atoms[0]
    elif len(atoms) > 1:
        when[_prompt_choice("combine as", ["any_of", "all_of"], "any_of")] = atoms

    rule = {"id": rule_id, "when": when, "reason": reason}
    if _prompt_choice("decision kind", ["flat", "by_tier"], "flat") == "by_tier":
        opts = conditions["decisions"]["by_tier"]
        rule["decision_by_tier"] = {
            tier: _prompt_choice(f"  decision for {tier} tier", opts, "warm")
            for tier in conditions["tiers"]
        }
    else:
        rule["decision"] = _prompt_choice("decision", conditions["decisions"]["flat"], "warm")
    return rule


def _coerce_value(value_spec, raw):
    t = value_spec.get("type")
    if t == "boolean":
        return raw.lower() in ("true", "1", "yes", "y")
    if t == "integer":
        return int(raw)
    if t == "number":
        return float(raw)
    if t == "array":
        return [x.strip() for x in raw.replace(",", " ").split() if x.strip()]
    return raw


def _insert_rule_text(text, rule, before=None, at=None):
    """Insert a serialized rule into routing-policy.yaml text, preserving all
    existing comments. Position: before a given rule id, at an index in the rules
    list, or (default) at the end of the list just above default_decision."""
    rule_yaml = _dump_yaml([rule])
    block = "\n" + "".join("  " + ln if ln.strip() else ln
                           for ln in rule_yaml.splitlines(keepends=True))
    if not block.endswith("\n"):
        block += "\n"

    lines = text.splitlines(keepends=True)
    # map rule id -> line index of its "- id:" line
    id_lines = {}
    order = []
    for idx, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.startswith("- id:"):
            rid = stripped.split(":", 1)[1].strip()
            id_lines[rid] = idx
            order.append((rid, idx))

    insert_at = None
    if before:
        if before not in id_lines:
            raise ValueError(f"--before: no rule with id '{before}'")
        insert_at = id_lines[before]
    elif at is not None:
        if at < len(order):
            insert_at = order[at][1]
        else:
            insert_at = None  # end
    if insert_at is None:
        # default: just above default_decision (and its leading comment block)
        dd = next((i for i, ln in enumerate(lines) if ln.startswith("default_decision:")), len(lines))
        j = dd
        while j > 0 and (lines[j - 1].lstrip().startswith("#") or lines[j - 1].strip() == ""):
            j -= 1
        insert_at = j
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def cmd_new_rule(args):
    conditions = compiler.load_conditions()
    catalog, routing, budget = _load_all()
    if args.from_json:
        rule = json.loads(Path(args.from_json).read_text())
    else:
        existing_ids = [r.get("id", "") for r in routing.get("rules", [])]
        rule = _wizard_build_rule(conditions, existing_ids)

    # Validate the rule in-memory before touching the file (clear error, no traceback).
    trial = json.loads(json.dumps(routing))  # deep copy
    trial["rules"].append(rule)
    compiler.validate_policies(catalog, trial, budget)

    old_text = ROUTING_PATH.read_text()
    new_text = _insert_rule_text(old_text, rule, before=args.before, at=args.at)
    new_routing = yaml.safe_load(new_text)
    compiler.validate_policies(catalog, new_routing, budget)
    old_cfg = _dump_yaml(compiler.compile_all(catalog, routing, budget)["config"])
    new_cfg = _dump_yaml(compiler.compile_all(catalog, new_routing, budget)["config"])

    def _show_diffs():
        print("\n=== routing-policy.yaml diff ===")
        _print_diff(old_text, new_text, "routing-policy.yaml")
        print("\n=== resulting collector OTTL diff ===")
        _print_diff(old_cfg, new_cfg, "otelcol-config.generated.yaml")

    if args.yes:
        # Automation/editor path: commit the write first so a closed output pipe
        # (e.g. piping to `head`) can never lose the change, then show the diffs.
        ROUTING_PATH.write_text(new_text)
        _show_diffs()
    else:
        _show_diffs()
        if _prompt("\nwrite this rule to routing-policy.yaml? (y/N)", "N").lower() != "y":
            print("[policyctl] aborted — nothing written.")
            return 1
        ROUTING_PATH.write_text(new_text)
    print(f"[policyctl] wrote rule '{rule['id']}' to routing-policy.yaml")
    print("[policyctl] next: `make compile-policy` then open a PR (dev pipeline validates it).")
    return 0


# --------------------------------------------------------------------------- #
# add-service / set-budget
# --------------------------------------------------------------------------- #

def cmd_add_service(args):
    catalog, routing, budget = _load_all()
    if any(s["name"] == args.name for s in catalog["services"]):
        print(f"[policyctl] service '{args.name}' already exists"); return 1
    catalog["services"].append({
        "name": args.name, "tier": args.tier, "team": args.team,
        "cost_center": args.cost_center, "compliance_hold": args.compliance_hold,
    })
    budget["budgets"].append({"service": args.name, "budget_gb": args.budget_gb})
    compiler.validate_policies(catalog, routing, budget)
    CATALOG_PATH.write_text(_preserving_header(CATALOG_PATH) + _dump_yaml(catalog))
    BUDGET_PATH.write_text(_preserving_header(BUDGET_PATH) + _dump_yaml(budget))
    print(f"[policyctl] added service '{args.name}' (tier={args.tier}, budget={args.budget_gb} GB)")
    print("[policyctl] next: `make compile-policy` then open a PR.")
    return 0


def cmd_set_budget(args):
    catalog, routing, budget = _load_all()
    found = False
    for b in budget["budgets"]:
        if b["service"] == args.service:
            b["budget_gb"] = args.budget_gb
            found = True
    if not found:
        print(f"[policyctl] no budget entry for '{args.service}'"); return 1
    compiler.validate_policies(catalog, routing, budget)
    BUDGET_PATH.write_text(_preserving_header(BUDGET_PATH) + _dump_yaml(budget))
    print(f"[policyctl] set budget for '{args.service}' = {args.budget_gb} GB")
    return 0


def _preserving_header(path):
    """Keep the leading comment block of a hand-authored policy file when rewriting it."""
    lines = path.read_text().splitlines(keepends=True)
    header = []
    for ln in lines:
        if ln.startswith("#") or ln.strip() == "":
            header.append(ln)
        else:
            break
    return "".join(header)


# --------------------------------------------------------------------------- #
# deployment ledger (traceability) + rollback
# --------------------------------------------------------------------------- #

def _ledger_records():
    if not LEDGER_PATH.exists():
        return []
    return [json.loads(ln) for ln in LEDGER_PATH.read_text().splitlines() if ln.strip()]


def _append_ledger(rec):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def cmd_record_deploy(args):
    catalog, routing, budget = _load_all()
    version = compiler.policy_version(catalog, routing, budget)
    try:
        sha = _git("rev-parse", "HEAD").stdout.strip()
    except subprocess.CalledProcessError:
        sha = args.sha or "unknown"
    rec = {
        "action": args.action,
        "env": args.env,
        "policy_version": version,
        "git_sha": args.sha or sha,
        "actor": args.actor or os.environ.get("GITHUB_ACTOR") or os.environ.get("USER", "unknown"),
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if args.note:
        rec["note"] = args.note
    _append_ledger(rec)
    print(f"[policyctl] recorded {rec['action']} to {rec['env']}: "
          f"policy.version={rec['policy_version']} sha={rec['git_sha'][:12]} @ {rec['timestamp']}")
    return 0


def cmd_ledger(args):
    recs = _ledger_records()
    if args.env:
        recs = [r for r in recs if r.get("env") == args.env]
    if not recs:
        print("[policyctl] no deployment records yet."); return 0
    for r in recs:
        note = f"  # {r['note']}" if r.get("note") else ""
        print(f"{r['timestamp']}  {r['env']:<4}  {r['action']:<8}  "
              f"policy.version={r['policy_version']}  sha={r['git_sha'][:12]}  "
              f"by {r['actor']}{note}")
    return 0


def _resolve_rollback_target(env, ref):
    recs = [r for r in _ledger_records() if r.get("env") == env and r.get("action") == "deploy"]
    if ref:
        for r in reversed(recs):
            if r["policy_version"] == ref or r["git_sha"].startswith(ref):
                return r
        # allow rolling back to an arbitrary sha not in the ledger
        return {"git_sha": ref, "policy_version": "(unknown)"}
    if len(recs) < 2:
        raise ValueError(f"not enough deploy history for env '{env}' to auto-pick a previous version; "
                         f"pass --to <policy.version|sha>")
    return recs[-2]


def cmd_rollback(args):
    target = _resolve_rollback_target(args.env, args.to)
    sha = target["git_sha"]
    print(f"[policyctl] rollback {args.env} -> policy.version={target['policy_version']} sha={sha[:12]}")
    paths = ["policy", "collector/config/otelcol-config.generated.yaml",
             "prometheus/rules/cost-rules.generated.yaml"]
    if not args.yes:
        if _prompt(f"restore {', '.join(paths)} from {sha[:12]}? (y/N)", "N").lower() != "y":
            print("[policyctl] aborted."); return 1
    _git("checkout", sha, "--", *paths, check=True, capture=False)
    _append_ledger({
        "action": "rollback", "env": args.env,
        "policy_version": target["policy_version"], "git_sha": sha,
        "actor": args.actor or os.environ.get("GITHUB_ACTOR") or os.environ.get("USER", "unknown"),
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "note": f"rollback to {target['policy_version']}",
    })
    print(f"[policyctl] restored. Re-apply with `make deploy-{args.env}` "
          f"(or commit these files and let the {args.env} pipeline apply them).")
    return 0


# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# serve — static editor + on-demand compile (authoritative OTTL preview)
# --------------------------------------------------------------------------- #

class _EditorHandler(SimpleHTTPRequestHandler):
    """Serves the repo statically (so the web editor can read policy/*.yaml and
    conditions.json) and adds JSON endpoints:
      POST /api/compile  — compile a posted routing policy, return the OTTL diff
                           (read-only preview; always on).
      POST /api/save     — write routing-policy.yaml + regenerate artifacts.
      POST /api/apply    — save, then restart the local collector + record deploy.
    The two mutating endpoints require `policyctl serve --apply` (allow_write) and
    only accept localhost Host headers. They edit the working tree locally — they
    never push or bypass the PR/CI governance path."""

    allow_write = False  # set by cmd_serve when --apply is passed

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def log_message(self, *args):  # keep the console quiet
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or "{}")

    def _host_is_local(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("localhost", "127.0.0.1", "")

    def do_POST(self):
        route = self.path.rstrip("/")
        actions = {"/api/compile": self._compile, "/api/save": self._save, "/api/apply": self._apply}
        fn = actions.get(route)
        if fn is None:
            self.send_error(404, "not found")
            return
        if route in ("/api/save", "/api/apply"):
            if not type(self).allow_write:
                self._send_json(403, {"error": "write disabled — start `policyctl serve --apply`"})
                return
            if not self._host_is_local():
                self._send_json(403, {"error": "refused: non-localhost Host header"})
                return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — surface any error as JSON, not a 500 page
            self._send_json(400, {"error": str(exc)})

    def _compile(self):
        payload = self._read_body()
        routing = payload.get("routing")
        if routing is None:
            raise ValueError("missing 'routing' in request body")
        catalog = payload.get("catalog") or compiler.load_yaml(CATALOG_PATH)
        budget = payload.get("budget") or compiler.load_yaml(BUDGET_PATH)
        result = compiler.compile_all(catalog, routing, budget)
        new_collector = _dump_yaml(result["config"])
        old_collector = _strip_header(COLLECTOR_OUT.read_text()) if COLLECTOR_OUT.exists() else ""
        diff = "\n".join(difflib.unified_diff(
            old_collector.splitlines(), new_collector.splitlines(),
            fromfile="committed", tofile="new", lineterm=""))
        self._send_json(200, {
            "version": result["version"],
            "committed_version": _committed_version(),
            "collector_yaml": new_collector,
            "prometheus_yaml": _dump_yaml(result["prometheus_rules"]),
            "diff": diff,
            "summary": _policy_summary(catalog, routing, budget),
        })

    def _write_and_compile(self, routing):
        """Validate + write routing-policy.yaml (keeping its comment header) and
        regenerate the committed artifacts via compile.py. Returns a result dict."""
        catalog = compiler.load_yaml(CATALOG_PATH)
        budget = compiler.load_yaml(BUDGET_PATH)
        compiler.validate_policies(catalog, routing, budget)  # fail before writing
        ROUTING_PATH.write_text(_preserving_header(ROUTING_PATH) + _dump_yaml(routing))
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "policy-compiler" / "compile.py")],
            cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("compile failed: " + (proc.stderr or proc.stdout).strip())
        return {
            "ok": True,
            "version": compiler.policy_version(catalog, routing, budget),
            "summary": _policy_summary(catalog, routing, budget),
        }

    def _save(self):
        payload = self._read_body()
        routing = payload.get("routing")
        if routing is None:
            raise ValueError("missing 'routing' in request body")
        data = self._write_and_compile(routing)
        data["message"] = ("Saved routing-policy.yaml and regenerated the OTTL. "
                           "Commit and open a PR to govern the change.")
        self._send_json(200, data)

    def _apply(self):
        payload = self._read_body()
        routing = payload.get("routing")
        if routing is None:
            raise ValueError("missing 'routing' in request body")
        data = self._write_and_compile(routing)
        up = subprocess.run(["docker", "compose", "up", "-d"], cwd=REPO_ROOT,
                            capture_output=True, text=True)
        restart = subprocess.run(["docker", "compose", "restart", "otel-gateway-collector"],
                                cwd=REPO_ROOT, capture_output=True, text=True)
        data["applied"] = restart.returncode == 0
        if data["applied"]:
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "record-deploy", "--env", "dev", "--note", "editor apply"],
                           cwd=REPO_ROOT, capture_output=True, text=True)
            data["message"] = "Saved + applied to dev (collector restarted, ledger updated)."
        else:
            err = (restart.stderr or up.stderr or "docker not available").strip()
            data["message"] = "Saved, but apply skipped (local dev only): " + err[:200]
        self._send_json(200, data)

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def cmd_serve(args):
    _EditorHandler.allow_write = bool(args.apply)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), _EditorHandler)
    editor_url = f"http://localhost:{args.port}/tools/policy-editor/"
    mode = "read-write (save/apply enabled)" if args.apply else "read-only (preview only)"
    print(f"[policyctl] serving {REPO_ROOT} on http://localhost:{args.port}  [{mode}]")
    print(f"[policyctl] open the editor: {editor_url}")
    if args.apply:
        print("[policyctl] WARNING: /api/save and /api/apply write the working tree and "
              "restart the local collector. Localhost only — never expose this port.")
    print("[policyctl] Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[policyctl] stopped")
    finally:
        httpd.server_close()
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="policyctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="validate the policies").set_defaults(func=cmd_validate)

    c = sub.add_parser("compile", help="compile (or --dry-run to preview the diff)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--prometheus-url", default=None)
    c.set_defaults(func=cmd_compile)

    n = sub.add_parser("new-rule", help="add a routing rule")
    n.add_argument("--from-json", help="path to a rule JSON (e.g. exported by the web editor)")
    n.add_argument("--before", help="insert before the rule with this id")
    n.add_argument("--at", type=int, help="insert at this index in the rules list")
    n.add_argument("--yes", action="store_true", help="skip confirmation")
    n.set_defaults(func=cmd_new_rule)

    a = sub.add_parser("add-service", help="add a service to the catalog + budget")
    a.add_argument("--name", required=True)
    a.add_argument("--tier", required=True, choices=["critical", "standard", "low"])
    a.add_argument("--team", required=True)
    a.add_argument("--cost-center", required=True)
    a.add_argument("--compliance-hold", action="store_true")
    a.add_argument("--budget-gb", type=float, required=True)
    a.set_defaults(func=cmd_add_service)

    b = sub.add_parser("set-budget", help="set a service's budget (GB)")
    b.add_argument("--service", required=True)
    b.add_argument("--budget-gb", type=float, required=True)
    b.set_defaults(func=cmd_set_budget)

    r = sub.add_parser("record-deploy", help="append a deployment record to the ledger")
    r.add_argument("--env", required=True)
    r.add_argument("--action", default="deploy", choices=["deploy", "rollback"])
    r.add_argument("--sha", default=None)
    r.add_argument("--actor", default=None)
    r.add_argument("--note", default=None)
    r.set_defaults(func=cmd_record_deploy)

    lg = sub.add_parser("ledger", help="show the deployment ledger")
    lg.add_argument("--env", default=None)
    lg.set_defaults(func=cmd_ledger)

    rb = sub.add_parser("rollback", help="roll policy + artifacts back to a previous version")
    rb.add_argument("--env", required=True)
    rb.add_argument("--to", default=None, help="policy.version or git sha (default: previous deploy)")
    rb.add_argument("--actor", default=None)
    rb.add_argument("--yes", action="store_true")
    rb.set_defaults(func=cmd_rollback)

    sv = sub.add_parser("serve", help="serve the web editor + on-demand OTTL preview (POST /api/compile)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--apply", action="store_true",
                    help="enable /api/save and /api/apply so the editor can write the "
                         "working tree and restart the local collector (localhost only)")
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0  # output pipe closed early (e.g. `| head`) — not an error
    except (ValueError, FileNotFoundError) as exc:
        print(f"[policyctl] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
