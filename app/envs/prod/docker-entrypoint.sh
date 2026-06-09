#!/bin/sh
set -e

# Fix ownership of bind-mounted directories that may have been created by root
for dir in /root/src/media /prometheus-multiproc-dir /var/run/gunicorn; do
    if [ -d "$dir" ] && [ "$(stat -c %u "$dir")" != "1000" ]; then
        chown -R appuser:appuser "$dir"
    fi
done

exec gosu appuser "$@"
