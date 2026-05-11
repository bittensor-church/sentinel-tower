# PostgreSQL mTLS certificates

Files required for PostgreSQL mTLS on port `5432`. mTLS is terminated by the nginx container, which proxies plain TCP to the internal `db` service. Only the files in **Keep on the server** are mounted into nginx.

## Layout

| File         | Purpose                                                         |
|--------------|-----------------------------------------------------------------|
| `ca.crt`     | CA certificate; nginx uses this to verify client certificates.  |
| `server.crt` | Server cert presented by nginx on `:5432`.                      |
| `server.key` | Private key for `server.crt`.                                   |

Mounted into the nginx container as `/etc/db_access_certs:ro`.

Replace `${NGINX_HOST}` below with the production hostname (e.g. `sentinel-tower.bittensor.church`).

## Issue certificates

Two scripts in this directory replace the manual `openssl` workflow. Both must be run on a workstation, never on the prod host — `ca.key` must stay offline between issuances.

### Bootstrap (one-time per environment)

```sh
./init.sh ${NGINX_HOST}
```

Produces `ca.{crt,key}`, `server.{crt,key}`, and `ca.srl`. Refuses to overwrite if any of those already exist. Print output ends with a "Next steps" reminder to scp the server triplet to prod and move `ca.key` offline.

### Add a new client

```sh
./issue-client.sh <client-cn>
# e.g. ./issue-client.sh internal-grafana.bittensor.church
```

`ca.crt` and `ca.key` must be in this directory at run time (bring `ca.key` in from offline storage, run the script, remove it again). Output goes to `clients/<client-cn>/{client.crt,client.key,ca.crt}` and one row is appended to `issued.log`. Refuses to overwrite an existing `clients/<client-cn>/` directory.

### Look up who has access

```sh
column -t -s $'\t' < issued.log              # human-readable
awk -F'\t' '$3 == "alice"' issued.log        # filter by CN
sort -t $'\t' -k5 issued.log                 # sort by expiry
```

The exact `openssl` commands the scripts run are visible in [`init.sh`](init.sh) and [`issue-client.sh`](issue-client.sh) — read those if you ever need to reproduce them by hand.

### Run the test suite

```sh
./test-scripts.sh
```

End-to-end test that exercises `init.sh` and `issue-client.sh` in a tmpdir, including a `nginx -t` smoke against the prod nginx config (skipped if Docker is unavailable). Useful after editing the scripts or bumping the nginx-rt image.

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

`init.sh` and `issue-client.sh` already clean up the transient `*.csr` / `*.ext` files. `ca.srl` is kept on purpose — `issue-client.sh` advances it to guarantee unique cert serial numbers across all certs signed by this CA. Move it offline alongside `ca.key`.

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
