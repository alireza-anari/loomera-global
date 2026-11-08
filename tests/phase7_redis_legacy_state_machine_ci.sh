#!/usr/bin/env bash
# Phase 7.21 single-node per-record WATCH state machine on actual legacy wire.
# Only synthetic fixtures; fixed new loopback port, dedicated Docker resources.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE721_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" ||
      -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.21 requires explicit disposable GitHub CI grant" >&2
  exit 2
fi

base="loomera-p721-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
redis_container="${base}-redis"
bridge="${base}-bridge"
volume="${base}-aof"

cleanup() {
  docker rm -f "$redis_container" >/dev/null 2>&1 || true
  docker volume rm -f "$volume" >/dev/null 2>&1 || true
  docker network rm "$bridge" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
with socket.socket() as s:
    s.settimeout(0.5)
    if s.connect_ex(("127.0.0.1", 6413)) == 0:
        raise SystemExit("refusing occupied 127.0.0.1:6413")
PY

docker network create --driver bridge "$bridge" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$redis_container" --network "$bridge" \
  --mount "type=volume,source=$volume,target=/data" \
  --publish 127.0.0.1:6413:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --save "" >/dev/null

ready=0
for ((i=0;i<80;i++)); do
  if docker exec "$redis_container" redis-cli PING 2>/dev/null | grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.25
done
if ((ready != 1)); then
  echo "Phase 7.21 isolated Redis 7.4 not ready" >&2
  exit 1
fi

export PYTHONPATH="$PWD"
python tests/phase7_legacy_state_machine_test.py -v

echo "Phase 7.21 DONE: real Django-Redis WRONG/CORRECT/EXHAUSTED CAS (test-only)"
