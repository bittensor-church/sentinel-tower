import os
from pathlib import Path

# Base settings read environment variables while they are imported, so test-specific
# defaults must be configured first. This keeps tests independent of a developer's
# potentially stale .env file.
TEST_ENV_DEFAULTS = {
    "CELERY_BROKER_POOL_LIMIT": "50",
    "CELERY_WORKER_PREFETCH_MULTIPLIER": "1",
    "HTTPS_REDIRECT": "False",
    "MEDIA_ROOT": str(Path(__file__).resolve().parents[3] / "media"),
    "PROMETHEUS_EXPORT_MIGRATIONS": "False",
}
for name, value in TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(name, value)

os.environ["DEBUG_TOOLBAR"] = "False"

from project.settings import *  # noqa: E402,F403

PROMETHEUS_EXPORT_MIGRATIONS = False
