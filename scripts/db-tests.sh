#!/usr/bin/env bash
# Run the full pytest suite against the throwaway neo4j-test container.
#
# The main database and neo4j-test never run at the same time, because together
# they exceed a 4 GB Docker VM. This stops the main database, runs the tests,
# then restores it, even if the tests fail.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=".venv/Scripts/python.exe"
[ -x "$PYTHON" ] || PYTHON=".venv/bin/python"

wait_healthy() {
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = "healthy" ] && return 0
    sleep 3
  done
  echo "$1 did not become healthy" >&2
  return 1
}

restore() {
  docker compose --profile test stop neo4j-test >/dev/null
  docker compose up -d neo4j >/dev/null
  wait_healthy fraud-neo4j
}
trap restore EXIT

docker compose stop neo4j >/dev/null
docker compose --profile test up -d neo4j-test >/dev/null
wait_healthy fraud-neo4j-test
(cd backend && "../$PYTHON" -m pytest "$@")
