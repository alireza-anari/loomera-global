#!/usr/bin/env bash
# Phase 7.25: physical dual-master Redis AOF idempotency/failover counterexample.
# All infrastructure and records disposable, synthetic GitHub CI ONLY.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE725_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" ||
      -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.25 requires an explicit disposable GitHub CI grant" >&2
  exit 2
fi

base="loomera-p725-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
old="${base}-old"
promoted="${base}-promoted"
writer="${base}-writer"
bypass_net="${base}-bypass"
client_net="${base}-client"
repl_net="${base}-replication"
old_vol="${base}-old-aof"
promoted_vol="${base}-promoted-aof"

cleanup() {
  docker rm -f "$writer" "$promoted" "$old" >/dev/null 2>&1 || true
  docker volume rm -f "$old_vol" "$promoted_vol" >/dev/null 2>&1 || true
  docker network rm "$repl_net" "$client_net" "$bypass_net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
for port in (6415, 6416):
    with socket.socket() as s:
        s.settimeout(.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("refuse occupied Phase7.25 localhost port " + str(port))
PY

docker network create --driver bridge "$bypass_net" >/dev/null
docker network create --driver bridge "$client_net" >/dev/null
docker network create --driver bridge "$repl_net" >/dev/null
docker volume create "$old_vol" >/dev/null
docker volume create "$promoted_vol" >/dev/null

# Host-accessible localhost port uses BYPASS network, not the client bridge.
# The client bridge can be severed while host raw Redis access still exists.
docker run -d --name "$old" --network "$bypass_net" \
  --mount "type=volume,source=$old_vol,target=/data" \
  --label loomera.phase725=synthetic-old \
  --publish 127.0.0.1:6415:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --save "" >/dev/null
docker run -d --name "$promoted" --network "$bypass_net" \
  --mount "type=volume,source=$promoted_vol,target=/data" \
  --label loomera.phase725=synthetic-promoted \
  --publish 127.0.0.1:6416:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --replica-read-only yes \
    --repl-ping-replica-period 2 --repl-timeout 8 --save "" >/dev/null

docker network connect --alias p725-old-client "$client_net" "$old"
docker network connect --alias p725-new-client "$client_net" "$promoted"
docker network connect --alias p725-old-repl "$repl_net" "$old"
docker network connect --alias p725-new-repl "$repl_net" "$promoted"
docker run -d --name "$writer" --network "$client_net" \
  redis:7.4-alpine sh -c 'sleep 600' >/dev/null

ready() {
  local c="$1" i
  for ((i=0;i<90;i++)); do
    if docker exec "$c" redis-cli PING 2>/dev/null | grep -qx PONG; then
      return 0
    fi
    sleep .3
  done
  echo "Phase7.25 disposable Redis not ready: $c" >&2
  return 1
}
role() {
  local c="$1" expected="$2" i
  for ((i=0;i<90;i++)); do
    if docker exec "$c" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${expected}"; then
      return 0
    fi
    sleep .3
  done
  echo "Phase7.25 expected role $expected not observed: $c" >&2
  return 1
}
link_state() {
  local c="$1" expected="$2" i
  for ((i=0;i<90;i++)); do
    if docker exec "$c" redis-cli INFO replication 2>/dev/null |
       grep -q "^master_link_status:${expected}"; then
      return 0
    fi
    sleep .3
  done
  echo "Phase7.25 expected replication link $expected not observed: $c" >&2
  return 1
}

ready "$old"
ready "$promoted"
docker exec "$writer" sh -c 'true' >/dev/null
docker exec "$promoted" redis-cli REPLICAOF p725-old-repl 6379 | grep -q '^OK'
role "$old" master
role "$promoted" slave
link_state "$promoted" up

export LOOMERA_PHASE725_ID="$(python - <<'PY'
from uuid import uuid4
print(uuid4().hex)
PY
)"
export PYTHONPATH="$PWD"
python tests/phase7_idempotency_failover_drill.py seed

echo "Phase7.25 PHYSICAL separation: remove replication bridge from replica"
docker network disconnect "$repl_net" "$promoted"
docker exec "$promoted" redis-cli CLIENT KILL TYPE MASTER >/dev/null
link_state "$promoted" down
docker exec "$promoted" redis-cli REPLICAOF NO ONE | grep -q '^OK'
role "$old" master
role "$promoted" master
python tests/phase7_idempotency_failover_drill.py partition

# Physically fence only one CLIENT interface, while retaining a separate
# bypass interface; verify DNS and previous client IPv4 both cannot write.
old_client_ip="$(docker inspect "$old" --format '{{json .NetworkSettings.Networks}}' |
  python -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]]["IPAddress"])' "$client_net")"
python - "$old_client_ip" <<'PY'
import ipaddress, sys
assert ipaddress.ip_address(sys.argv[1]).version == 4
PY
docker network disconnect "$client_net" "$old"
role "$old" master
role "$promoted" master
guard_key="loomera:phase725:synthetic-two-master-only:${LOOMERA_PHASE725_ID}:1:phase725:test-disallowed-client"
for target in p725-old-client "$old_client_ip"; do
  if timeout 8s docker exec "$writer" redis-cli --raw \
      -h "$target" -p 6379 -n 15 \
      EVAL "return redis.call('SET', KEYS[1], ARGV[1], 'EX', 3900)" 1 \
      "$guard_key" "must-never-commit" >/dev/null 2>&1; then
    echo "SECURITY FAIL: old Redis still writable through severed client route: $target" >&2
    exit 1
  fi
done
python tests/phase7_idempotency_failover_drill.py host-bypass

# Check exact labels and exact run-id-bound container names *before* any
# physical stop/start operation. Never stop arbitrary Docker resources.
if [[ "$(docker inspect --format '{{ index .Config.Labels "loomera.phase725" }}' "$old")" != "synthetic-old" ||
      "$(docker inspect --format '{{ index .Config.Labels "loomera.phase725" }}' "$promoted")" != "synthetic-promoted" ]]; then
  echo "Phase7.25 unexpected disposable container labels" >&2
  exit 1
fi
docker stop "$old" "$promoted" >/dev/null
docker start "$old" "$promoted" >/dev/null
ready "$old"
ready "$promoted"
role "$old" master
role "$promoted" master
python tests/phase7_idempotency_failover_drill.py after-restart

echo "Phase7.25 DONE: raw old-master bypass, lost replica ledger, TWO local same-ID commits, AOF divergence; PRODUCTION BLOCKED"
