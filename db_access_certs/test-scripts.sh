#!/bin/bash
# Automated end-to-end test of db_access_certs/init.sh and issue-client.sh.
# Run from the repo root:  ./db_access_certs/test-scripts.sh
# Or from this directory:  ./test-scripts.sh
#
# Creates a tmpdir, copies the scripts in, exercises every documented behavior,
# and reports pass/fail per check. Exits 0 only if everything passes.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

PASS=0
FAIL=0
FAILED_NAMES=()

ok()    { printf '  \033[32mok\033[0m   %s\n' "$1"; PASS=$((PASS + 1)); }
fail()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); }
group() { printf '\n\033[1m# %s\033[0m\n' "$1"; }

# Run an arbitrary check.  Usage: assert <name> <command...>
# Asserts the command exits 0.
assert() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then ok "$name"; else fail "$name"; fi
}

# Asserts the command exits NON-zero (used for refuse-to-overwrite checks).
assert_fails() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then fail "$name (should have errored)"; else ok "$name"; fi
}

# Returns the path to a fresh per-test working directory with init.sh and
# issue-client.sh copied in.
new_workdir() {
    local d
    d="$(mktemp -d "$TMPROOT/work.XXXXXX")"
    cp "$SCRIPT_DIR/init.sh" "$d/"
    [ -f "$SCRIPT_DIR/issue-client.sh" ] && cp "$SCRIPT_DIR/issue-client.sh" "$d/"
    echo "$d"
}

# ---- tests start ----

group "init.sh happy path"
WORK="$(new_workdir)"
( cd "$WORK" && ./init.sh test.example.com ) >/dev/null 2>&1
assert "init.sh exits 0 with valid hostname"      [ $? -eq 0 ]
assert "ca.crt produced"                          [ -f "$WORK/ca.crt" ]
assert "ca.key produced"                          [ -f "$WORK/ca.key" ]
assert "server.crt produced"                      [ -f "$WORK/server.crt" ]
assert "server.key produced"                      [ -f "$WORK/server.key" ]
assert "ca.srl kept (needed for client serials)"  [ -f "$WORK/ca.srl" ]
assert "server.csr cleaned up"                    [ ! -f "$WORK/server.csr" ]
assert "server.ext cleaned up"                    [ ! -f "$WORK/server.ext" ]
assert "server cert has SAN for given host" \
    bash -c "openssl x509 -in '$WORK/server.crt' -noout -ext subjectAltName | grep -q 'DNS:test.example.com'"
assert "ca cert subject is sentinel-tower-db-ca" \
    bash -c "openssl x509 -in '$WORK/ca.crt' -noout -subject | grep -q 'CN *= *sentinel-tower-db-ca'"
assert "server cert chains to CA" \
    openssl verify -CAfile "$WORK/ca.crt" "$WORK/server.crt"

# ---- summary ----

printf '\n'
if [ "$FAIL" -eq 0 ]; then
    printf '\033[32mAll %d checks passed.\033[0m\n' "$PASS"
    exit 0
fi
printf '\033[31m%d failed / %d passed\033[0m\n' "$FAIL" "$PASS"
for n in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$n"; done
exit 1
