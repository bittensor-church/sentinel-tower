#!/bin/sh

# We assume that WORKDIR is defined in Dockerfile

./prometheus-cleanup.sh
PROMETHEUS_EXPORT_MIGRATIONS=0 ./manage.py wait_for_database --timeout 10
# this seems to be the only place to put this for AWS deployments to pick it up.
# AUTO_MIGRATE=0 skips it so long-running migrations (e.g. CREATE INDEX
# CONCURRENTLY on multi-100M-row tables) can be run manually while the app
# serves: docker compose run --rm app python manage.py migrate
if [ "${AUTO_MIGRATE:-1}" = "1" ]; then
    PROMETHEUS_EXPORT_MIGRATIONS=0 ./manage.py migrate
fi

gunicorn -c gunicorn.conf.py
