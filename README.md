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

```
# Starting block number (required for backfill)
BLOCK_START=1000000
# Ending block number (required for backfill)
BLOCK_END=2000000
# Seconds between blocks in backfill mode
BACKFILL_RATE_LIMIT=0.5
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
