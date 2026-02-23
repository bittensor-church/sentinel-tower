import logging
import os
import tracemalloc

# Initialize New Relic before any other imports so the agent can instrument
# Django, Celery, Redis, and psycopg from the start. Each celery multi worker
# subprocess imports this module independently, so all workers get monitored.
if os.environ.get("NEW_RELIC_LICENSE_KEY"):
    import newrelic.agent

    newrelic.agent.initialize()

import psutil
import structlog
from celery import Celery
from celery.signals import celeryd_init, setup_logging, task_postrun, worker_process_init, worker_process_shutdown
from django.conf import settings
from django_structlog.celery.steps import DjangoStructLogInitStep
from more_itertools import chunked
from prometheus_client import Gauge, multiprocess

from .settings import configure_structlog

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

app = Celery("project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.steps["worker"].add(DjangoStructLogInitStep)  # type: ignore
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

num_tasks_in_queue = Gauge(
    "celery_queue_len",
    "How many tasks are there in a queue",
    labelnames=("queue",),
)


@setup_logging.connect
def receiver_setup_logging(loglevel, logfile, format, colorize, **kwargs):  # pragma: no cover
    config = settings.LOGGING
    # worker and master have a logfile, beat does not
    if logfile:
        config["handlers"]["console"]["class"] = "logging.FileHandler"
        config["handlers"]["console"]["filename"] = logfile
    logging.config.dictConfig(config)
    configure_structlog()


def get_tasks_in_queue(queue_name: str) -> list[bytes]:
    with app.pool.acquire(block=True) as conn:
        return conn.default_channel.client.lrange(queue_name, 0, -1)


def get_num_tasks_in_queue(queue_name: str) -> int:
    with app.pool.acquire(block=True) as conn:
        return conn.default_channel.client.llen(queue_name)


def move_tasks(source_queue: str, destination_queue: str, chunk_size: int = 100) -> None:
    with app.pool.acquire(block=True) as conn:
        client = conn.default_channel.client
        tasks = client.lrange(source_queue, 0, -1)

        for chunk in chunked(tasks, chunk_size):
            with client.pipeline() as pipe:
                for task in chunk:
                    client.rpush(destination_queue, task)
                    client.lrem(source_queue, 1, task)
                pipe.execute()


def flush_tasks(queue_name: str) -> None:
    with app.pool.acquire(block=True) as conn:
        conn.default_channel.client.delete(queue_name)


_memory_log = structlog.get_logger("memory_monitor")

# How often to emit a memory report (every N tasks completed by this worker process).
# Lower = more overhead; 50 is a safe default for busy workers.
_MEMORY_REPORT_EVERY_N_TASKS = int(os.environ.get("MEMORY_REPORT_EVERY_N_TASKS", "50"))

# Per-process state (each celery multi worker subprocess has its own copy).
_worker_task_count = 0
_worker_rss_baseline_mb: float | None = None


@worker_process_init.connect
def start_memory_tracing(**kwargs) -> None:
    """Start tracemalloc in every worker subprocess.

    25 stack frames gives enough context to pinpoint the call-site while keeping
    the per-allocation overhead small.
    """
    tracemalloc.start(25)


@task_postrun.connect
def report_memory_after_task(**kwargs) -> None:
    """Periodically emit a structured memory report for leak detection.

    Fires after every task completion. Every _MEMORY_REPORT_EVERY_N_TASKS
    executions it logs:
      - RSS / VMS of this worker process (via psutil)
      - Top 15 allocation sites (file:line, size, count) from tracemalloc
    The snapshot is also forwarded to New Relic as a custom event so it can
    be queried in NRQL alongside APM data.
    """
    global _worker_task_count, _worker_rss_baseline_mb

    _worker_task_count += 1
    if _worker_task_count % _MEMORY_REPORT_EVERY_N_TASKS != 0:
        return

    pid = os.getpid()
    mem = psutil.Process(pid).memory_info()
    rss_mb = mem.rss / 1024 ** 2
    vms_mb = mem.vms / 1024 ** 2

    if _worker_rss_baseline_mb is None:
        _worker_rss_baseline_mb = rss_mb
    rss_growth_mb = rss_mb - _worker_rss_baseline_mb

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")[:15]
    top_allocations = [
        {
            "location": str(stat.traceback[0]),
            "size_kb": round(stat.size / 1024, 1),
            "count": stat.count,
        }
        for stat in top_stats
    ]

    _memory_log.info(
        "worker_memory_report",
        pid=pid,
        rss_mb=round(rss_mb, 1),
        vms_mb=round(vms_mb, 1),
        rss_growth_mb=round(rss_growth_mb, 1),
        task_count=_worker_task_count,
        top_allocations=top_allocations,
    )

    if os.environ.get("NEW_RELIC_LICENSE_KEY"):
        import newrelic.agent

        newrelic.agent.record_custom_event(
            "WorkerMemoryReport",
            {
                "pid": pid,
                "rss_mb": round(rss_mb, 1),
                "vms_mb": round(vms_mb, 1),
                "rss_growth_mb": round(rss_growth_mb, 1),
                "task_count": _worker_task_count,
                # Top allocation as a compact string for NR attribute search
                "top1_location": top_allocations[0]["location"] if top_allocations else "",
                "top1_size_kb": top_allocations[0]["size_kb"] if top_allocations else 0,
            },
        )


@worker_process_shutdown.connect
def child_exit(pid, **kw):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)


@celeryd_init.connect
def on_worker_init(**kwargs) -> None:
    """Load block tasks when worker initializes."""
    from abstract_block_dumper._internal.discovery import ensure_modules_loaded

    ensure_modules_loaded()
