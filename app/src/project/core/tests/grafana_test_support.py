from project.core.grafana_contact import AbstractGrafanaContact, QueryResult


class MockGrafanaContact(AbstractGrafanaContact):
    """Declarative reusable Contact double for services consuming Grafana queries."""

    def __init__(self, results: list[QueryResult]):
        self.results = results
        self.calls: list[str] = []

    def query(self, sql: str) -> QueryResult:
        self.calls.append(sql)
        return self.results[len(self.calls) - 1]
