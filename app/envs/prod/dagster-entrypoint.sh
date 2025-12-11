#!/bin/sh
set -e

# Wait for database and run migrations
PROMETHEUS_EXPORT_MIGRATIONS=0 ./manage.py wait_for_database --timeout 10
PROMETHEUS_EXPORT_MIGRATIONS=0 ./manage.py migrate --no-input

# Set Dagster home for instance config
export DAGSTER_HOME=/root/src

# Start Dagster webserver with path prefix for nginx proxy
exec dagster-webserver -h 0.0.0.0 -p 3000 --path-prefix /dagster -m project.dagster.definitions
