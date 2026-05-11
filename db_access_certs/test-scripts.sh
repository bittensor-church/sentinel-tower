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

group "init.sh refuse-to-overwrite"
WORK="$(new_workdir)"
( cd "$WORK" && ./init.sh test.example.com ) >/dev/null 2>&1
# Capture the ca.crt fingerprint so we can prove the second run did not touch it.
FP_BEFORE="$(openssl x509 -in "$WORK/ca.crt" -noout -fingerprint -sha256)"
SECOND_OUTPUT="$( cd "$WORK" && ./init.sh test.example.com 2>&1 || true )"
FP_AFTER="$(openssl x509 -in "$WORK/ca.crt" -noout -fingerprint -sha256)"
assert "second init.sh exits non-zero" \
    bash -c "( cd '$WORK' && ./init.sh test.example.com ) >/dev/null 2>&1; [ \$? -ne 0 ]"
assert "error message mentions existing files" \
    bash -c "echo '$SECOND_OUTPUT' | grep -qi 'already exists'"
assert "ca.crt fingerprint unchanged after refused second run" \
    bash -c "[ '$FP_BEFORE' = '$FP_AFTER' ]"

group "issue-client.sh happy path + audit log + unique serials"
WORK="$(new_workdir)"
( cd "$WORK" && ./init.sh test.example.com ) >/dev/null 2>&1
( cd "$WORK" && ./issue-client.sh alice )   >/dev/null 2>&1
ALICE_RC=$?
( cd "$WORK" && ./issue-client.sh bob )     >/dev/null 2>&1
BOB_RC=$?

assert "issue-client.sh alice exits 0"            [ "$ALICE_RC" -eq 0 ]
assert "issue-client.sh bob   exits 0"            [ "$BOB_RC"   -eq 0 ]
assert "clients/alice/client.crt produced"        [ -f "$WORK/clients/alice/client.crt" ]
assert "clients/alice/client.key produced"        [ -f "$WORK/clients/alice/client.key" ]
assert "clients/alice/ca.crt copied for client"   [ -f "$WORK/clients/alice/ca.crt" ]
assert "clients/bob/client.crt produced"          [ -f "$WORK/clients/bob/client.crt" ]
assert "client.csr cleaned up (alice)"            [ ! -f "$WORK/clients/alice/client.csr" ]
assert "client.ext cleaned up (alice)"            [ ! -f "$WORK/clients/alice/client.ext" ]

assert "alice client cert chains to CA" \
    openssl verify -CAfile "$WORK/ca.crt" "$WORK/clients/alice/client.crt"
assert "alice client cert has clientAuth EKU" \
    bash -c "openssl x509 -in '$WORK/clients/alice/client.crt' -noout -ext extendedKeyUsage | grep -q 'TLS Web Client Authentication'"
assert "alice client cert CN is 'alice'" \
    bash -c "openssl x509 -in '$WORK/clients/alice/client.crt' -noout -subject | grep -q 'CN *= *alice'"

assert "issued.log exists"                        [ -f "$WORK/issued.log" ]
assert "issued.log has exactly 2 rows" \
    bash -c "[ \"\$(wc -l < '$WORK/issued.log')\" = '2' ]"
assert "issued.log rows have 5 tab-separated columns" \
    bash -c "awk -F'\t' 'NF != 5 { exit 1 }' '$WORK/issued.log'"
assert "issued.log column 3 contains both CNs" \
    bash -c "awk -F'\t' '{print \$3}' '$WORK/issued.log' | sort | uniq | tr '\n' ',' | grep -q 'alice,bob,'"

