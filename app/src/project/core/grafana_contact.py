"""Grafana query transport. Probe policy and persistence live in grafana_probes."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from django.conf import settings


@dataclass(frozen=True)
class QueryResult:
    rows: int = 0
    error: str = ""


class AbstractGrafanaContact(ABC):
    @abstractmethod
    def query(self, sql: str) -> QueryResult:
        """Execute one bounded read-only diagnostic query."""


class GrafanaContact(AbstractGrafanaContact):
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def query(self, sql: str) -> QueryResult:
        payload = {
            "from": "now-1h",
            "to": "now",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"uid": "postgresql", "type": "postgres"},
                    "rawSql": sql,
                    "format": "table",
                    "maxDataPoints": 1,
                }
            ],
        }
        try:
            with requests.post(
                f"{self.url}/api/ds/query",
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=(3, 20),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in (408, 504):
                    return QueryResult(error="timeout")
                if response.status_code != 200:
                    return QueryResult(error="http_error")
                # The queries return at most one row. Reject unexpectedly large replies.
                body = bytearray()
                for chunk in response.iter_content(8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        return QueryResult(error="invalid_response")
                result = json.loads(body)["results"]["A"]
                if result.get("error") or result.get("status", 200) >= 400:
                    return QueryResult(error="query_error")
                rows = 0
                for frame in result["frames"]:
                    fields = frame["schema"]["fields"]
                    columns = frame["data"]["values"]
                    if not fields or len(fields) != len(columns) or not all(isinstance(c, list) for c in columns):
                        return QueryResult(error="invalid_response")
                    if len({len(c) for c in columns}) != 1:
                        return QueryResult(error="invalid_response")
                    rows += sum(any(value is not None for value in values) for values in zip(*columns))
                return QueryResult(rows=rows)
        except requests.Timeout:
            return QueryResult(error="timeout")
        except requests.RequestException:
            return QueryResult(error="connection_error")
        except ValueError, KeyError, TypeError, AttributeError:
            return QueryResult(error="invalid_response")


def contact() -> AbstractGrafanaContact:
    return GrafanaContact(settings.SENTINEL_GRAFANA_URL, settings.SENTINEL_GRAFANA_TOKEN)


def probes_configured() -> bool:
    netuids = settings.SENTINEL_GRAFANA_PROBE_NETUIDS
    return bool(settings.SENTINEL_GRAFANA_TOKEN and 1 <= len(netuids) <= 3 and all(0 <= n <= 65535 for n in netuids))
