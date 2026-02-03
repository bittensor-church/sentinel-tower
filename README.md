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

## Local Development Setup

To set up the development environment using Docker Compose, run the following commands in your terminal:

Run compose
```bash
$ ./setup-dev.sh
$ docker compose up -d
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

**Sentinel mode**

The block scheduler supports three modes controlled by `SENTINEL_MODE` environment variable:

### Live mode (default)

Runs the block scheduler in live mode, processing new blocks as they appear on the chain.

```bash
SENTINEL_MODE=live  # or omit (default)
```

### Backfill mode

Backfills historical blocks sequentially with rate limiting.

```bash
SENTINEL_MODE=backfill

# Required
BLOCK_START=1000000              # Starting block number
BLOCK_END=2000000                # Ending block number
BITTENSOR_ARCHIVE_NETWORK=wss://archive.node.url  # Archive node URI

# Optional
BACKFILL_RATE_LIMIT=0.5          # Seconds between blocks (default: 1.0)
```

### Fast backfill mode

Fast backfilling using Celery for parallel processing. Recommended for large block ranges.

```bash
SENTINEL_MODE=fast_backfill

# Required
BLOCK_START=1000000              # Starting block number
BLOCK_END=2000000                # Ending block number
BITTENSOR_ARCHIVE_NETWORK=wss://archive.node.url  # Archive node URI

# Optional
NETUID=1                         # Specific subnet (default: all configured netuids)
BACKFILL_STEP=1                  # Block step size (default: 1)
BACKFILL_BATCH_SIZE=10           # Blocks per Celery task (default: 10)
BACKFILL_BATCH_DELAY=1.0         # Seconds between batch spawns (default: 1.0)
STORE_ARTIFACT=false             # Store JSONL artifacts (default: false)
```

Fast backfill uses batch processing - each Celery task processes multiple blocks using a single WebSocket connection, significantly reducing connection overhead. Monitor progress with:

```bash
celery -A project inspect active
```

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
