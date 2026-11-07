#!/usr/bin/env bash
# Phase 7.18: actual two-node Redis AOF split-brain and local ACL boundaries.
set -Eeuo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE718_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.18 requires GitHub CI disposable grant" >&2
  exit 2
fi
base="loomera-p718-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
old="${base}-old"; new="${base}-new"
client_net="${base}-client"; repl_net="${base}-replication"
old_vol="${base}-old-aof"; new_vol="${base}-new-aof"
cleanup() {
  docker rm -f "$old" "$new" >/dev/null 2>&1 || true
  docker volume rm -f "$old_vol" "$new_vol" >/dev/null 2>&1 || true
  docker network rm "$repl_net" "$client_net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker info >/dev/null
python - <<'PY'
import socket
for port in (6408, 6409):
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("refusing occupied isolated port " + str(port))
PY
docker network create --driver bridge "$client_net" >/dev/null
docker network create --driver bridge "$repl_net" >/dev/null
docker volume create "$old_vol" >/dev/null
docker volume create "$new_vol" >/dev/null
docker run -d --name "$old" --network "$client_net" \
  --mount "type=volume,source=$old_vol,target=/data" \
  --publish 127.0.0.1:6408:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --save "" >/dev/null
docker run -d --name "$new" --network "$client_net" \
  --mount "type=volume,source=$new_vol,target=/data" \
  --publish 127.0.0.1:6409:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --replica-read-only yes \
    --repl-ping-replica-period 2 --repl-timeout 8 --save "" >/dev/null
docker network connect --alias p718-old "$repl_net" "$old"
docker network connect --alias p718-new "$repl_net" "$new"
ready() {
  local c="$1" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$c" redis-cli PING 2>/dev/null | grep -qx PONG; then
      return 0
    fi
    sleep 0.3
  done
  echo "Phase 7.18 isolated Redis unavailable: $c" >&2
  return 1
}
role() {
  local c="$1" wanted="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$c" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${wanted}"; then return 0; fi
    sleep 0.3
  done
  echo "Phase 7.18 role $wanted not seen: $c" >&2
  return 1
}
ready "$old"
ready "$new"
docker exec "$new" redis-cli REPLICAOF p718-old 6379 | grep -q '^OK'
role "$old" master
role "$new" slave
# REPLICAOF returning OK and role=slave do not prove link readiness.
# Require the actual upstream connection before seeding / WAIT 1.
link_ok=0
for ((attempt=0; attempt<80; attempt++)); do
  if docker exec "$new" redis-cli INFO replication 2>/dev/null |
     grep -q '^master_link_status:up'; then
    link_ok=1
    break
  fi
  sleep 0.35
done
if ((link_ok != 1)); then
  echo "Phase 7.18 replica link never became ready" >&2
  exit 1
fi
mapfile -t secrets < <(python - <<'PY'
from uuid import uuid4
for _ in range(4):
    print(uuid4().hex)
PY
)
export LOOMERA_PHASE718_ID="${secrets[0]}"
export LOOMERA_PHASE718_ADMIN_PASS="${secrets[1]}"
export LOOMERA_PHASE718_STALE_PASS="${secrets[2]}"
export LOOMERA_PHASE718_READ_PASS="${secrets[3]}"
export PYTHONPATH="$PWD"
python tests/phase7_acl_partition_drill.py seed
docker network disconnect "$repl_net" "$new"
docker exec "$new" redis-cli CLIENT KILL TYPE MASTER >/dev/null
docker exec "$new" redis-cli REPLICAOF NO ONE | grep -q '^OK'
role "$old" master
role "$new" master
python tests/phase7_acl_partition_drill.py partition
python tests/phase7_acl_partition_drill.py revoke-old
echo "Phase 7.18 isolated ACL stale writer and local revocation test PASSED"
