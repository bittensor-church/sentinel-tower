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

Move `ca.key` somewhere offline and secure (e.g. a password manager, encrypted USB, vault). You will need it to issue additional client certs in the future. **Do not leave `ca.key` on the production server** — its compromise means the entire mTLS gate is compromised.

After issuance, remove the remaining temporary files from the working directory:

```sh
rm -f ca.srl server.csr server.ext client.csr client.ext
```

## Test from a client

```sh
psql "host=${NGINX_HOST} port=5432 dbname=<db> user=<user> \
      sslmode=verify-full sslrootcert=ca.crt sslcert=client.crt sslkey=client.key"
```

## Revocation / rotation

**This setup does not implement per-client revocation.** Without a CRL or OCSP responder, a client cert remains valid until it expires (~825 days). Plan your response accordingly:

- **One client compromised** — there is no way to invalidate that specific cert alone short of rotating the CA. Practical options, worst-case to least bad:
  1. **Rotate the CA** (see below). Slow, affects every client, but is the only true revocation.
  2. **Wait for the cert to expire.** Use only if the consumer can be locked out at the postgres role level (revoke the role's password / drop the role) in the meantime, since postgres role auth is the second factor.
  3. **Configure `ssl_crl`** in `nginx/stream.d/postgres.conf` and start publishing a CRL — out of scope for this initial setup.
- **CA compromised** — regenerate `ca.crt` and `ca.key` (offline), reissue every client cert against the new CA, replace `db_access_certs/ca.crt` on the server, and reload nginx:
  ```sh
  docker compose exec nginx nginx -s reload
  ```
  Old client certs stop working as soon as the new `ca.crt` is in place.
