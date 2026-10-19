"""Opt-in tests against the disposable nginx/Grafana/Postgres/Alloy stack.

Start scripts/tests/grafana-query-telemetry/compose.yml manually, then run:
GRAFANA_TELEMETRY_TEST=1 python3 -m unittest discover -s scripts/tests -p test_grafana_query_telemetry.py -v
"""

import json
import os
import time
import unittest
import urllib.error
import urllib.request


@unittest.skipUnless(os.environ.get("GRAFANA_TELEMETRY_TEST") == "1", "requires disposable telemetry stack")
class GrafanaQueryTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for url in ["http://127.0.0.1:18380/grafana/api/health", "http://127.0.0.1:18345/-/ready"]:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - fixed localhost test URLs
                        if response.status == 200:
                            break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                time.sleep(0.2)

    def query(self, sql, panel, *, selection="var-netuid=8", headers=True, extra_queries=()):
        body = {
            "from": "now-1h",
            "to": "now",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"uid": "postgresql", "type": "grafana-postgresql-datasource"},
                    "rawSql": sql,
                    "format": "table",
                },
                *extra_queries,
            ],
        }
        metadata = {"Content-Type": "application/json"}
        if headers:
            metadata.update(
                {
                    "X-Dashboard-Uid": "weight-setting",
                    "X-Panel-Id": panel,
                    "X-Dashboard-Title": "Weight setting",
                    "X-Panel-Title": 'Weights "chart"',
                    "X-Datasource-Uid": "postgresql",
                    "Referer": "http://localhost:18380/grafana/d/weight-setting/test?" + selection,
                }
            )
        request = urllib.request.Request(
            "http://127.0.0.1:18380/grafana/api/ds/query", json.dumps(body).encode(), metadata
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:  # noqa: S310 - fixed localhost endpoint
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def metric(self, name, labels, *, timeout=12, minimum=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with urllib.request.urlopen("http://127.0.0.1:18345/metrics", timeout=3) as response:
                lines = response.read().decode().splitlines()
            matches = [
                line
                for line in lines
                if line.startswith(name + "{") and all(f'{key}="{value}"' in line for key, value in labels.items())
            ]
            if matches:
                value = float(matches[0].rsplit(" ", 1)[1])
                if minimum is None or value >= minimum:
                    return value
            time.sleep(0.2)
        self.fail(f"Missing metric {name} {labels}")

    def test_failed_sql_and_mixed_response_keep_exact_chart(self):
        before = time.time()
        status, body = self.query(
            "SELECT * FROM missing_sentinel_telemetry_test_table",
            "11",
            extra_queries=[
                {
                    "refId": "B",
                    "datasource": {"uid": "postgresql", "type": "grafana-postgresql-datasource"},
                    "rawSql": "SELECT 1",
                    "format": "table",
                }
            ],
        )
        self.assertEqual(status, 400, body)
        results = json.loads(body)["results"]
        self.assertIn("error", results["A"])
        self.assertNotIn("error", results["B"])
        event_time = self.metric(
            "sentinel_grafana_query_last_failure_timestamp_seconds",
            {"dashboard_uid": "weight-setting", "panel_id": "11", "netuid": "8", "status_code": "400"},
            minimum=before,
        )
        self.assertGreaterEqual(event_time, before)

    def test_timeout_identifies_scene_panel_and_subnet_variable(self):
        status, body = self.query("SELECT pg_sleep(9)", "panel-12", selection="var-subnet=1")
        self.assertEqual(status, 504, body)
        self.metric(
            "sentinel_grafana_query_last_failure_timestamp_seconds",
            {"panel_id": "12", "netuid": "1", "subnet_variable": "subnet", "status_code": "504"},
        )

    def test_multiple_subnets_are_not_misreported_as_one(self):
        status, body = self.query("SELECT no_such_column", "13", selection="var-netuid=1&var-netuid=8")
        self.assertEqual(status, 400, body)
        self.metric("sentinel_grafana_query_last_failure_timestamp_seconds", {"panel_id": "13", "netuid": "multiple"})

    def test_missing_context_is_explicit(self):
        status, body = self.query("SELECT no_such_column", "14", headers=False)
        self.assertEqual(status, 400, body)
        self.metric(
            "sentinel_grafana_query_last_failure_timestamp_seconds",
            {"dashboard_uid": "unknown", "panel_id": "unknown", "netuid": "unknown"},
        )

    def test_successful_slow_query_records_duration(self):
        before = time.time()
        status, body = self.query("SELECT pg_sleep(5.2)", "15")
        self.assertEqual(status, 200, body)
        labels = {"panel_id": "15", "status_code": "200"}
        self.metric("sentinel_grafana_query_last_slow_timestamp_seconds", labels, minimum=before)
        self.assertGreaterEqual(self.metric("sentinel_grafana_query_duration_seconds_sum", labels), 5)
        self.assertEqual(self.metric("sentinel_grafana_query_duration_seconds_bucket", {**labels, "le": "5"}), 0)

    def test_scrape_heartbeat_proves_ingestion_without_chart_traffic(self):
        before = time.time()
        with urllib.request.urlopen("http://127.0.0.1:18380/grafana-query-metrics/", timeout=3) as response:
            self.assertEqual(response.status, 200)
        self.metric("sentinel_grafana_query_log_last_seen_timestamp_seconds", {}, minimum=before)

    def test_structured_logs_escape_titles_and_omit_sql_and_full_url(self):
        self.query("SELECT no_such_private_column", "16", selection="var-netuid=8&private_value=do_not_log")
        with urllib.request.urlopen("http://127.0.0.1:18380/telemetry-test-log", timeout=3) as response:
            events = [json.loads(line) for line in response.read().decode().splitlines()]
        event = next(e for e in reversed(events) if e.get("panel_id") == "16")
        self.assertEqual(event["panel_title"], 'Weights "chart"')
        self.assertEqual(event["netuid"], "8")
        self.assertEqual(len(event["request_id"]), 32)
        self.assertNotIn("no_such_private_column", json.dumps(event))
        self.assertNotIn("do_not_log", json.dumps(event))

    def test_all_comma_and_absent_selections_are_explicit(self):
        for panel, selection, expected in [
            ("17", "var-netuid=%24__all", "all"),
            ("18", "var-netuid=1%2C8", "multiple"),
            ("19", "from=now-1h", "unknown"),
        ]:
            with self.subTest(selection=selection):
                status, body = self.query("SELECT no_such_column", panel, selection=selection)
                self.assertEqual(status, 400, body)
                self.metric(
                    "sentinel_grafana_query_last_failure_timestamp_seconds", {"panel_id": panel, "netuid": expected}
                )
