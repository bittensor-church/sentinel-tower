import fcntl
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from prometheus_client import multiprocess
from prometheus_client.mmap_dict import MmapedDict, mmap_key

from project.core.metrics import RecursiveMultiProcessCollector


def _write_counter(path: Path, value: float) -> None:
    metric_file = MmapedDict(str(path))
    metric_file.write_value(
        mmap_key("template_step_requests", "template_step_requests_total", [], [], "Template-step test counter"),
        value,
        0.0,
    )
    metric_file.close()


def _collect_counter(collector: RecursiveMultiProcessCollector) -> float:
    metrics = {metric.name: metric for metric in collector.collect()}
    samples = {sample.name: sample.value for sample in metrics["template_step_requests"].samples}
    return samples["template_step_requests_total"]


def test_recursive_collector_aggregates_service_directories_without_compaction(tmp_path: Path) -> None:
    celery_dir = tmp_path / "celery-worker"
    scheduler_dir = tmp_path / "block-scheduler"
    celery_dir.mkdir()
    scheduler_dir.mkdir()

    metric_files = (
        tmp_path / "counter_101.db",
        celery_dir / "counter_202.db",
        scheduler_dir / "counter_303.db",
    )
    for path, value in zip(metric_files, (2.0, 3.0, 5.0), strict=True):
        _write_counter(path, value)

    collector = RecursiveMultiProcessCollector(None, path=str(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: _collect_counter(collector), range(32)))

    assert values == [10.0] * 32
    assert all(path.exists() for path in metric_files)
    assert not list(tmp_path.rglob("merged_metrics.pkl"))


def test_recursive_collector_ignores_file_removed_during_scrape(tmp_path: Path, monkeypatch) -> None:
    stable_file = tmp_path / "counter_101.db"
    disappearing_dir = tmp_path / "celery-worker"
    disappearing_dir.mkdir()
    disappearing_file = disappearing_dir / "counter_202.db"
    _write_counter(stable_file, 2.0)
    _write_counter(disappearing_file, 3.0)

    original_read_metrics = multiprocess.MultiProcessCollector._read_metrics

    def remove_before_read(files):
        filenames = list(files)
        if str(disappearing_file) in filenames and disappearing_file.exists():
            disappearing_file.unlink()
            raise FileNotFoundError(disappearing_file)
        return original_read_metrics(filenames)

    monkeypatch.setattr(multiprocess.MultiProcessCollector, "_read_metrics", staticmethod(remove_before_read))

    collector = RecursiveMultiProcessCollector(None, path=str(tmp_path))
    assert _collect_counter(collector) == 2.0


def test_recursive_collector_preserves_flock_locked_live_file(tmp_path: Path) -> None:
    writer_dir = tmp_path / "block-scheduler"
    writer_dir.mkdir()
    writer_code = "\n".join(
        (
            "import time",
            "from prometheus_client import Counter",
            "counter = Counter('template_step_requests', 'Template-step test counter')",
            "counter.inc()",
            "print('ready', flush=True)",
            "for _ in range(999):",
            "    counter.inc()",
            "    time.sleep(0.001)",
            "time.sleep(30)",
        )
    )
    writer_env = {
        **os.environ,
        "PROMETHEUS_MULTIPROC_DIR": str(writer_dir),
        "PROMETHEUS_USE_FLOCK": "1",
    }
    writer = subprocess.Popen(
        [sys.executable, "-c", writer_code],
        env=writer_env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline() == "ready\n"
        metric_file = next(writer_dir.glob("counter_*.db"))

        with metric_file.open("r+b") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("the live Prometheus writer did not retain its flock lock")

        collector = RecursiveMultiProcessCollector(None, path=str(tmp_path))
        with ThreadPoolExecutor(max_workers=16) as executor:
            values = list(executor.map(lambda _: _collect_counter(collector), range(256)))

        assert all(1.0 <= value <= 1000.0 for value in values)
        assert metric_file.exists()
        assert not list(tmp_path.rglob("merged_metrics.pkl"))
    finally:
        writer.terminate()
        writer.wait(timeout=5)
