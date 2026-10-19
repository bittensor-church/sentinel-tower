"""Exercise the real HTTP Contact against a disposable local HTTP endpoint."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


@pytest.fixture
def grafana_server():
    state = {
        "status": 200,
        "body": {
            "results": {
                "A": {
                    "frames": [{"schema": {"fields": [{"name": "value", "type": "number"}]}, "data": {"values": [[1]]}}]
                }
            }
        },
        "requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(json.dumps(state["body"]).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/grafana", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_contact_submits_query_and_parses_nonempty_frames(grafana_server):
    from project.core.grafana_contact import GrafanaContact

    url, state = grafana_server
    result = GrafanaContact(url, "test-token").query("SELECT 1 AS value")
    assert result.rows == 1
    assert result.error == ""
    path, auth, body = state["requests"][0]
    assert path == "/grafana/api/ds/query"
    assert auth == "Bearer test-token"
    assert body["queries"][0]["rawSql"] == "SELECT 1 AS value"
    assert body["queries"][0]["datasource"]["uid"] == "postgresql"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (200, {"results": {"A": {"error": "SQL failed", "status": 400, "frames": []}}}, "query_error"),
        (200, {"results": {"A": {"frames": []}}}, ""),
        (200, {}, "invalid_response"),
        (200, {"results": {"A": {"frames": [{"data": {"values": [[None]]}}]}}}, "invalid_response"),
        (403, {}, "http_error"),
        (504, {}, "timeout"),
    ],
)
def test_real_contact_handles_query_errors_empty_and_malformed_responses(grafana_server, status, body, error):
    from project.core.grafana_contact import GrafanaContact

    url, state = grafana_server
    state.update(status=status, body=body)
    result = GrafanaContact(url, "test-token").query("SELECT 1 AS value")
    assert result.rows == 0
    assert result.error == error


@pytest.mark.django_db
def test_probe_task_keeps_success_failure_and_empty_results_separate(settings, monkeypatch):
    from project.core import grafana_contact
    from project.core.grafana_contact import QueryResult
    from project.core.grafana_probes import run_grafana_probes
    from project.core.models import MonitoringResult
    from project.core.tests.grafana_test_support import MockGrafanaContact

    settings.SENTINEL_GRAFANA_TOKEN = "test-token"  # noqa: S105 -- local test credential
    settings.SENTINEL_GRAFANA_PROBE_NETUIDS = [1]
    contact = MockGrafanaContact(results=[QueryResult(1), QueryResult(0, "timeout"), QueryResult(0)])
    monkeypatch.setattr(grafana_contact, "contact", lambda: contact)
    run_grafana_probes()
    assert list(
        MonitoringResult.objects.filter(kind="query").order_by("name").values_list("name", "success", "error_code")
    ) == [("apy", False, "no_data"), ("connection", True, ""), ("snapshots", False, "timeout")]
