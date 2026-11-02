import json
import os
import subprocess
import sys
import time

import pytest

from project.core.services.collector_watchdog import CollectorWatchdog


@pytest.mark.parametrize("record", [None, "broken-json", "[]", "{}", "dead", "stale", "future"])
def test_health_check_rejects_missing_invalid_dead_or_stale_progress(tmp_path, record):
    path = tmp_path / "health.json"
    if record in ("dead", "stale", "future"):
        data = {"pid": os.getpid(), "progress_at": time.monotonic(), "block": 100}
        if record == "dead":
            data["pid"] = 2**30  # above Linux's maximum PID
        elif record == "stale":
            data["progress_at"] -= 601
        else:
            data["progress_at"] += 601
        record = json.dumps(data)
    if record is not None:
        path.write_text(record)
    assert CollectorWatchdog(path).healthy() is False


def test_advancing_collector_stays_healthy_and_cleans_up_on_shutdown(tmp_path):
    path = tmp_path / "health.json"
    script = """
import json, sys, time
from pathlib import Path
from project.core.services.collector_watchdog import CollectorWatchdog
path = Path(sys.argv[1])
with CollectorWatchdog(path, operation_timeout=1, progress_timeout=0.4) as watchdog:
    assert watchdog.healthy()  # startup grace
    for block in range(10, 18):
        with watchdog.operation('work'):
            time.sleep(0.1)
        watchdog.advance(block)
        assert watchdog.healthy()
    previous = path.read_text()
    watchdog.advance(16)
    assert path.read_text() == previous  # old/repeated blocks cannot refresh health
    print(json.loads(previous)['block'])
assert not path.exists()
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=5)
    assert (result.returncode, result.stdout.strip()) == (0, "17"), result.stderr
    assert not path.exists()


def test_docker_health_command_reads_progress_without_django(tmp_path):
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"pid": os.getpid(), "progress_at": time.monotonic(), "block": 100}))
    env = {**os.environ, "METAGRAPH_HEALTH_FILE": str(path), "DJANGO_SETTINGS_MODULE": "does_not_exist"}
    command = [sys.executable, "-m", "project.core.services.collector_watchdog"]
    assert subprocess.run(command, env=env, timeout=5).returncode == 0
    path.unlink()
    assert subprocess.run(command, env=env, timeout=5).returncode == 1


def test_full_logging_pipe_cannot_prevent_watchdog_exit(tmp_path):
    script = """
import os, sys, time
from pathlib import Path
from project.core.services.collector_watchdog import CollectorWatchdog
os.set_blocking(2, False)
try:
    while True:
        os.write(2, b'x' * 4096)
except BlockingIOError:
    pass
os.set_blocking(2, True)
with CollectorWatchdog(Path(sys.argv[1]), operation_timeout=0.1, progress_timeout=2) as watchdog:
    with watchdog.operation('blocked_provider'):
        time.sleep(60)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path / "health.json")], stderr=subprocess.PIPE)
    try:
        assert process.wait(timeout=3) == 70
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stderr.close()


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_timeouts_cannot_disable_recovery(tmp_path, value):
    with pytest.raises(ValueError, match="finite and positive"):
        CollectorWatchdog(tmp_path / "health.json", operation_timeout=value)
    with pytest.raises(ValueError, match="finite and positive"):
        CollectorWatchdog(tmp_path / "health.json", progress_timeout=value)
