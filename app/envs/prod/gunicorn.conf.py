import environ
from prometheus_client import multiprocess

env = environ.Env()

workers = env.int("GUNICORN_WORKERS", 1)
max_workers = env.int("GUNICORN_MAX_WORKERS", 0)

if max_workers > 0:
    workers = min(max_workers, workers)

# Must default to False: the app's logging uses a multiprocessing.Queue
# (QueueListener / Sentry threading integration) whose background threads and
# locks do not survive fork(). With preload_app=True that state is created in
# the gunicorn master and inherited by forked workers, which then deadlock on
# the first log call and never bind the socket (container -> Up but unhealthy).
preload_app = env.bool("GUNICORN_PRELOAD_APP", False)
bind = "unix:/var/run/gunicorn/gunicorn.sock"
wsgi_app = "project.wsgi:application"
access_logfile = "-"


def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)
