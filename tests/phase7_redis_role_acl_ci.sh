#!/usr/bin/env bash
# Phase 7.33 - standalone, disposable Redis 7.4 ACL fixture. NEVER live Redis.
set -Eeuo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE733_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ||
      ! "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ||
      ! "${GITHUB_RUN_ATTEMPT:-}" =~ ^[0-9]+$ ]]; then
  echo "Phase 7.33 requires explicit isolated CI grants" >&2
  exit 2
fi

name="loomera-p733-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
owned=0
cleanup() {
  if ((owned)); then docker rm -f "$name" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
docker info >/dev/null
if docker container inspect "$name" >/dev/null 2>&1; then
  echo "Phase 7.33 refuses preexisting container" >&2
  exit 2
fi
python - <<'PY'
import socket
with socket.socket() as s:
    s.settimeout(0.5)
    if s.connect_ex(("127.0.0.1", 6433)) == 0:
        raise SystemExit("Phase 7.33 refuses occupied 127.0.0.1:6433")
PY
# No persisted volume, host aliases or external port.
docker run -d --name "$name" \
  --label loomera.phase733=disposable-acl-test-only \
  --publish 127.0.0.1:6433:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
  --appendonly no --save "" >/dev/null
owned=1
ready=0
for ((attempt=0;attempt<80;attempt++)); do
  if docker exec "$name" redis-cli PING 2>/dev/null | grep -qx PONG; then
    ready=1
    break
  fi
  sleep 0.25
done
if ((ready != 1)); then
  echo "Phase 7.33 disposable Redis did not start" >&2
  exit 1
fi
mapfile -t generated < <(python - <<'PY'
from uuid import uuid4
for _ in range(7):
    print(uuid4().hex)
PY
)
if (("${#generated[@]}" != 7)); then
  echo "Phase 7.33 random fixture generation failed" >&2
  exit 1
fi
export LOOMERA_PHASE733_ID="${generated[0]}"
export LOOMERA_PHASE733_ADMIN_PASS="${generated[1]}"
export LOOMERA_PHASE733_GENERAL_PASS="${generated[2]}"
export LOOMERA_PHASE733_OTP_PASS="${generated[3]}"
export LOOMERA_PHASE733_BROKER_PASS="${generated[4]}"
export LOOMERA_PHASE733_RESULT_PASS="${generated[5]}"
export LOOMERA_PHASE733_OVERBROAD_PASS="${generated[6]}"
unset generated
python -m unittest discover -s tests -p 'phase7_redis_role_acl_test.py' -v
echo "Phase 7.33 disposable named ACL isolation and overbroad counterexample passed"
