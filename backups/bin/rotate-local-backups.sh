#!/bin/bash
set -euo pipefail

keep_last="${BACKUP_LOCAL_ROTATE_KEEP_LAST:-}"

if [[ -z "$keep_last" ]]; then
    echo "BACKUP_LOCAL_ROTATE_KEEP_LAST is not set, skipping backup rotation"
    exit 0
fi

if [[ ! "$keep_last" =~ ^[1-9][0-9]{0,17}$ ]]; then
    echo "BACKUP_LOCAL_ROTATE_KEEP_LAST must be a positive integer of at most 18 digits" >&2
    exit 2
fi

echo "Rotating backup files - keeping ${keep_last} last ones"

mapfile -d '' -t backup_files < <(
    find /var/backups -type f -name "*.dump.zstd" -print0 | sort -zr
)

files_to_delete=()
if (( ${#backup_files[@]} > 10#$keep_last )); then
    files_to_delete=("${backup_files[@]:10#$keep_last}")
    rm -- "${files_to_delete[@]}"
fi

echo "Removed:"
printf '%s\n' "${files_to_delete[@]}"
