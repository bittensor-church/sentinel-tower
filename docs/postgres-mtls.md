# Remote PostgreSQL access (mTLS)

The prod stack exposes PostgreSQL on port `5432` with **mutual TLS** terminated at nginx. There is no host port binding on the `db` container — every external connection must present a client certificate signed by our CA. Internal services (app, celery, etc.) keep talking to `db:5432` on the docker network in cleartext as before.

This page covers operator workflows. For background, see [`docs/superpowers/specs/2026-05-11-postgres-mtls-via-nginx-stream-design.md`](superpowers/specs/2026-05-11-postgres-mtls-via-nginx-stream-design.md) (git-ignored; lives in the working tree of whoever wrote the spec).

## Architecture

```
external client (client.crt / client.key + ca.crt)
        │  TLS 1.2/1.3 + mTLS
        ▼
nginx :5432  (stream block — see nginx/stream.d/postgres.conf)
        │  plain TCP, docker network
        ▼
db :5432  (postgres, no host binding)
```

Relevant files in the repo:

| File                                         | Purpose                                                                 |
|----------------------------------------------|-------------------------------------------------------------------------|
| [`nginx/nginx.conf`](../nginx/nginx.conf)    | Override of the image-baked nginx.conf adding the top-level `stream {}` block (with `log_format`, shared cipher list, and stream include). |
| [`nginx/stream.d/postgres.conf`](../nginx/stream.d/postgres.conf) | The mTLS-terminating stream server on `:5432`.                          |
| [`db_access_certs/`](../db_access_certs/)    | Server-side cert material (git-ignored except for the README).          |
| [`db_access_certs/README.md`](../db_access_certs/README.md) | Operator runbook for the cert-issuance scripts (bootstrap, add client, audit). |
| [`envs/prod/docker-compose.yml`](../envs/prod/docker-compose.yml) | Wires the bind mounts and exposes nginx `:5432`.                        |

## Initial setup (one-time per environment)

1. **Bootstrap the CA and server cert** on a workstation. From a clean checkout of this repo:
   ```sh
   cd db_access_certs
   ./init.sh ${NGINX_HOST}   # the prod hostname, e.g. sentinel-tower.bittensor.church
   ```
   This produces `ca.{crt,key}`, `server.{crt,key}`, and `ca.srl` in `db_access_certs/`. See [`db_access_certs/README.md`](../db_access_certs/README.md) for the exact `openssl` flags if you're curious.
2. **Move `ca.key` offline.** It must NOT live on the server. You'll need it to issue more client certs later; store it in a password manager / vault / encrypted offline media.
3. **Copy `ca.crt`, `server.crt`, `server.key` to the prod host** into `db_access_certs/`. After this step, that directory on the prod host contains:
   ```
   db_access_certs/
   ├── .gitignore
   ├── README.md
   ├── ca.crt
   ├── server.crt
   └── server.key
   ```
