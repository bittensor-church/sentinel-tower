#!/usr/bin/env bash
set -euo pipefail

python3 scripts/grafana_preview.py report "$PREVIEW_PULLS" "$PREVIEW_STATE" > "$PREVIEW_REPORT"
cat "$PREVIEW_REPORT" >> "$GITHUB_STEP_SUMMARY"

# Update previous participants too: queued removal events may be coalesced.
targets=$(
  {
    if [ -f "$PREVIEW_STATE" ]; then
      jq -r '.pulls[]?.number, .previous_pulls[]?' "$PREVIEW_STATE"
    fi
    if [ -n "$TRIGGER_PR" ]; then
      printf '%s\n' "$TRIGGER_PR"
    fi
  } | sort -nu
)
failed=0
while read -r pr; do
  [ -n "$pr" ] || continue
  # Consume all pages before choosing an ID. head would close the pipe while gh
  # can still be producing results, failing the pipeline under pipefail.
  if ! comment_ids=$(gh api --paginate "repos/$GITHUB_REPOSITORY/issues/$pr/comments?per_page=100" \
    --jq '.[] | select(.user.login == "github-actions[bot]" and (.body | startswith("<!-- grafana-preview -->"))) | .id'); then
    printf 'Failed to read preview comments for PR #%s\n' "$pr" >&2
    failed=1
    continue
  fi
  comment_id=$(printf '%s\n' "$comment_ids" | sed -n '1p')
  if [ -n "$comment_id" ]; then
    method=PATCH
    endpoint="repos/$GITHUB_REPOSITORY/issues/comments/$comment_id"
  else
    method=POST
    endpoint="repos/$GITHUB_REPOSITORY/issues/$pr/comments"
  fi
  if ! gh api --method "$method" "$endpoint" \
    --raw-field "body=$(cat "$PREVIEW_REPORT")" > /dev/null; then
    printf 'Failed to update preview comment for PR #%s\n' "$pr" >&2
    failed=1
  fi
done <<< "$targets"

# Notify every affected PR, but keep partial failures visible in Actions.
exit "$failed"
