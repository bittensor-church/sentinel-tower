#!/bin/sh
set -e

if [ -n "$PROMETHEUS_MULTIPROC_DIR" ]; then
    if [ -d "$PROMETHEUS_MULTIPROC_DIR" ]; then
        # Delete all prometheus metric files in PROMETHEUS_MULTIPROC_DIR, but not in its subdirectories to not
        # interfere with other processes. At startup, we can safely remove all .db files since the process is
        # starting fresh. This covers all file types: gauge_live*, gauge_all*, counter_*, histogram_*, summary_*.
        find "$PROMETHEUS_MULTIPROC_DIR" -maxdepth 1 -type f -name '*.db' -delete
    else
        # Ensure the directory exists
        mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    fi
fi
