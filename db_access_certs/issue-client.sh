#!/bin/bash
# Issue one client cert signed by the local mTLS CA.
#
# WARNING: run on a workstation, NEVER on prod. ca.key must be in this
# directory at run time and removed/moved offline immediately after.
#
# Usage:  ./issue-client.sh <client-cn>
#
# Produces:
#   clients/<client-cn>/client.crt
#   clients/<client-cn>/client.key
#   clients/<client-cn>/ca.crt        (copy of the local CA cert)
# Appends one TSV row to issued.log.
# Refuses to overwrite if clients/<client-cn>/ already exists.

set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    echo "usage: $0 <client-cn>" >&2
    echo "  e.g. $0 internal-grafana.bittensor.church" >&2
    exit 1
fi

CN="$1"

# Filesystem-safe CN: letters/digits/dot/dash/underscore only. The CN is used
# verbatim as the output directory name, so reject anything with slashes,
# spaces, or shell-special characters.
if ! printf '%s' "$CN" | grep -Eq '^[A-Za-z0-9._-]+$'; then
    echo "error: <client-cn> must match [A-Za-z0-9._-]+ (got: $CN)" >&2
    exit 1
fi

# The character class above also accepts "." and "..", which resolve to the
# clients/ directory itself and the script directory respectively. Reject them
# explicitly so OUTDIR is always a fresh, distinct subdirectory.
if [ "$CN" = "." ] || [ "$CN" = ".." ]; then
    echo "error: <client-cn> cannot be '.' or '..'" >&2
    exit 1
fi

cd "$(dirname "$0")"

echo
echo "  WARNING: run on a workstation, NEVER on prod. ca.key must stay offline."
echo

if [ ! -f ca.crt ] || [ ! -f ca.key ]; then
    echo "error: ca.crt and ca.key must both be in $PWD before issuing a client" >&2
    echo "       cert. Bring ca.key in from offline storage, run this script," >&2
    echo "       then remove ca.key again." >&2
    exit 1
fi

OUTDIR="clients/$CN"
if [ -e "$OUTDIR" ]; then
    echo "error: $PWD/$OUTDIR already exists. Re-issuance for an existing CN is" >&2
    echo "       blocked. Remove the directory explicitly if you really mean to" >&2
    echo "       re-issue (the old client cert remains valid until expiry)." >&2
    exit 1
fi

mkdir -p "$OUTDIR"

LEAF_DAYS=825

openssl genrsa -out "$OUTDIR/client.key" 4096 2>/dev/null
openssl req -new -key "$OUTDIR/client.key" -out "$OUTDIR/client.csr" -subj "/CN=$CN"

cat > "$OUTDIR/client.ext" <<'EOF'
extendedKeyUsage=clientAuth
EOF

# Use the existing ca.srl if present (init.sh leaves one behind so serials
# advance monotonically). Fall back to -CAcreateserial otherwise so the
# script still works on a CA that pre-dates the script.
if [ -f ca.srl ]; then
    openssl x509 -req -in "$OUTDIR/client.csr" -CA ca.crt -CAkey ca.key \
        -CAserial ca.srl -out "$OUTDIR/client.crt" -days "$LEAF_DAYS" \
        -sha256 -extfile "$OUTDIR/client.ext"
else
    openssl x509 -req -in "$OUTDIR/client.csr" -CA ca.crt -CAkey ca.key \
        -CAcreateserial -out "$OUTDIR/client.crt" -days "$LEAF_DAYS" \
        -sha256 -extfile "$OUTDIR/client.ext"
fi

cp ca.crt "$OUTDIR/ca.crt"
rm -f "$OUTDIR/client.csr" "$OUTDIR/client.ext"

# Audit log: tab-separated, append-only.
DATE_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SERIAL="$(openssl x509  -in "$OUTDIR/client.crt" -noout -serial    | cut -d= -f2)"
NOT_BEFORE="$(openssl x509 -in "$OUTDIR/client.crt" -noout -startdate | cut -d= -f2)"
NOT_AFTER="$(openssl x509  -in "$OUTDIR/client.crt" -noout -enddate   | cut -d= -f2)"
printf '%s\t%s\t%s\t%s\t%s\n' \
    "$DATE_ISO" "$SERIAL" "$CN" "$NOT_BEFORE" "$NOT_AFTER" >> issued.log

cat <<EOF

Client cert issued for "$CN" (serial $SERIAL, expires $NOT_AFTER):
  $PWD/$OUTDIR/client.crt
  $PWD/$OUTDIR/client.key
  $PWD/$OUTDIR/ca.crt

Distribute all three files to the consumer via a secure channel.
If you brought ca.key in from offline storage, shred or move it now.
EOF
