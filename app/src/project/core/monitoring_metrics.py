"""Custom collector reads summaries directly, avoiding stale multiprocess gauge files."""

from prometheus_client.core import GaugeMetricFamily

from apps.metagraph.models import SnapshotHealthMetric
from project.core.grafana_contact import probes_configured
from project.core.models import MonitoringProgress, MonitoringResult


class MonitoringCollector:
    def describe(self):
        # Registration happens before migrations and must not touch the database.
        return []

    def collect(self):
        gaps = GaugeMetricFamily(
            "metagraph_missing_snapshot_blocks",
            "Dumpable blocks with no NeuronSnapshot entries in the look-back window",
            labels=["netuid", "window"],
        )
        for netuid, window, missing in SnapshotHealthMetric.objects.values_list("netuid", "window", "missing_blocks"):
            gaps.add_metric([str(netuid), window], missing)
        yield gaps
        configured = GaugeMetricFamily(
            "sentinel_grafana_probes_configured", "Grafana probe credentials and subnet configured"
        )
        configured.add_metric([], int(probes_configured()))
        yield configured
        progress = dict(MonitoringProgress.objects.values_list("name", "succeeded_at"))
        tasks = GaugeMetricFamily(
            "sentinel_task_last_success_timestamp_seconds", "Last committed successful check or task", labels=["task"]
        )
        for name in ("snapshot_health", "validator_apy", "data_health", "grafana_probes"):
            tasks.add_metric([name], progress[name].timestamp() if name in progress else 0)
        yield tasks
        rows = list(MonitoringResult.objects.all())
        for field, suffix, help_text in (
            ("source_timestamp", "timestamp_seconds", "Latest stored source data time"),
            ("max_age_seconds", "max_age_seconds", "Allowed age for this dataset"),
            ("checked_at", "checked_timestamp_seconds", "When this dataset was checked"),
        ):
            metric = GaugeMetricFamily(f"sentinel_data_{suffix}", help_text, labels=["dataset", "netuid"])
            for row in rows:
                if row.kind == "data":
                    value = getattr(row, field)
                    if field != "max_age_seconds":
                        value = value.timestamp() if value else 0
                    metric.add_metric([row.name, row.netuid], value)
            yield metric
        for field, suffix in (
            ("success", "success"),
            ("duration_seconds", "duration_seconds"),
            ("checked_at", "checked_timestamp_seconds"),
        ):
            metric = GaugeMetricFamily(
                f"sentinel_grafana_probe_{suffix}", f"Grafana probe {suffix}", labels=["check", "netuid", "reason"]
            )
            for row in rows:
                if row.kind == "query":
                    value = row.checked_at.timestamp() if field == "checked_at" else float(getattr(row, field))
                    metric.add_metric([row.name, row.netuid, row.error_code], value)
            yield metric
        inventory = GaugeMetricFamily(
            "sentinel_monitored_subnets", "Subnets in the last successful data health inventory"
        )
        inventory.add_metric([], sum(row.kind == "data" and row.name == "snapshots" for row in rows))
        yield inventory
