#!/bin/bash
# Bootstrap the postgres mTLS CA and server cert.
#
# WARNING: run on a workstation, NEVER on prod. ca.key must stay offline.
#
# Usage:  ./init.sh <nginx-host>
#
# Produces, in this script's directory:
#   ca.crt, ca.key, server.crt, server.key, ca.srl
# Refuses to overwrite if any of the four cert/key files already exist.

set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    echo "usage: $0 <nginx-host>" >&2
    echo "  e.g. $0 sentinel-tower.bittensor.church" >&2
    exit 1
fi

NGINX_HOST="$1"

# Always operate in our own directory so paths are unambiguous.
cd "$(dirname "$0")"

echo
echo "  WARNING: run on a workstation, NEVER on prod. ca.key must stay offline."
echo

# Refuse to overwrite. Rotating the CA is a deliberate operation: remove the
# files explicitly first.
for f in ca.crt ca.key server.crt server.key; do
    if [ -e "$f" ]; then
        echo "error: $PWD/$f already exists. Remove or move the existing CA/server" >&2
        echo "       files explicitly before re-running init.sh." >&2
        exit 1
    fi
done

CA_DAYS=3650
LEAF_DAYS=825

# ---- CA ----
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days "$CA_DAYS" \
    -out ca.crt -subj "/CN=sentinel-tower-db-ca"

# ---- server ----
openssl genrsa -out server.key 4096 2>/dev/null
openssl req -new -key server.key -out server.csr -subj "/CN=$NGINX_HOST"

cat > server.ext <<EOF
subjectAltName=DNS:$NGINX_HOST
extendedKeyUsage=serverAuth
EOF

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days "$LEAF_DAYS" -sha256 -extfile server.ext

# Cleanup transient files. Keep ca.srl: issue-client.sh advances it for
# unique serial numbers across all certs signed by this CA.
rm -f server.csr server.ext

cat <<EOF

CA and server cert created in $PWD:
  ca.crt       (distribute to clients)
  ca.key       (KEEP OFFLINE — move to vault / encrypted media now)
  server.crt   (deploy to prod $PWD/)
  server.key   (deploy to prod $PWD/)
  ca.srl       (serial counter — keep alongside ca.key)

Next steps:
  1. scp ca.crt server.crt server.key to the prod host's db_access_certs/.
  2. Move ca.key + ca.srl to offline storage (vault, encrypted USB, etc.).
  3. Run ./issue-client.sh <cn> once per consumer (requires ca.key + ca.srl
     to be in this directory at run time).
EOF
