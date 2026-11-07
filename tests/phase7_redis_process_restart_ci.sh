#!/usr/bin/env bash
# Phase 7.13: real Redis PROCESS restarts in a dedicated disposable CI Docker
# container. Never touch the job's existing redis:6379 service or live data.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE713_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.13 requires GitHub Actions + explicit isolated Redis grant" >&2
  exit 2
fi

name="loomera-phase713-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
volume="${name}-aof"
port=6392

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm -f "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(0.5)
    if sock.connect_ex(("127.0.0.1", 6392)) == 0:
        raise SystemExit("Refusing to replace a service already on port 6392")
PY

# Only this job-specific Docker volume is created. The existing Redis service,
# project database and all other volumes/containers remain untouched.
docker volume create "$volume" >/dev/null
docker run -d --name "$name" \
  --mount "type=volume,source=$volume,target=/data" \
  --publish "127.0.0.1:${port}:6379" \
  redis:7.4-alpine redis-server \
    --protected-mode no \
    --appendonly yes \
    --appendfsync always \
    --save "" >/dev/null

ready() {
  local i
  for ((i=0; i<60; i++)); do
    if docker exec "$name" redis-cli ping 2>/dev/null | grep -qx PONG &&
      python - <<'PY' 2>/dev/null
import redis
c = redis.Redis(host="127.0.0.1", port=6392, db=15,
                socket_timeout=2, socket_connect_timeout=2)
try:
    assert c.ping() is True
    assert c.config_get("appendonly").get("appendonly") == "yes"
    assert c.config_get("appendfsync").get("appendfsync") == "always"
finally:
    c.close()
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "Isolated AOF Redis did not become ready" >&2
  docker logs --tail 60 "$name" >&2 || true
  return 1
}
ready
echo "Phase 7.13: dedicated Redis 7.4 AOF always-fsync container ready on loopback 6392"

# Three independent random synthetic fixture IDs; no actual person, account,
# code, OTP, session ID, phone, IP address or provider is ever stored.
mapfile -t ids < <(python - <<'PY'
from uuid import uuid4
for _ in range(3):
    print(uuid4().hex)
PY
)
export LOOMERA_PHASE713_OBSERVING_ID="${ids[0]}"
export LOOMERA_PHASE713_QUARANTINED_ID="${ids[1]}"
export LOOMERA_PHASE713_HALTED_ID="${ids[2]}"
export PYTHONPATH="$PWD"

# Explicit fixture-only seed privilege exists for FIRST stage and unit tests.
export LOOMERA_PHASE713_ALLOW_TEST_SEED=1
python -m unittest discover -s tests -p 'phase7_aof_restart_fixture_test.py' -v
python tests/phase7_aof_process_restart_drill.py prepare
unset LOOMERA_PHASE713_ALLOW_TEST_SEED

started_before="$(docker inspect --format '{{.State.StartedAt}}' "$name")"
echo "Phase 7.13: real graceful docker stop followed by start"
docker stop --time 15 "$name" >/dev/null
docker start "$name" >/dev/null
ready
started_after="$(docker inspect --format '{{.State.StartedAt}}' "$name")"
if [[ "$started_before" == "$started_after" ]]; then
  echo "The Redis process did not restart after graceful stop" >&2
  exit 1
fi
python tests/phase7_aof_process_restart_drill.py after-graceful

started_before="$started_after"
echo "Phase 7.13: real SIGKILL of Redis process followed by start"
docker kill --signal KILL "$name" >/dev/null
docker start "$name" >/dev/null
ready
started_after="$(docker inspect --format '{{.State.StartedAt}}' "$name")"
if [[ "$started_before" == "$started_after" ]]; then
  echo "The Redis process did not restart after SIGKILL" >&2
  exit 1
fi
python tests/phase7_aof_process_restart_drill.py after-sigkill

echo "Phase 7.13 isolated Redis AOF graceful + SIGKILL restart rehearsal PASSED"
# The EXIT trap removes ONLY this ephemeral test container and named volume.
