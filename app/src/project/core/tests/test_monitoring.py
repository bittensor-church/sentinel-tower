from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time
from prometheus_client.parser import text_string_to_metric_families

from tests.factories.metagraph import BlockFactory, SubnetFactory


def sample(client, name, **labels):
    response = client.get("/metrics")
    assert response.status_code == 200
    for family in text_string_to_metric_families(response.content.decode()):
        for item in family.samples:
            if item.name == name and all(item.labels.get(k) == str(v) for k, v in labels.items()):
                return item.value
    pytest.fail(f"Missing metric {name} {labels}")


@pytest.mark.django_db
def test_unconfigured_probes_are_visible(client):
    assert sample(client, "sentinel_grafana_probes_configured") == 0


@pytest.mark.django_db
def test_freshness_keeps_healthy_missing_and_stale_subnets_distinct(client, settings):
    from apps.metagraph.models import MetagraphDump
    from project.core.monitoring import refresh_data_health

    settings.METAGRAPH_NETUIDS = [1, 2, 3]
    now = timezone.now()
    for netuid in (1, 2, 3):
        SubnetFactory(netuid=netuid, tempo=360)
    MetagraphDump.objects.create(netuid=1, block=BlockFactory(number=1000, timestamp=now), finished_at=now)
    old = now - timedelta(days=2)
    MetagraphDump.objects.create(netuid=3, block=BlockFactory(number=10, timestamp=old), finished_at=now)
    refresh_data_health()
    assert sample(client, "sentinel_data_timestamp_seconds", dataset="snapshots", netuid=1) == now.timestamp()
    assert sample(client, "sentinel_data_timestamp_seconds", dataset="snapshots", netuid=2) == 0
    assert sample(client, "sentinel_data_timestamp_seconds", dataset="snapshots", netuid=3) == old.timestamp()
    assert sample(client, "sentinel_data_max_age_seconds", dataset="snapshots", netuid=1) == 9264


@pytest.mark.django_db
def test_backfill_does_not_move_extrinsics_progress_backwards(client):
    from project.core.monitoring import record_ingestion_success, refresh_data_health

    new = datetime(2026, 10, 19, tzinfo=UTC)
    old = new - timedelta(days=1)
    record_ingestion_success("extrinsics", 1000, new)
    record_ingestion_success("extrinsics", 500, old)
    refresh_data_health()
    assert sample(client, "sentinel_data_timestamp_seconds", dataset="extrinsics", netuid="all") == new.timestamp()


@pytest.mark.django_db
def test_scrapes_do_not_renew_snapshot_health_computation(client):
    from apps.metagraph.tasks import update_snapshot_health_metrics

    with freeze_time("2026-10-19 00:00:00"):
        update_snapshot_health_metrics()
    with freeze_time("2026-10-19 04:00:00"):
        assert sample(client, "sentinel_task_last_success_timestamp_seconds", task="snapshot_health") == 1792368000
        assert sample(client, "sentinel_task_last_success_timestamp_seconds", task="snapshot_health") == 1792368000


@pytest.mark.django_db
def test_metrics_drop_subnets_removed_from_inventory(client, settings):
    from project.core.monitoring import refresh_data_health

    settings.METAGRAPH_NETUIDS = [7]
    refresh_data_health()
    assert sample(client, "sentinel_data_timestamp_seconds", dataset="snapshots", netuid=7) == 0
    settings.METAGRAPH_NETUIDS = [8]
    refresh_data_health()
    response = client.get("/metrics").content.decode()
    samples = [
        s
        for f in text_string_to_metric_families(response)
        for s in f.samples
        if s.name == "sentinel_data_timestamp_seconds" and s.labels["dataset"] == "snapshots"
    ]
    assert [(s.labels["netuid"], s.value) for s in samples] == [("8", 0)]


@pytest.mark.django_db
def test_ingested_extrinsics_record_progress_but_unavailable_block_does_not():
    from sentinel.v1.testing import FakeBlockchainProvider

    from apps.extrinsics.block_tasks import BlockExtrinsicsUnavailableError, store_block_extrinsics
    from project.core.models import MonitoringProgress

    # Timestamp inherent is a real extrinsic even when there are no user transactions.
    raw = {
        "index": 0,
        "extrinsic_hash": "0xstamp",
        "call_module": "Timestamp",
        "call_function": "set",
        "call_args": [{"name": "now", "value": 1792368000000}],
    }
    provider = (
        FakeBlockchainProvider()
        .with_block(100, "0xblock")
        .with_extrinsics("0xblock", [raw])
        .with_events(
            "0xblock",
            [
                {
                    "phase": {"ApplyExtrinsic": 0},
                    "extrinsic_idx": 0,
                    "event_index": "0x0000",
                    "module_id": "System",
                    "event_id": "ExtrinsicSuccess",
                    "attributes": {},
                    "topics": [],
                }
            ],
        )
    )
    store_block_extrinsics(100, provider)
    progress = MonitoringProgress.objects.get(name="extrinsics")
    assert progress.source_block == 100
    assert progress.source_timestamp == datetime(2026, 10, 19, tzinfo=UTC)
    bad = FakeBlockchainProvider().with_block(101, "0xmissing").with_extrinsics("0xmissing", [])
    with pytest.raises(BlockExtrinsicsUnavailableError):
        store_block_extrinsics(101, bad)
    progress.refresh_from_db()
    assert progress.source_block == 100


