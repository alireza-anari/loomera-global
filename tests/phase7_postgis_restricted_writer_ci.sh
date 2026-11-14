#!/usr/bin/env bash
# Phase 7.28 - disposable PostGIS + Redis fixture, NEVER a live OTP gateway.
set -Eeuo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE728_TEST_REDIS:-}" != "1" ||
      "${LOOMERA_PHASE729_TEST_OUTBOX:-}" != "1" ||
      "${LOOMERA_PHASE730_TEST_REVIEW:-}" != "1" ||
      "${LOOMERA_PHASE726_TEST_POSTGIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.28-7.30 requires all isolated GitHub CI grants" >&2
  exit 2
fi
if [[ ! "$GITHUB_RUN_ID" =~ ^[0-9]+$ ||
      ! "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]; then
  echo "Phase 7.28 rejects nonnumeric run identity" >&2
  exit 2
fi

name="loomera-p728-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
volume="${name}-aof"
owned_volume=0
owned_container=0
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
if docker container inspect "$name" >/dev/null 2>&1; then
  echo "Phase 7.28 refuses existing container" >&2
  exit 2
fi
if docker volume inspect "$volume" >/dev/null 2>&1; then
  echo "Phase 7.28 refuses existing volume" >&2
  exit 2
fi
python - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(0.5)
    if sock.connect_ex(("127.0.0.1", 6428)) == 0:
        raise SystemExit("Phase 7.28 isolated 6428 already occupied")
PY

docker volume create "$volume" >/dev/null
owned_volume=1
docker run -d --name "$name" \
  --label loomera.phase728=synthetic-restricted-gateway-only \
  --mount "type=volume,source=$volume,target=/data" \
  --publish 127.0.0.1:6428:6379 \
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
  echo "Phase 7.28 synthetic Redis did not start" >&2
  exit 1
fi

mapfile -t generated < <(python - <<'PY'
from uuid import uuid4
for _ in range(5):
    print(uuid4().hex)
PY
)
if ((${#generated[@]} != 5)); then
  echo "Phase 7.28 failed to generate isolated credentials" >&2
  exit 1
fi
export LOOMERA_PHASE728_ID="${generated[0]}"
export LOOMERA_PHASE728_ADMIN_PASS="${generated[1]}"
export LOOMERA_PHASE728_GATEWAY_PASS="${generated[2]}"
export LOOMERA_PHASE728_LEGACY_PASS="${generated[3]}"
export LOOMERA_PHASE728_REVOKE_PASS="${generated[4]}"
unset generated

python manage.py test apps.accounts.test_phase7_postgis_mandatory_ingress \
  --failfast --noinput
echo "Phase 7.28-7.30 physical Redis gate, SQL-first outbox and readonly cross-store review PASSED"
