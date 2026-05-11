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

**External Grafana** — Grafana's PostgreSQL driver is Go's `lib/pq`, which does not support `sslnegotiation=direct`. Pasting client cert + key into the Grafana UI does **not** work against this nginx setup — Grafana surfaces the error as `EOF` because nginx closes the connection on the SSLRequest preamble. Use the server-side stunnel approach below ("On a dedicated server").

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

**On a dedicated server (Grafana, exporters, anything Go/Java-based).** Same stunnel idea, but the laptop-style instructions above don't carry over cleanly — Ubuntu/Debian's `stunnel4` package has several stationary gotchas, and a containerized client (e.g. Grafana in docker on this host) can't reach `127.0.0.1` on the host.

1. Install and enable:
   ```sh
   sudo apt install stunnel4
   sudo sed -i 's/^ENABLED=0/ENABLED=1/' /etc/default/stunnel4
   ```
   The package ships with `ENABLED=0` as a safety; the systemd unit refuses to start until you flip it.

2. Place certs **inside** `/etc/stunnel/` to avoid the chroot issue (`stunnel4` on Ubuntu chroots to `/var/lib/stunnel4` by default, so paths in `/home/...` aren't visible):
   ```sh
   sudo mkdir -p /etc/stunnel/certs
   sudo cp /path/to/issued/{ca.crt,client.crt,client.key} /etc/stunnel/certs/
   sudo chown -R stunnel4:stunnel4 /etc/stunnel/certs
   sudo chmod 600 /etc/stunnel/certs/client.key
   ```

3. Drop `/etc/stunnel/sentinel.conf`:
   ```ini
   foreground = no
   # Use the package-managed pid directory, OR leave pid = empty.
   # /var/run/stunnel/ (no "4") does NOT exist on Ubuntu — only /var/run/stunnel4/ does.
   pid = /var/run/stunnel4/sentinel.pid

   [sentinel-prod-db]
   client = yes
   accept  = <bind-address>:5433
   connect = ${NGINX_HOST}:5432
   cert    = /etc/stunnel/certs/client.crt
   key     = /etc/stunnel/certs/client.key
   CAfile  = /etc/stunnel/certs/ca.crt
   verifyChain = yes
   checkHost   = ${NGINX_HOST}
   ```
   For `accept`, pick the bind address based on where the client lives:

   | Client lives on… | `accept =` |
   |---|---|
   | Same host, native (systemd service) | `127.0.0.1:5433` |
   | Docker container on the **default bridge** | `172.17.0.1:5433` |
   | Docker container on a **custom network** (e.g. `compose_default`) | output of `docker network inspect <name> --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'` |
   | Anywhere — simplest, broadest | `0.0.0.0:5433` (then firewall-restrict) |

4. Start it:
   ```sh
   sudo systemctl enable --now stunnel4
   sudo ss -tlnp | grep 5433       # confirm the listener is on the address you intended
   sudo journalctl -u stunnel4 -n 30 --no-pager
   ```

5. Configure the client (Grafana data source shown; other tools analogous):

   | Field         | Value                                          |
   |---------------|------------------------------------------------|
   | Host          | the same `<bind-address>:5433` you set above   |
   | Database      | `${POSTGRES_DB}`                               |
   | User          | the postgres role (recommended: read-only)     |
   | Password      | the role's password                            |
   | TLS/SSL Mode  | **disable** (stunnel terminates TLS)           |
   | TLS/SSL Auth  | off (clear any cert/key fields)                |
   | Version       | match the postgres major version on the server |

Sanity-check before saving in Grafana:

```sh
# From the host shell
nc -zv <bind-address> 5433

# From inside the client container (replace <grafana-container> as needed)
docker exec <grafana-container> sh -c 'nc -zv <bind-address> 5433'
```

Both should print `succeeded`. If the host-side test passes but the container-side fails, the bind address isn't reachable from the container's network — pick a different one from the table above.

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
