# `db_access_certs/`

Files required for PostgreSQL mTLS on port `5432`. mTLS is terminated by the nginx container, which proxies plain TCP to the internal `db` service. Only the files in **Keep on the server** are mounted into nginx.

## Layout

| File         | Purpose                                                         |
|--------------|-----------------------------------------------------------------|
| `ca.crt`     | CA certificate; nginx uses this to verify client certificates.  |
| `server.crt` | Server cert presented by nginx on `:5432`.                      |
| `server.key` | Private key for `server.crt`.                                   |

Mounted into the nginx container as `/etc/db_access_certs:ro`.

Replace `${NGINX_HOST}` below with the production hostname (e.g. `sentinel-tower.bittensor.church`).

## Generate certificates

### 1. CA

```sh
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
    -out ca.crt -subj "/CN=sentinel-tower-db-ca"
```

### 2. Server key and CSR

```sh
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
    -subj "/CN=${NGINX_HOST}"
```

### 3. Sign the server cert with a SAN for the public hostname

```sh
cat > server.ext <<EOF
subjectAltName=DNS:${NGINX_HOST}
extendedKeyUsage=serverAuth
EOF

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 825 -sha256 -extfile server.ext
```

### 4. Per-consumer client key and CSR

Replace `<client-cn>` with something identifying the consumer, e.g. `internal-grafana.bittensor.church` or `analyst-alice`.

```sh
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr \
    -subj "/CN=<client-cn>"
```

### 5. Sign the client cert

```sh
cat > client.ext <<'EOF'
extendedKeyUsage=clientAuth
EOF

openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAserial ca.srl \
    -out client.crt -days 825 -sha256 -extfile client.ext
```

## Keep on the server

- `ca.crt`
- `server.crt`
- `server.key`

## Distribute to each approved client

- `client.crt`
- `client.key`
- `ca.crt`

## Cleanup

After issuance, remove temporary files:

```sh
rm -f ca.key ca.srl server.csr server.ext client.csr client.ext
```

Keep `ca.key` somewhere safe if you intend to issue more client certs later — otherwise you must re-issue everything.

## Test from a client

```sh
psql "host=${NGINX_HOST} port=5432 dbname=<db> user=<user> \
      sslmode=verify-full sslrootcert=ca.crt sslcert=client.crt sslkey=client.key"
```

## Revocation / rotation

- **One client compromised** — rotate that client's `client.crt`/`client.key`. Other clients are unaffected. Nginx does not need a reload because client cert validity is checked per-handshake against the CA.
- **CA compromised** — regenerate `ca.crt`, reissue every client cert, replace the server-side `ca.crt`, and reload nginx (`docker compose exec nginx nginx -s reload`).
