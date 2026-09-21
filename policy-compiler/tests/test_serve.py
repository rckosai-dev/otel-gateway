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


def _post(port, body, path="/api/compile"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _serve(allow_write):
    pc._EditorHandler.allow_write = allow_write
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), pc._EditorHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


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


def test_write_endpoints_gated_by_apply_flag():
    """Without --apply (allow_write False), /api/save and /api/apply are refused."""
    httpd, port = _serve(False)
    try:
        routing = yaml.safe_load((REPO_ROOT / "policy" / "routing-policy.yaml").read_text())
        for endpoint in ("/api/save", "/api/apply"):
            code, data = _post(port, {"routing": routing}, path=endpoint)
            assert code == 403, endpoint
            assert "error" in data
    finally:
        httpd.shutdown()
        httpd.server_close()
        pc._EditorHandler.allow_write = False


def test_save_writes_and_regenerates_then_restore():
    """With --apply, /api/save writes routing-policy.yaml and regenerates the
    artifacts. Original bytes are restored in finally so the test is side-effect free."""
    paths = [
        REPO_ROOT / "policy" / "routing-policy.yaml",
        REPO_ROOT / "collector" / "config" / "otelcol-config.generated.yaml",
        REPO_ROOT / "prometheus" / "rules" / "cost-rules.generated.yaml",
    ]
    backup = {p: p.read_text() for p in paths}
    httpd, port = _serve(True)
    try:
        routing = yaml.safe_load(backup[paths[0]])
        code, data = _post(port, {"routing": routing}, path="/api/save")
        assert code == 200, data
        assert data.get("ok") is True
        assert data.get("version")
    finally:
        httpd.shutdown()
        httpd.server_close()
        for path, text in backup.items():
            path.write_text(text)
        pc._EditorHandler.allow_write = False
