#!/usr/bin/env bash
# Saves all the data that the deployed API needs, so a deployment does not need a new crawl:
#   data/snapshots/dump.rdb              the FalkorDB graph (BGSAVE)
#   data/snapshots/fallout-data.tar.gz   crawl resolutions and versions, demo repo checkouts
# To restore on the target: tar -xzf data/snapshots/fallout-data.tar.gz, then docker compose up.
set -euo pipefail
cd "$(dirname "$0")/.."
CONTAINER="${FALKORDB_CONTAINER:-fallout-falkordb}"
mkdir -p data/snapshots

before=$(docker exec "$CONTAINER" redis-cli LASTSAVE)
docker exec "$CONTAINER" redis-cli BGSAVE >/dev/null
until [ "$(docker exec "$CONTAINER" redis-cli LASTSAVE)" != "$before" ]; do sleep 0.5; done
dir=$(docker exec "$CONTAINER" redis-cli CONFIG GET dir | tail -1)
docker cp "$CONTAINER:$dir/dump.rdb" data/snapshots/dump.rdb

tar -czf data/snapshots/fallout-data.tar.gz \
  data/raw/crawl/resolutions.jsonl data/raw/crawl/versions.jsonl data/raw/repos
ls -lh data/snapshots/
