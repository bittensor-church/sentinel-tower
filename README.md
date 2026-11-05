```
    ╔═══════════════════════════════╗
    ║   ___                         ║
    ║  [O_O]  BITTENSOR SENTINEL    ║
    ║   |||                         ║
    ║  /| |\   Watching the chain   ║
    ║   | |                         ║
    ║  _|_|_                        ║
    ║ [#0A]═[#0B]═[#0C]  ≡≡≡        ║
    ╚═══════════════════════════════╝
```

# Bittensor Sentinel

A platform that allows for tracking and alerting on specific events/patterns/anomalies.
Sentinel records Bittensor chain activity in PostgreSQL, serves it through Grafana dashboards
and the Django admin, and sends governance alerts to Discord. What its users can do is described
in [USER_STORIES.md](USER_STORIES.md).

## How it works

- **Extrinsics.** The `sync_extrinsics` daemon records every extrinsic as blocks appear. A block
  that cannot be read stays a detectable gap for `backfill_extrinsics` instead of being stored as
  empty. Failed chain calls reopen the connection and retry with exponential backoff instead of
  exiting; the first retry of a lasting outage is logged at error level (and reaches Sentry).
- **Notifications.** Each successful extrinsic is matched against the notification handlers,
  after unwrapping sudo and executed multisig calls, and posted to Discord: to the channel
  configured for that alert type, or, for subnet-routed alerts, to the subnet's webhooks from
  admin (`SubnetWebhook`). Unhandled sudo calls go to a
  catch-all alert; multisig proposals and intermediate approvals are not alerted.
