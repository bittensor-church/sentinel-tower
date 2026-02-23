FROM newrelic/infrastructure:latest
# License key is NOT baked in — it is supplied at runtime via the
# NRIA_LICENSE_KEY environment variable (mapped from NEW_RELIC_LICENSE_KEY
# in .env by docker-compose).
