# Prod log volume

## Why logs are quiet by default

`bittensor >= 11` logs every JSON-RPC frame at DEBUG under
`bittensor.transport.raw_websocket`, including multi-KB hex extrinsic blobs. Prod
runs `LOG_LEVEL=DEBUG`, so those frames were 96-99% of container log bytes —
about 3 GiB/day on the 38G root filesystem. It filled `/` twice:

- 2026-09-23: 94% full, reclaimed by hand.
- 2026-09-29: 100% full. Redis keeps its AOF on `/`, so it answered `MISCONF`,
  both Celery nodes died with "Unrecoverable error", and `/metrics` returned 500.

Two settings keep it from happening again:

- `BITTENSOR_LOG_LEVEL` (default `WARNING`) pins the whole `bittensor` logger
  tree in `LOGGING["loggers"]`, independent of `LOG_LEVEL`.
- `ForwardToSyslog=no` in `/etc/systemd/journald.conf.d/syslog.conf` stops
  journald writing a second, uncapped copy of every container line to
  `/var/log/syslog`. journald itself is capped at `SystemMaxUse=2G`, so a future
  noisy logger can no longer fill the disk, whatever its name.

`app/src/tests/core/test_logging_config.py` fails if the mute is dropped or the
bittensor frame logger is renamed again.

## Applying the host setting

`bin/prepare-os.sh` writes two journald drop-ins on a fresh box: `99-limits.conf`
(size cap) and `syslog.conf` (no forwarding). The second must be named
`syslog.conf`: Ubuntu turns forwarding on in
`/usr/lib/systemd/journald.conf.d/syslog.conf`, drop-ins apply in filename order,
and a same-named file in `/etc` masks the vendor one. On an existing box,
install just those two files from `bin/prepare-os.sh`, then:

    systemctl restart systemd-journald
    systemd-analyze cat-config systemd/journald.conf | grep -E "ForwardToSyslog|SystemMaxUse"

Verify with `stat -c %s /var/log/syslog` a minute apart: it should only grow by
the few hundred bytes of non-journald host logging.

## Reading prod logs

`docker logs` reaches back only as far as journald keeps. Alloy ships to
`loki.reef.pl` from `docker.sock`, independently of journald and rsyslog; query
it with the `LOKI_READER_*` credentials in `/root/domains/bittensor_sentinel/.env`.

## Debugging the chain transport

To see frames again for one session, set `BITTENSOR_LOG_LEVEL=DEBUG` in the
prod `.env` and recreate only the service you are debugging:

    docker compose up -d sync-extrinsics

Set it back to `WARNING` as soon as you are done.

## If the disk fills anyway

    df -h /
    du -sh /var/log/* | sort -hr | head

`truncate -s 0 /var/log/syslog` rather than `rm` — rsyslog holds the descriptor
open and unlinking leaks the space until it restarts. Rotated files
(`syslog.1`, `*.gz`) are closed and can be removed. After freeing space, check
`redis-cli INFO persistence` shows `aof_last_write_status:ok` and restart
`celery-worker` if its nodes died while Redis was refusing writes.
