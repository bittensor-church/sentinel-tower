#!/bin/sh
# Copyright 2024, Reef Technologies (reef.pl), All rights reserved.
set -eux

if [ ! -f ".env" ]; then
    echo "\e[31mPlease setup the environment first!\e[0m";
    exit 1;
fi

docker compose build

docker compose up -d db  # in case it hasn't been launched before
# backup db before any database changes
# docker compose run --rm backups ./backup-db.sh

# collect static files to external storage while old app is still running
# docker compose run --rm app sh -c "python manage.py collectstatic --no-input"

# Stop selected app/celery services before the stack is recreated.
SERVICES=$(docker compose ps --services 2>/dev/null | grep -E '^(app|celery-worker|celery-beat)$' || true)
if [ -n "$SERVICES" ]; then
    # shellcheck disable=2086
    docker compose stop $SERVICES
fi

# start everything; migrations are NOT run automatically (long CONCURRENTLY
# index builds would keep the whole stack down) — run them manually while the
# app serves traffic:
docker compose up -d

echo "Deploy done. If this release contains migrations, apply them now with:"
echo "  docker compose run --rm app sh -c 'python manage.py wait_for_database --timeout 10; python manage.py migrate'"

# Clean up older dangling images without killing recent build cache
docker image prune -f --filter "until=168h" || true
