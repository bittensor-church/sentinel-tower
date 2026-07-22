#!/bin/sh
set -e

if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
fi

# Fix ownership of bind-mounted directories that may have been created by root
for dir in "$MEDIA_ROOT" /var/static /prometheus-multiproc-dir "${PROMETHEUS_MULTIPROC_DIR:-}" /var/run/gunicorn; do
    if [ -d "$dir" ] && [ "$(stat -c %u "$dir")" != "1000" ]; then
        chown -R appuser:appuser "$dir"
    fi
done

exec gosu appuser "$@"
