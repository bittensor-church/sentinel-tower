# These exporter releases still ship old public roots. Keep their runtime behavior
# and users, replacing only the CA bundle until upstream ships fixed images.
FROM alpine:3.24 AS certificates
RUN apk add --no-cache 'ca-certificates>=20261020-r0'

FROM ghcr.io/google/cadvisor:v0.60.5 AS cadvisor
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

FROM prom/node-exporter:v1.12.1 AS node-exporter
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

FROM prometheuscommunity/postgres-exporter:v0.20.1 AS postgres-exporter
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