4. **Deploy.** `./deploy.sh` (or whatever your prod deploy mechanism is) brings the stack up. nginx will refuse to start if any of the three cert files is missing or unreadable, so a failed boot is the signal that step 3 wasn't done.
5. **Verify** with the test commands in the [Testing the endpoint](#testing-the-endpoint) section below.

## Adding a new client

Most common operation. The CA is the only thing that can sign new client certs — so this happens wherever `ca.key` and `ca.crt` live (your workstation / vault).

1. On the workstation that has `ca.key` (bring it in from offline storage first), run:
   ```sh
   cd db_access_certs
   ./issue-client.sh <client-cn>   # e.g. internal-grafana.bittensor.church
   ```
   Output goes to `clients/<client-cn>/{client.crt,client.key,ca.crt}` and a row is appended to `issued.log`. Use a CN that identifies the consumer — it's logged on every connection and shows up in `issued.log` for audit. After issuance, move `ca.key` back offline.
2. Securely deliver three files to the consumer: `client.crt`, `client.key`, `ca.crt`.
3. **Nothing on the server changes.** nginx validates new clients against the existing CA on every handshake; no reload, no redeploy.

## Testing the endpoint

Run from a host that has the client cert triplet. **Requires libpq ≥17** for `sslnegotiation=direct` (PostgreSQL 17 client libraries). On older clients use the docker fallback shown below.

`sslnegotiation=direct` is required because nginx terminates TLS at the TCP layer (`listen 5432 ssl;`) and expects a TLS ClientHello as the first bytes. Without it, libpq sends an 8-byte `SSLRequest` preamble first, which nginx parses as a malformed TLS record (`SSL: error:0A00010B:SSL routines::wrong version number`).

**Happy path** — should succeed and print `now`:

```sh
psql "host=${NGINX_HOST} port=5432 dbname=${POSTGRES_DB} user=${POSTGRES_USER} \
      sslnegotiation=direct sslmode=verify-full \
      sslrootcert=ca.crt sslcert=client.crt sslkey=client.key" \
     -c 'select now();'
```

If you don't have libpq 17 installed locally, run the same connstring inside the `postgres:17` image:

```sh
docker run --rm -e PGPASSWORD='<password>' -v "$PWD:/certs:ro" -w /certs postgres:17 \
  psql "host=${NGINX_HOST} port=5432 dbname=${POSTGRES_DB} user=${POSTGRES_USER} \
        sslnegotiation=direct sslmode=verify-full \
        sslrootcert=ca.crt sslcert=client.crt sslkey=client.key" -c 'select now();'
```

**Negative — no client cert** — should fail at TLS handshake (`tlsv13 alert certificate required`):

```sh
psql "host=${NGINX_HOST} port=5432 dbname=${POSTGRES_DB} user=${POSTGRES_USER} \
      sslnegotiation=direct sslmode=require"
```

**Negative — verify-full with IP** — should fail SAN check (proves hostname verification works):

```sh
psql "host=$(getent hosts ${NGINX_HOST} | awk '{print $1}') port=5432 \
      dbname=${POSTGRES_DB} user=${POSTGRES_USER} \
      sslnegotiation=direct sslmode=verify-full \
      sslrootcert=ca.crt sslcert=client.crt sslkey=client.key"
```

**Internal admin** — should still work from the prod host:

```sh
docker compose -f envs/prod/docker-compose.yml exec db psql -U "${POSTGRES_USER}" "${POSTGRES_DB}" -c 'select 1;'
```

## Connecting from common tools

**psql** — see commands above.

**External Grafana** (a separate Grafana instance, not the one inside our compose) — add a PostgreSQL data source with:

| Field                 | Value                                                |
|-----------------------|------------------------------------------------------|
| Host                  | `${NGINX_HOST}:5432`                                 |
| TLS/SSL Mode          | `verify-full`                                        |
| TLS/SSL Auth          | enabled                                              |
| TLS/SSL Root Cert     | contents of `ca.crt`                                 |
| TLS/SSL Client Cert   | contents of `client.crt`                             |
| TLS/SSL Client Key    | contents of `client.key`                             |
| User / Password / DB  | `${POSTGRES_READONLY_USER}` recommended (read-only)  |

**Python (psycopg)** — connect with:

```python
psycopg.connect(
    host=NGINX_HOST, port=5432, dbname=..., user=..., password=...,
    sslnegotiation="direct", sslmode="verify-full",
    sslrootcert="ca.crt", sslcert="client.crt", sslkey="client.key",
)
```

Requires libpq ≥17 (psycopg links against the system libpq).

`client.key` must be `chmod 600` or psycopg/libpq refuses to use it.

**GUI clients (Beekeeper Studio, DBeaver, DataGrip, …) — via local stunnel.** GUI clients typically use drivers that don't support direct SSL — Beekeeper Studio uses `node-postgres` (pure JS), and DBeaver / DataGrip default to the pgjdbc JDBC driver. Neither supports `sslnegotiation=direct`, so they cannot terminate TLS directly against nginx. Run a local TLS proxy that handles direct SSL + the client cert for them:

1. Install stunnel (`sudo apt install stunnel4` / `brew install stunnel`).
2. Create `~/stunnel-sentinel.conf` (adjust the cert paths and host):
   ```ini
   foreground = yes
   pid =
   output = /dev/stderr

   [postgres-mtls]
   client = yes
   accept  = 127.0.0.1:5433
   connect = ${NGINX_HOST}:5432
   cert    = /path/to/client.crt
   key     = /path/to/client.key
   CAfile  = /path/to/ca.crt
   verifyChain = yes
   checkHost   = ${NGINX_HOST}
   # alpn = postgresql   # uncomment if your stunnel build (5.65+) needs explicit ALPN
   ```
3. Run it in a terminal and leave it running while you use the UI:
   ```sh
   stunnel ~/stunnel-sentinel.conf
   ```
4. In the UI, create a connection with **SSL/TLS disabled**:

   | Field         | Value                              |
   |---------------|------------------------------------|
   | Host          | `127.0.0.1`                        |
   | Port          | `5433`                             |
   | SSL/TLS       | **off** (stunnel terminates TLS)   |
   | SSH tunnel    | off                                |
   | User/Password/DB | as usual                        |

The UI sees a plain local postgres while stunnel handles the direct-SSL + mTLS handshake against nginx. Success looks like `Negotiated TLSv1.3` in the stunnel log followed by a normal postgres password prompt in the UI.

## Rotation & revocation

See the **Revocation / rotation** section of [`db_access_certs/README.md`](../db_access_certs/README.md). Short version: per-client revocation is **not** implemented (no CRL/OCSP). Real options for a compromised client are CA rotation, waiting for cert expiry while disabling the consumer's postgres role, or adding `ssl_crl` to `nginx/stream.d/postgres.conf` once a CRL workflow exists.

## Re-syncing `nginx/nginx.conf` after an nginx-rt image bump

`nginx/nginx.conf` is a copy of the image's baked-in `/etc/nginx/nginx.conf` plus our `stream { ... }` block. When `ghcr.io/reef-technologies/nginx-rt` is bumped in `envs/prod/docker-compose.yml`, re-sync:

```sh
docker run --rm --entrypoint cat ghcr.io/reef-technologies/nginx-rt:<new-tag> /etc/nginx/nginx.conf > /tmp/baked.conf
diff /tmp/baked.conf nginx/nginx.conf
```

The only expected differences are our leading comment block and the trailing `stream { ... }` block. If anything inside `http { }` changed in the new image, port those changes into our `nginx/nginx.conf` and update the comment's "Synced from" tag line. Validate with:

```sh
docker run --rm \
  -v $(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v $(pwd)/nginx/stream.d:/etc/nginx/stream.d:ro \
  -v /path/to/stub/db_access_certs:/etc/db_access_certs:ro \
  --entrypoint sh ghcr.io/reef-technologies/nginx-rt:<new-tag> -c 'nginx -t'
```

(stub certs can be any valid PEM, e.g. `openssl req -x509 -newkey rsa:2048 -nodes -keyout server.key -out server.crt -days 1 -subj "/CN=test"` then `cp server.crt ca.crt`)

## Troubleshooting

| Symptom (client side)                                                  | Likely cause                                                                          |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `SSL error: tlsv1 alert unknown ca`                                    | Client cert was signed by a different CA than `db_access_certs/ca.crt`. Reissue.      |
| `SSL error: tlsv13 alert certificate required`                         | Client isn't presenting a cert — check `sslcert`/`sslkey` paths and file permissions. |
| `SSL: error:0A00010B:SSL routines::wrong version number`               | Client did NOT use `sslnegotiation=direct` — libpq sent the SSLRequest preamble before TLS. Add `sslnegotiation=direct` and upgrade to libpq ≥17. |
| `direct SSL connection was established without ALPN protocol negotiation extension` | Server-side: `ssl_alpn postgresql;` is missing from `nginx/stream.d/postgres.conf`. Required when clients use `sslnegotiation=direct`. |
| `server certificate for "X" does not match host name "Y"`              | SAN mismatch. Connect with the hostname in the server cert's SAN, or use `sslmode=verify-ca` (weaker). |
| `psql: error: could not connect to server: Connection refused` on 5432 | nginx didn't bring up the stream listener. Check `docker compose logs nginx`.         |
| Server-side: nginx restarting in a loop                                | Almost always a missing/unreadable cert file in `/etc/db_access_certs/` or a syntax error in `nginx/stream.d/postgres.conf`. Run `docker compose logs nginx` and `docker compose exec nginx nginx -t`. |

To inspect what nginx loaded after a deploy:

```sh
docker compose -f envs/prod/docker-compose.yml exec nginx nginx -T 2>&1 | grep -B1 -A30 -E 'stream\s*\{'
```