- **Metagraph snapshots.** `sync_metagraph` dumps every subnet's metagraph at epoch start, two
  intermediate points and epoch end. Missing dumps are repaired automatically (see
  [Automatic metagraph gap repair](#automatic-metagraph-gap-repair)).
- **Derived data.** Validator APY facts are updated incrementally every 15 minutes. Burns,
  superburns (`METAGRAPH_SUPERBURN_COLDKEY`) and subnet emission flags are recorded from each
  epoch-start snapshot against the root subnet's epoch; a missing anchor block is recovered from
  Finney, then the archive node. Coldkey identities refresh hourly; manual key labels win over
  them. Hyperparameter changes from extrinsics update the current-value table and append their
  old and new value to its history.
- **Retention.** A daily job prunes old low-value rows (non-validator neuron snapshots, weights,
  bonds and collateral past their retention windows) in bounded batches; validator APY data is
  kept forever.
- **Workers.** Expensive metagraph tasks run on the `metagraph` queue and everything else on
  `celery`. Tasks are acknowledged late and re-queued if a worker dies; workers recycle after a
  fixed number of tasks.

## Operator commands

Run from `app/src` with `uv run manage.py <command>`:

| Command | Purpose |
| --- | --- |
| `backfill_extrinsics --lookback N` | Find and fill missing extrinsic blocks between the head and head-N, using the live node for recent blocks and the archive node for older ones |
| `historical_metagraph_backfill --block-start A --block-end B [--netuids ...]` | Long-running walk over a historical range, one epoch-start snapshot at a time, to fill APY history |
| `backfill_burn_metrics --from-block A --to-block B` | Recompute burn and superburn rows from stored snapshots; emission history for such ranges needs an archive node. Dumps from before owners were recorded per block use the current owner as a best-effort stand-in |
| `load_key_labels --hotkeys FILE --coldkeys FILE` | Load human-readable key labels for dashboards |
| `sync_hyperparams [--block N]` | Seed or repair the current hyperparameter values from the chain |
| `replay_notifications BLOCK... [--archive]` | Dry-run the notification pipeline for past blocks: print and log payloads and target channels, post and store nothing |
| `prune_retention` | Run the retention pruning now |
| `acknowledge_snapshot_gap --block N --netuids ...` | Acknowledge one exact missing block; never repairs or fabricates data |

## Local Development Setup

Requirements:

- [docker](https://docs.docker.com)
- [uv](https://docs.astral.sh/uv/)

Run compose
```bash
$ ./setup-dev.sh
$ docker compose up -d
```

The dev database preloads `pg_stat_statements` for the PostgreSQL dashboard.
A fresh volume gets the extension from `db/init/`; an existing volume needs it once, after `docker compose up -d` has recreated the `db` container:
```bash
$ docker compose exec db psql -U postgres -d project -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements'
```

visit app/src
```bash
cd app/src
```

Start celery worker
```bash
uv run celery -A project worker -l INFO -Q celery -E
```

Start abstract block dumper
```bash
uv run manage.py block_tasks_v1
```

End-to-end tests are run against a localnet instance running in a Docker container
```bash
docker compose --profile e2e up -d localnet
nox -s test_e2e
```

**Sentinel mode**

The block scheduler supports four modes controlled by `SENTINEL_MODE` environment variable:

### Live mode (default)

Runs the block scheduler in live mode, processing new blocks as they appear on the chain. This is the default mode used in production for real-time monitoring.

```bash
SENTINEL_MODE=live  # or omit (default)
```

### Backfill mode

Legacy sequential backfill. Processes historical blocks one-by-one with rate limiting. Uses `backfill_blocks_v1` management command which performs full metagraph dumps per block.

```bash
SENTINEL_MODE=backfill

# Required
BLOCK_START=1000000              # Starting block number
BLOCK_END=2000000                # Ending block number
BITTENSOR_ARCHIVE_NETWORK=wss://archive.node.url  # Archive node URI

# Optional
BACKFILL_RATE_LIMIT=0.5          # Seconds between blocks (default: 1.0)
```

### Automatic metagraph gap repair

The `backfill-metagraph` Compose service scans on startup and five minutes after each pass,
repairing missing or unfinished dumps from the archive node. It skips the newest 25 blocks
(~5 minutes) and scans the preceding `METAGRAPH_REPAIR_LOOKBACK` blocks (default 7200, ~24 hours),
starting no earlier than each subnet's first dump. Failed repairs retry on the next pass;
older gaps require manual backfill. Snapshot-health alerts refresh every 72 minutes.

Direct `python manage.py backfill_metagraph` runs remain one-shot with a 300-block safety margin.
Use `--interval SECONDS` for repeat mode and `--settle-blocks N` to change the margin.

### Fast backfill mode

Synchronous lite APY-only backfill. Processes epoch-start blocks directly in the management command using a single WebSocket connection. Uses `--lite` mode (excludes weights/bonds). Good for smaller ranges or debugging.

```bash
SENTINEL_MODE=fast_backfill

# Required
BLOCK_START=1000000              # Starting block number
BLOCK_END=2000000                # Ending block number
BITTENSOR_ARCHIVE_NETWORK=wss://archive.node.url  # Archive node URI

# Optional
NETUID=1                         # Specific subnet (default: all configured netuids)
BACKFILL_STEP=1                  # Block step size (default: 1)
```

### APY backfill mode

Same underlying command as `fast_backfill` but tuned for high-throughput APY backfilling with larger batch sizes and shorter delays between dispatches. Use this when you need to backfill APY data across large block ranges as fast as possible.

```bash
SENTINEL_MODE=apy_backfill

# Required
BLOCK_START=1000000              # Starting block number
BLOCK_END=2000000                # Ending block number
BITTENSOR_ARCHIVE_NETWORK=wss://archive.node.url  # Archive node URI

# Optional
NETUID=1                         # Specific subnet (default: all configured netuids)
BACKFILL_STEP=1                  # Block step size (default: 1)
BACKFILL_BATCH_SIZE=50           # Blocks per Celery task (default: 50)
BACKFILL_BATCH_DELAY=0.5         # Seconds between batch spawns (default: 0.5)
```

Monitor backfill progress with:

```bash
celery -A project inspect active
```

## Grafana dashboard previews

Apply the `grafana-preview` label to a PR targeting `master` to include it in the shared
`staging-grafana` branch. Configure staging Grafana Git Sync to read that branch and
`grafana/dashboards`; production stays on `master`. Set the Actions repository variable
`GRAFANA_PREVIEW_URL` for the staging link, and allow the Action to force-update the generated
branch. Conflicts preserve the previous preview. PR comments confirm branch publication;
verify Grafana has finished importing before reviewing. Never merge `staging-grafana` into `master`.

Test the preview tooling with `python3 -m unittest discover -s scripts/tests -v`
(Python 3.11+, Git 2.38+, Bash, and jq).

## Set up production environment (git deploy)

<details>

This sets up "deployment by pushing to git storage on remote", so that:

- `git push origin ...` just pushes code to Github / other storage without any consequences;
- `git push production master` pushes code to a remote server running the app and triggers a git hook to redeploy the application.

```
Local .git ------------> Origin .git
                \
                 ------> Production .git (redeploy on push)
```

- - -

Use `ssh-keygen` to generate a key pair for the server, then add read-only access to repository in "deployment keys" section (`ssh -A` is easy to use, but not safe).

```sh
# remote server
mkdir -p ~/repos
cd ~/repos
git init --bare --initial-branch=master bittensor_sentinel.git

mkdir -p ~/domains/bittensor_sentinel
```

```sh
# locally
git remote add production root@<server>:~/repos/bittensor_sentinel.git
git push production master
```

```sh
# remote server
cd ~/repos/bittensor_sentinel.git

cat <<'EOT' > hooks/post-receive
#!/bin/bash
unset GIT_INDEX_FILE
export ROOT=/root
export REPO=bittensor_sentinel
while read oldrev newrev ref
do
    if [[ $ref =~ .*/master$ ]]; then
        export GIT_DIR="$ROOT/repos/$REPO.git/"
        export GIT_WORK_TREE="$ROOT/domains/$REPO/"
        git checkout -f master
        cd $GIT_WORK_TREE
        ./deploy.sh
    else
        echo "Doing nothing: only the master branch may be deployed on this server."
    fi
done
EOT

chmod +x hooks/post-receive
./hooks/post-receive
cd ~/domains/bittensor_sentinel
sudo bin/prepare-os.sh
./setup-prod.sh

# adjust the `.env` file

mkdir letsencrypt
./letsencrypt_setup.sh  # or ./selfsign_setup.sh; see "TLS certificates" below
./deploy.sh
```

### Deploy another branch

Only `master` branch is used to redeploy an application.
If one wants to deploy other branch, force may be used to push desired branch to remote's `master`:

```sh
git push --force-with-lease production local-branch-to-deploy:master
```

### Deploy to staging from GitHub Actions

Pushing a commit to the `deploy/staging` branch (`git push --force origin <sha>:deploy/staging`) runs the
"Deploy to staging" workflow: it pushes the commit through the jump host to the staging server, where the
post-receive hook runs `deploy.sh`, and then applies migrations. Its SSH key, hosts, paths and pinned host
keys live in the `staging` GitHub Environment, which only `deploy/staging` may use; the list is at the top
of `.github/workflows/deploy-staging.yml`. Production is still deployed by hand.

### TLS certificates

`nginx/templates/default.conf.template` reads four files, and the `nginx` service bind-mounts `./letsencrypt/etc` into `/etc/letsencrypt` to supply them:

| Path inside the container | Path on the host |
|---|---|
| `/etc/letsencrypt/dhparams/dhparam.pem` | `letsencrypt/etc/dhparams/dhparam.pem` |
| `/etc/letsencrypt/live/$NGINX_HOST/fullchain.pem` | `letsencrypt/etc/live/$NGINX_HOST/fullchain.pem` |
| `/etc/letsencrypt/live/$NGINX_HOST/privkey.pem` | `letsencrypt/etc/live/$NGINX_HOST/privkey.pem` |
| `/etc/letsencrypt/live/$NGINX_HOST/chain.pem` | `letsencrypt/etc/live/$NGINX_HOST/chain.pem` |

**Two scripts produce exactly those four files, so the choice between them changes nothing else in the deployment.** `letsencrypt/` is gitignored, and `NGINX_HOST` must be set in `.env` before either runs: it names the `live/` directory the certificate is written to, and nginx substitutes it into `server_name`.

The monitoring vhost on port `10443` is independent of both. It uses the mutually authenticated pair under `nginx/monitoring_certs/` described in that directory's README, and neither script touches it.

#### Let's Encrypt (default)

`./letsencrypt_setup.sh` issues a publicly trusted certificate through certbot's standalone HTTP-01 challenge. It needs `NGINX_HOST` to resolve publicly to this host with port 80 reachable from the internet, and it binds port 80 itself — so on a deployment that is already serving, stop `nginx` for the duration of the run.

#### Self-signed

`./selfsign_setup.sh` issues a self-signed certificate instead, for deployments where ACME is not an option: no public DNS name, port 80 unreachable, or a host that is internal by design. It needs nothing but Docker and a `NGINX_HOST` value, and it takes the hostname from `.env` the same way, emitting an `IP:` rather than a `DNS:` subject alternative name when that value is an address literal.

```sh
mkdir -p letsencrypt
./selfsign_setup.sh
docker compose up -d --force-recreate nginx
```

Like certbot's `certonly`, it keeps a certificate that is still valid rather than reissuing one, so rerunning the deployment steps will not invalidate the certificate clients were told to trust. Reissue deliberately with `./selfsign_setup.sh --force`. The Diffie-Hellman parameter is generated once and survives a reissue.

Three consequences, none of which apply to the Let's Encrypt path:

- **Every client has to be told to trust it.** Nothing chains to a public root, so each caller needs the certificate in its trust store, `curl --cacert letsencrypt/etc/live/$NGINX_HOST/fullchain.pem`, or verification disabled. The script prints the certificate's SHA-256 fingerprint so that what a client trusts can be checked against what the server actually serves.
- **HSTS makes the switch one-way in a browser.** The main vhost sends `Strict-Transport-Security: max-age=31536000`. A browser that has already reached this hostname over a publicly trusted certificate will refuse to offer a click-through warning for a self-signed one, for up to a year and regardless of what the server now sends. Only a hostname no browser has visited over HTTPS is unaffected.
- **Nothing renews it.** The certificate is valid for ten years and no certbot timer will replace it.

Verify what is being served, from a host that can reach the deployment:

```sh
openssl s_client -connect "$NGINX_HOST:443" -servername "$NGINX_HOST" </dev/null 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates -ext subjectAltName

# succeeds only if the served certificate is the one in this file
curl --cacert "letsencrypt/etc/live/$NGINX_HOST/fullchain.pem" -sSI "https://$NGINX_HOST/"
```

</details>


## Log aggregation

Generate new access credentials for the Loki server.

- Take `<SERVER_GROUP>` from Grafana's `client_server_group` option so logs can be shown automatically in Grafana; for example, `rt_rat`.
- `<ENVIRONMENT>` is usually `prod`.

```sh
uvx cadm exec prometheus -- "cd /home/ubuntu/apps/prometheus-grafana-monitoring/scripts && ./add_loki_target.sh <SERVER_GROUP> <ENVIRONMENT>"
```

Put the generated credentials in the `.env` file's `LOKI_USER` and `LOKI_PASSWORD` fields.

See the [log aggregation configuration](https://github.com/reef-technologies/prometheus-grafana-monitoring?tab=readme-ov-file#adding-log-aggregation-targets) for more details.

With the credentials in place, Alloy also ships the Postgres log, and the
**Postgres Slow Statements** Grafana dashboard lists slow, cancelled and failed
statements with their SQL. See [docs/postgres-slow-statements.md](docs/postgres-slow-statements.md).

## Sentinel Core

Core is a standalone Python package for monitoring the Bittensor blockchain. Located in `app/src/sentinel`.

Core exposes a CLI and programmatic interface for ingesting and analyzing blockchain data.

### CLI Usage

#### View hyperparameters for current block

```bash
uv run sentinel-cli block hyperparameters
```

[Sentinel Core documentation](sentinel/README.md)

## Sentinel Storage

Sentinel storage a pluggable storage system that can be used to store artifacts and data files. Currently it supports
`AWS S3` and `local` filesystem storage backends. These backends are configured with the names `local` and `s3`
respectively, and can be accessed through convenient factory functions.

```python
from project.core.storage import get_local_storage, get_s3_storage

storage = get_local_storage()  # or get_s3_storage() for S3

storage.store("file/path.json", b'{"json": "data"}')
storage.exists("file/path.json")  # True
storage.read("file/path.json")  # b'{"json": "data"}'
storage.delete("file/path.json")
storage.exists("file/path.json")  # False
```

*IMPORTANT*: S3 storage is not fully configured. You need to set `SENTINEL_STORAGE_S3_BUCKET`, and optionally
`SENTINEL_STORAGE_S3_BASE_PATH`, `SENTINEL_STORAGE_S3_AWS_REGION`, `SENTINEL_STORAGE_S3_AWS_ACCESS_KEY_ID`, and
`SENTINEL_STORAGE_S3_AWS_SECRET_ACCESS_KEY` to use it. Otherwise, it'll throw a configuration error at runtime.

### Custom Storages

You can also configure your own storage via Django settings under `SENTINEL_STORAGES` setting like this.

```python
# settings.py

SENTINEL_STORAGES = {
    ...: ...,
    "my-storage": {
        "BACKEND_NAME": "fsspec-local", 
        "OPTIONS": {"base_path": "some/base/path"},
    },
}

# in your code
from project.core.storage import get_storage

my_storage = get_storage("my-storage")

```

`fsspec-local` and `fsspec-s3` storage backends are supported with the following configuration options.

#### 1. `fsspec-local` options

| Option      | Required |
|-------------|----------|
| `base_path` | ✅ Yes    |  

#### 2. `fsspec-s3` options

| Option                  | Required |                
|-------------------------|----------|
| `bucket`                | Yes      |                                                                
| `base_path`             | No       |                        
| `aws_region`            | No       | 
| `aws_access_key_id`     | No       | 
| `aws_secret_access_key` | No       |


## Collector health

Recreate `sync-metagraph` on deployment to apply its progress health check. It automatically
restarts after a 120-second operation timeout or 10 minutes without block progress.

## Tests / CI

First install `nox` as a tool for running tests and other checks:

```sh
# pyyaml is required for nox to read `pyproject.toml`
uv tool install --with pyyaml nox
```

Then run the desired Nox session:

```sh
uvx nox -s lint
uvx nox -s type_check
uvx nox -s test
```

### Run whole stack locally

```bash
$ docker run --rm -p 9944:9944 ghcr.io/opentensor/subtensor:latest-local  \
    --dev --rpc-external --rpc-methods=unsafe --rpc-cors=all --rpc-port=9944 \
    --one --unsafe-force-node-key-generation
```
