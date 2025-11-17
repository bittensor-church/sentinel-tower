import os

from project.settings import *  # noqa: E402,F403

os.environ["DEBUG_TOOLBAR"] = "False"

PROMETHEUS_EXPORT_MIGRATIONS = False