@pytest.mark.django_db
@pytest.mark.parametrize("netuids", [[], [-1], [65536], [1, 2, 3, 4]])
def test_invalid_probe_inventory_is_not_reported_as_configured(client, settings, netuids):
    settings.SENTINEL_GRAFANA_TOKEN = "test-token"  # noqa: S105 -- local test credential
    settings.SENTINEL_GRAFANA_PROBE_NETUIDS = netuids
    assert sample(client, "sentinel_grafana_probes_configured") == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "case,required",
    [
        ("no_eligible", 0),
        ("eligible", 1),
        ("empty", 1),
        ("stale", 1),
        ("unfinished", 1),
        ("pending", 1),
        ("processed", 0),
        ("expired", 0),
        ("lost_validator", 1),
        ("legacy", 1),
    ],
)
def test_apy_exemption_requires_fresh_evidence_and_no_pending_eligible_epoch(client, settings, case, required):
    from apps.metagraph.models import MetagraphDump, ValidatorApyEpoch
    from project.core.monitoring import refresh_data_health
    from tests.factories.metagraph import NeuronFactory, NeuronSnapshotFactory

    settings.METAGRAPH_NETUIDS = [70]
    now = timezone.now()
    subnet = SubnetFactory(netuid=70)
    neuron = NeuronFactory(subnet=subnet)
    stamp = now - timedelta(days=1) if case == "stale" else now
    block = BlockFactory(number=10000, timestamp=stamp)
    MetagraphDump.objects.create(
        netuid=70,
        block=block,
        epoch_position=2,
        finished_at=None if case == "unfinished" else now,
        validator_snapshot_count=None if case == "legacy" else 1,
    )
    if case != "empty":
        NeuronSnapshotFactory(
            neuron=neuron,
            block=block,
            is_validator=case != "lost_validator",
            alpha_stake=10 if case == "eligible" else 0,
        )
    if case in ("pending", "processed", "expired"):
        older = BlockFactory(
            number=9000, timestamp=now - (timedelta(days=91) if case == "expired" else timedelta(hours=5))
        )
        MetagraphDump.objects.create(netuid=70, block=older, epoch_position=2, finished_at=now)
        NeuronSnapshotFactory(neuron=neuron, block=older, is_validator=True, alpha_stake=10)
        if case in ("processed", "expired"):
            ValidatorApyEpoch.objects.create(
                subnet_id=70,
                neuron=neuron,
                hotkey=neuron.hotkey,
                epoch_block=9000,
                epoch_ts=older.timestamp,
                alpha_stake=10,
                alpha_dividends=1,
                total_stake=10,
                tempo=360,
                apy_pct=1,
            )
    if case == "expired":
        from django.db import connection

        from apps.metagraph.services.apy_epoch_ingest import apply_retention

        with connection.cursor() as cursor:
            assert apply_retention(cursor) == 1
    refresh_data_health()
    assert sample(client, "sentinel_data_freshness_required", dataset="apy", netuid=70) == required
    # A legitimate no-output epoch must not fabricate an APY source timestamp.
    if case == "no_eligible":
        assert sample(client, "sentinel_data_timestamp_seconds", dataset="apy", netuid=70) == 0
    assert sample(client, "sentinel_data_freshness_required", dataset="snapshots", netuid=70) == 1


@pytest.mark.django_db
def test_old_worker_insert_keeps_freshness_required_during_rollout(client):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO core_monitoringresult
                (kind, name, netuid, checked_at, max_age_seconds, success, duration_seconds, error_code)
            VALUES ('data', 'apy', '70', NOW(), 300, false, 0, '')
        """)
    assert sample(client, "sentinel_data_freshness_required", dataset="apy", netuid=70) == 1


@pytest.mark.django_db
def test_old_worker_insert_keeps_snapshot_gaps_actionable_during_rollout(client):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO metagraph_snapshot_health_metric (netuid, "window", missing_blocks, updated_at)
            VALUES (70, '7d', 3, NOW())
        """)
    assert sample(client, "metagraph_actionable_missing_snapshot_blocks", netuid=70, window="7d") == 3
