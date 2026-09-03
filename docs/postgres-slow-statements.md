# Postgres Slow Statements dashboard

Slow, cancelled and failed Postgres statements with their SQL, for any
selected time range. Provisioned from
[`grafana/provisioning/dashboards/postgres-slow-statements.json`](../grafana/provisioning/dashboards/postgres-slow-statements.json),
reachable at `/grafana/d/postgres-slow-statements/`.

It fills the two gaps the other performance dashboards leave:
`pg_stat_statements` (DB Query Performance) is cumulative since its last reset
and never sees a statement that was cancelled, and Grafana's own metrics
(Grafana Query Timing) carry no query text at all.

## Where the data comes from

Postgres writes to its log every statement slower than
`log_min_duration_statement` (2 s on prod) with its duration and full SQL,
and every failed or cancelled statement as an `ERROR` line followed by a
`STATEMENT` line with the SQL. A statement spans several lines: the first
carries the `log_line_prefix`, the rest are tab-indented.

[`alloy/config.alloy`](../alloy/config.alloy) ships every container's log to
the central Loki (`https://loki.reef.pl`). For the db container it joins the
continuation lines into the entry that started them (`stage.multiline`), so
each slow statement and each `STATEMENT` line arrives as one entry with its
whole SQL.

Grafana reads them back through the provisioned `Loki` data source, which
uses the same `LOKI_URL`, `LOKI_USER` and `LOKI_PASSWORD` values Alloy uses.

## Credentials

Nothing is shipped and the data source cannot query until the three `LOKI_*`
values are set in `.env`. Credentials for the central Loki are created on the
monitoring server, one pair per server group and environment, as described in
the README under "Log aggregation":

```sh
uvx cadm exec prometheus_and_grafana -- "cd /home/ubuntu/apps/prometheus-grafana-monitoring/scripts && ./add_loki_target.sh <SERVER_GROUP> <ENVIRONMENT>"
```

The script prints the username and password to put into `LOKI_USER` and
`LOKI_PASSWORD`. After changing `.env`, restart `alloy` and `grafana`: both
read their configuration at start.

## Reading it

- The tiles count completed slow statements and cancelled statements in the
  selected range and show the longest and the total time spent.
- The two charts bucket slow statements by duration band and show
  cancellations over time.
- "Slow statements, longest first" is the list: time, duration and SQL, up to
  1000 entries per query. Click a cell to expand the SQL.
- "Errored and cancelled statements" shows `ERROR` lines and the `STATEMENT`
  lines Postgres writes right after them, newest first. A cancellation by a
  client that gave up reads "canceling statement due to user request".
- Statements faster than the log threshold never appear here; use DB Query
  Performance for those.
