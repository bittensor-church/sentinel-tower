"""Static checks of the SQL in the provisioned Grafana dashboards (grafana/dashboards).

Dashboards are deployed from JSON, so a query only fails once someone opens the panel.
These checks catch the two ways that has happened: a query using a variable the
dashboard does not define (Grafana leaves it in the SQL verbatim, and the public
Grafana's query filter then rejects the whole query), and a query that no longer
matches the schema.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from django.db import connection

DASHBOARDS_DIR = Path(__file__).resolve().parents[4] / "grafana" / "dashboards"

_SQL_DATASOURCE = "grafana-postgresql-datasource"
# `${name}`, `${name:format}` and `$name` references in SQL.
_VARIABLE = re.compile(r"\$\{(\w+)(?::(\w+))?\}|\$(\w+)")
# Grafana's global variables and the SQL datasource's macros.
_BUILTINS = {"__from", "__to", "__interval", "__interval_ms", "__range", "__timeFrom", "__timeTo", "__timeFilter"}

# Values substituted for each variable when planning a query; any value of the right
# type will do, since only the plan is checked.
_SAMPLE_VALUES = {
    "subnet": "1",
    "netuid": "1",
    "mech_id": "0",
    "miner": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    "validator": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    "address": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    "call_module": "SubtensorModule",
    "call_function": "set_weights",
    "status": "success",
}
_FROM_MS, _TO_MS = 1_790_000_000_000, 1_790_604_800_000
_FROM_DATE, _TO_DATE = "2026-09-21T12:53:20.000Z", "2026-09-28T12:53:20.000Z"


@dataclass(frozen=True)
class DashboardQuery:
    dashboard: str
    where: str
    sql: str
    variables: frozenset[str]

    def __str__(self) -> str:
        return f"{self.dashboard}: {self.where}"


def _template_query(variable: dict) -> str:
    if variable.get("type") != "query" or (variable.get("datasource") or {}).get("type") != _SQL_DATASOURCE:
        return ""
    query = variable.get("query")
    if isinstance(query, dict):
        query = query.get("query") or query.get("rawSql")
    return query if isinstance(query, str) else ""


def _panels(panels: list[dict]) -> Iterator[dict]:
    for panel in panels:
        yield panel
        yield from _panels(panel.get("panels") or [])


def _dashboard_queries() -> Iterator[DashboardQuery]:
    for path in sorted(DASHBOARDS_DIR.glob("**/*.json")):
        dashboard = json.loads(path.read_text())
        spec = dashboard.get("spec", dashboard)
        if "panels" not in spec:
            continue  # folder metadata
        name = str(path.relative_to(DASHBOARDS_DIR))
        templating = spec.get("templating", {}).get("list", [])
        variables = frozenset(variable["name"] for variable in templating)
        for variable in templating:
            if sql := _template_query(variable):
                yield DashboardQuery(name, f"variable {variable['name']}", sql, variables)
        for panel in _panels(spec["panels"]):
            for target in panel.get("targets") or []:
                if sql := target.get("rawSql"):
                    where = f"panel {panel.get('id')} {panel.get('title')!r} query {target.get('refId')}"
                    yield DashboardQuery(name, where, sql, variables)


def _sample_value(name: str, value_format: str | None) -> str:
    if name in ("__from", "__to"):
        if value_format == "date":
            return _FROM_DATE if name == "__from" else _TO_DATE
        return str(_FROM_MS if name == "__from" else _TO_MS)
    value = _SAMPLE_VALUES[name]
    return f"'{value}'" if value_format == "singlequote" else value


def _interpolate(sql: str) -> str:
    sql = sql.replace("$__timeFrom()", f"'{_FROM_DATE}'::timestamptz").replace(
        "$__timeTo()", f"'{_TO_DATE}'::timestamptz"
    )
    return _VARIABLE.sub(lambda match: _sample_value(match[1] or match[3], match[2]), sql)


QUERIES = list(_dashboard_queries())


def test_dashboards_were_found():
    dashboards = {query.dashboard for query in QUERIES}
    assert {"metagraph-subnet.json", "metagraph-validator.json", "metagraph-miner.json"} <= dashboards


@pytest.mark.parametrize("query", QUERIES, ids=str)
def test_queries_use_only_defined_variables(query: DashboardQuery):
    used = {match[1] or match[3] for match in _VARIABLE.finditer(query.sql)}
    assert used - query.variables - _BUILTINS == set()


@pytest.mark.django_db
@pytest.mark.parametrize("query", QUERIES, ids=str)
def test_queries_plan_against_the_current_schema(query: DashboardQuery):
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {_interpolate(query.sql).strip().rstrip(';')}")
