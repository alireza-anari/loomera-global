#!/usr/bin/env bash
# Phase 7.20: actual django-redis 5.4 pickled STRING WATCH/MULTI single-winner.
# New loopback-only Redis 7.4 container and network, NEVER real user cache.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE720_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" ||
      -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.20 requires explicit disposable GitHub Actions grant" >&2
  exit 2
fi

base="loomera-p720-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
container="${base}-redis"
network="${base}-bridge"
volume="${base}-aof"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm -f "$volume" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(0.5)
    if sock.connect_ex(("127.0.0.1", 6412)) == 0:
        raise SystemExit("refusing occupied isolated 127.0.0.1:6412")
PY

docker network create --driver bridge "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$container" --network "$network" \
  --mount "type=volume,source=$volume,target=/data" \
  --publish 127.0.0.1:6412:6379 \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always --save "" >/dev/null

ready=0
for ((attempt=0;attempt<80;attempt++)); do
  if docker exec "$container" redis-cli PING 2>/dev/null | grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.25
done
if ((ready != 1)); then
  echo "Phase 7.20 isolated Redis 7.4 unavailable" >&2
  exit 1
fi

export PYTHONPATH="$PWD"
python tests/phase7_legacy_watch_candidate_test.py -v

echo "Phase 7.20 real serialized legacy OTP WATCH preflight PASSED (test-only)"
