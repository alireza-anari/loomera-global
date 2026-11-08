#!/usr/bin/env bash
# Phase 7.27: real PostGIS test DB against disposable raw Redis 7.4 ingress.
# No Production data/services. No in-place GitHub Redis job modifications.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE727_TEST_REDIS:-}" != "1" ||
      "${LOOMERA_PHASE726_TEST_POSTGIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.27 requires both isolated GitHub CI grants" >&2
  exit 2
fi
if [[ ! "$GITHUB_RUN_ID" =~ ^[0-9]+$ || ! "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]; then
  echo "Phase 7.27 rejects non-numeric CI run identity" >&2
  exit 2
fi
name="loomera-p727-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
volume="${name}-aof"
owned_container=0
owned_volume=0
cleanup() {
  if ((owned_container)); then
    docker rm -f "$name" >/dev/null 2>&1 || true
  fi
  if ((owned_volume)); then
    docker volume rm "$volume" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker info >/dev/null
# NEVER commandeer a pre-existing container, volume, or occupied port.
if docker container inspect "$name" >/dev/null 2>&1; then
  echo "Phase 7.27 disposable container unexpectedly exists" >&2
  exit 2
fi
if docker volume inspect "$volume" >/dev/null 2>&1; then
  echo "Phase 7.27 disposable volume unexpectedly exists" >&2
  exit 2
fi
python - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(0.5)
    if sock.connect_ex(("127.0.0.1", 6427)) == 0:
        raise SystemExit("refuse occupied Phase 7.27 loopback port 6427")
PY

docker volume create "$volume" >/dev/null
owned_volume=1
docker run -d --name "$name" \
  --label loomera.phase727=synthetic-pg-redis-only \
  --mount "type=volume,source=$volume,target=/data" \
  --publish 127.0.0.1:6427:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
  --appendonly yes --appendfsync always --save "" >/dev/null
owned_container=1

ready=0
for ((attempt=0; attempt<80; attempt++)); do
  if docker exec "$name" redis-cli -n 15 PING 2>/dev/null |
      grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.3
done
if ((ready != 1)); then
  echo "Phase 7.27 disposable Redis did not start" >&2
  exit 1
fi
mapfile -t generated < <(python - <<'PY'
from uuid import uuid4
for _ in range(4):
    print(uuid4().hex)
PY
)
if ((${#generated[@]} != 4)); then
  echo "Phase 7.27 random fixture generation failed" >&2
  exit 1
fi
export LOOMERA_PHASE727_ID="${generated[0]}"
export LOOMERA_PHASE727_ADMIN_PASS="${generated[1]}"
export LOOMERA_PHASE727_STALE_PASS="${generated[2]}"
export LOOMERA_PHASE727_PROMOTED_PASS="${generated[3]}"
unset generated

# Real Django PostGIS TransactionTestCase and real independent Redis sockets.
# This test must fail on PostgreSQL errors, ACL bypass, or non-isolated targets.
python manage.py test apps.accounts.test_phase7_postgis_redis_ingress --failfast --noinput
echo "Phase 7.27 real PostGIS x raw Redis negative-proof tests passed"
