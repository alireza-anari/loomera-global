#!/usr/bin/env bash
# Phase 7.22: physical isolated Redis multi-key OTP issue/rate/cooldown CAS.
# CI only; never real OTP, customer accounts, sessions or Production cache.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE722_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" ||
      -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.22 requires explicit disposable GitHub CI grant" >&2
  exit 2
fi

base="loomera-p722-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
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
with socket.socket() as sock:
    sock.settimeout(0.5)
    if sock.connect_ex(("127.0.0.1", 6414)) == 0:
        raise SystemExit("refusing occupied isolated 127.0.0.1:6414")
PY

docker network create --driver bridge "$bridge" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$redis_container" --network "$bridge" \
  --mount "type=volume,source=$volume,target=/data" \
  --label loomera.phase723=synthetic \
  --label loomera.phase724=idempotency-test \
  --publish 127.0.0.1:6414:6379 \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always --save "" >/dev/null

ready=0
for ((i=0;i<80;i++)); do
  if docker exec "$redis_container" redis-cli PING 2>/dev/null | grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.25
done
if ((ready != 1)); then
  echo "Phase 7.22 isolated Redis did not become ready" >&2
  exit 1
fi

export PYTHONPATH="$PWD"
python tests/phase7_legacy_issue_rate_test.py -v

# Phase 7.23 MUST run on the *same* isolated physical Redis as Phase 7.22,
# before the EXIT cleanup trap; no second port or shared production cache.
export LOOMERA_PHASE723_TEST_REDIS="1"
export LOOMERA_PHASE723_CONTAINER="$redis_container"
python tests/phase7_legacy_integrated_recovery_test.py -v

# Phase 7.24 reuses the SAME physical AOF master and exact prior
# isolated fixture namespace while the EXIT trap owns all resources.
export LOOMERA_PHASE724_TEST_REDIS="1"
export LOOMERA_PHASE724_CONTAINER="$redis_container"
python tests/phase7_legacy_idempotency_test.py -v

echo "Phases 7.22-7.24 real synthetic issuer/verify/idempotency/AOF CI PASSED"
