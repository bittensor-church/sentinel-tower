#!/usr/bin/env python3
"""Run every panel query of a provisioned Grafana dashboard through Grafana's query API.

Usage:
    python3 scripts/check_dashboard_queries.py grafana/provisioning/dashboards/<file>.json

Environment:
    GRAFANA_URL       default http://localhost:3001
    GRAFANA_USER      default admin
    GRAFANA_PASSWORD  default admin

Exits 1 when the file is invalid (duplicate panel ids, wrong datasource, empty SQL)
or when any query returns an error from the datasource.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

EXPECTED_DS_UID = "postgresql"


def iter_panels(panels):
    for panel in panels:
        yield panel
        yield from iter_panels(panel.get("panels", []))


def validate_structure(dashboard):
    errors = []
    seen = set()
    for panel in iter_panels(dashboard["panels"]):
        pid = panel.get("id")
        if pid in seen:
            errors.append(f"duplicate panel id {pid}")
        seen.add(pid)
        for target in panel.get("targets", []):
            uid = target.get("datasource", {}).get("uid")
            if uid != EXPECTED_DS_UID:
                errors.append(f"panel {pid} ({panel.get('title')}): datasource uid {uid!r}")
            if not target.get("rawSql"):
                errors.append(f"panel {pid} ({panel.get('title')}): empty rawSql")
    return errors


def run_query(base_url, auth_header, sql):
    body = json.dumps(
        {
            "from": "now-1h",
            "to": "now",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": "postgres", "uid": EXPECTED_DS_UID},
                    "rawSql": sql,
                    "format": "table",
                }
            ],
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 - local Grafana over http by design
        f"{base_url}/api/ds/query",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": auth_header},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - local Grafana over http by design
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        payload = json.load(exc)
    return payload.get("results", {}).get("A", {}).get("error")


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open(argv[1]) as fh:
        dashboard = json.load(fh)
    errors = validate_structure(dashboard)
    base_url = os.environ.get("GRAFANA_URL", "http://localhost:3001").rstrip("/")
    credentials = f"{os.environ.get('GRAFANA_USER', 'admin')}:{os.environ.get('GRAFANA_PASSWORD', 'admin')}"
    auth_header = "Basic " + base64.b64encode(credentials.encode()).decode()
    checked = 0
    for panel in iter_panels(dashboard["panels"]):
        for target in panel.get("targets", []):
            checked += 1
            error = run_query(base_url, auth_header, target["rawSql"])
            if error:
                errors.append(f"panel {panel.get('id')} ({panel.get('title')}): {error}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"{checked} targets checked, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
