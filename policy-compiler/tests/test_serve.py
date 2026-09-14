"""Integration test for `policyctl serve` — the on-demand OTTL preview endpoint
the web editor calls (POST /api/compile)."""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pc = _load("policyctl_mod", REPO_ROOT / "policy-compiler" / "policyctl.py")


def _post(port, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/compile",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_api_compile_roundtrip_and_error():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), pc._EditorHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        routing = yaml.safe_load((REPO_ROOT / "policy" / "routing-policy.yaml").read_text())

        # current routing compiles and equals the committed artifact (empty diff)
        code, data = _post(port, {"routing": routing})
        assert code == 200, data
        assert data["diff"] == ""
        assert data["version"] == data["committed_version"]

        # a new env rule produces a visible OTTL diff
        modified = json.loads(json.dumps(routing))
        modified["rules"].insert(2, {
            "id": "prod-hot", "when": {"any_of": [{"env": ["prod"]}]},
            "decision": "hot", "reason": "prod up",
        })
        code, data = _post(port, {"routing": modified})
        assert code == 200
        assert 'deployment.environment' in data["diff"]

        # invalid enum -> 400 with a clean error message (no traceback/HTML)
        bad = {"version": 1, "default_decision": "warm",
               "rules": [{"id": "x", "when": {"span_status": "info"},
                          "decision": "warm", "reason": "x"}]}
        code, data = _post(port, {"routing": bad})
        assert code == 400
        assert "error" in data and "OK" in data["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()