# Serial uniqueness: server cert serial must differ from both client cert serials,
# and the two client serials must differ from each other.
S_SRV="$(openssl x509 -in "$WORK/server.crt"             -noout -serial | cut -d= -f2)"
S_A="$(  openssl x509 -in "$WORK/clients/alice/client.crt" -noout -serial | cut -d= -f2)"
S_B="$(  openssl x509 -in "$WORK/clients/bob/client.crt"   -noout -serial | cut -d= -f2)"
assert "server serial != alice serial" bash -c "[ '$S_SRV' != '$S_A' ]"
assert "server serial != bob serial"   bash -c "[ '$S_SRV' != '$S_B' ]"
assert "alice serial  != bob serial"   bash -c "[ '$S_A'   != '$S_B' ]"

group "issue-client.sh preconditions"
WORK="$(new_workdir)"

# Case 1: no CA at all.
NO_CA_OUTPUT="$( cd "$WORK" && ./issue-client.sh alice 2>&1 || true )"
assert "fails when ca.crt is missing" \
    bash -c "( cd '$WORK' && ./issue-client.sh alice ) >/dev/null 2>&1; [ \$? -ne 0 ]"
assert "missing-CA error message mentions ca.key" \
    bash -c "echo '$NO_CA_OUTPUT' | grep -q 'ca.key'"

# Case 2: existing client directory.
( cd "$WORK" && ./init.sh test.example.com ) >/dev/null 2>&1
( cd "$WORK" && ./issue-client.sh alice )    >/dev/null 2>&1
EXISTING_OUTPUT="$( cd "$WORK" && ./issue-client.sh alice 2>&1 || true )"
assert "fails when clients/<cn>/ already exists" \
    bash -c "( cd '$WORK' && ./issue-client.sh alice ) >/dev/null 2>&1; [ \$? -ne 0 ]"
assert "existing-client error mentions re-issuance" \
    bash -c "echo '$EXISTING_OUTPUT' | grep -qi 're-issu'"
# issued.log must still have exactly one entry (the original alice) after the refused second run.
assert "issued.log unchanged after refused re-issuance" \
    bash -c "[ \"\$(wc -l < '$WORK/issued.log')\" = '1' ]"

# Case 3: bad CN (with a slash).
BAD_CN_OUTPUT="$( cd "$WORK" && ./issue-client.sh 'evil/cn' 2>&1 || true )"
assert "rejects CN containing a slash" \
    bash -c "( cd '$WORK' && ./issue-client.sh 'evil/cn' ) >/dev/null 2>&1; [ \$? -ne 0 ]"
assert "bad-CN error names the CN" \
    bash -c "echo '$BAD_CN_OUTPUT' | grep -q 'evil/cn'"

group "nginx -t smoke (requires docker)"
if ! command -v docker >/dev/null 2>&1; then
    ok "docker not present — skipping nginx integration smoke"
else
    WORK="$(new_workdir)"
    ( cd "$WORK" && ./init.sh test.example.com ) >/dev/null 2>&1

    # Stage a stub stream config that uses a resolvable upstream (127.0.0.1)
    # in place of the docker-network "db" hostname.
    STREAM_D="$(mktemp -d "$TMPROOT/stream.d.XXXXXX")"
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    sed 's/server db:5432/server 127.0.0.1:5432/' \
        "$REPO_ROOT/nginx/stream.d/postgres.conf" > "$STREAM_D/postgres.conf"

    NGINX_OUTPUT="$( docker run --rm \
        -v "$REPO_ROOT/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
        -v "$STREAM_D:/etc/nginx/stream.d:ro" \
        -v "$WORK:/etc/db_access_certs:ro" \
        --entrypoint sh ghcr.io/reef-technologies/nginx-rt:v1.2.2 \
        -c 'nginx -t' 2>&1 || true )"
    assert "nginx -t accepts the generated certs" \
        bash -c "echo '$NGINX_OUTPUT' | grep -q 'test is successful'"
fi

# ---- summary ----

printf '\n'
if [ "$FAIL" -eq 0 ]; then
    printf '\033[32mAll %d checks passed.\033[0m\n' "$PASS"
    exit 0
fi
printf '\033[31m%d failed / %d passed\033[0m\n' "$FAIL" "$PASS"
for n in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$n"; done
exit 1
