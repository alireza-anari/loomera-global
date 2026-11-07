#!/usr/bin/env bash
# Phase 7.14 — TWO real, isolated Redis 7.4 Docker processes. Manual replica
# promotion only: NO Sentinel/Cluster, no durable witness, no production.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE714_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.14 requires GitHub Actions + isolated test grant" >&2
  exit 2
fi

base="loomera-p714-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
primary="${base}-primary"
replica="${base}-replica"
network="${base}-net"
primary_volume="${base}-primary-aof"
replica_volume="${base}-replica-aof"

cleanup() {
  docker rm -f "$primary" "$replica" >/dev/null 2>&1 || true
  docker volume rm -f "$primary_volume" "$replica_volume" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
for port in (6393, 6394):
    with socket.socket() as s:
        s.settimeout(0.6)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Refuse to touch already-bound port {port}")
PY

docker network create --driver bridge "$network" >/dev/null
docker volume create "$primary_volume" >/dev/null
docker volume create "$replica_volume" >/dev/null

# Containers share an ephemeral private bridge but have separate AOF volumes.
# Published ports are loopback only. NEVER address the existing Redis 6379.
docker run -d --name "$primary" \
  --network "$network" \
  --mount "type=volume,source=$primary_volume,target=/data" \
  --publish "127.0.0.1:6393:6379" \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always \
    --save "" >/dev/null

docker run -d --name "$replica" \
  --network "$network" \
  --mount "type=volume,source=$replica_volume,target=/data" \
  --publish "127.0.0.1:6394:6379" \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always \
    --replica-read-only yes --save "" >/dev/null

ready() {
  local container="$1" port="$2" attempt
  for ((attempt=0; attempt<70; attempt++)); do
    if docker exec "$container" redis-cli ping 2>/dev/null | grep -qx PONG &&
      python - "$port" <<'PY' 2>/dev/null
import redis
import sys
port = int(sys.argv[1])
client = redis.Redis(host="127.0.0.1", port=port, db=15,
                     socket_timeout=2, socket_connect_timeout=2)
try:
    assert client.ping() is True
    assert client.config_get("appendonly").get("appendonly") == "yes"
    assert client.config_get("appendfsync").get("appendfsync") == "always"
finally:
    client.close()
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "Redis container not ready: $container (port $port)" >&2
  docker logs --tail 40 "$container" >&2 || true
  return 1
}

role_is() {
  local container="$1" role="$2" attempt
  for ((attempt=0; attempt<70; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${role}"; then
      return 0
    fi
    sleep 0.3
  done
  echo "Redis did not enter required role $role: $container" >&2
  docker logs --tail 50 "$container" >&2 || true
  return 1
}

replica_link_up() {
  local container="$1" attempt
  for ((attempt=0; attempt<70; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q '^master_link_status:up'; then
      return 0
    fi
    sleep 0.3
  done
  echo "Redis replica link never became ready: $container" >&2
  return 1
}

ready "$primary" 6393
ready "$replica" 6394
docker exec "$replica" redis-cli REPLICAOF "$primary" 6379 |
  grep -q '^OK'
role_is "$primary" master
role_is "$replica" slave
replica_link_up "$replica"

mapfile -t ids < <(python - <<'PY'
from uuid import uuid4
for _ in range(3):
    print(uuid4().hex)
PY
)
export LOOMERA_PHASE714_OBSERVING_ID="${ids[0]}"
export LOOMERA_PHASE714_QUARANTINED_ID="${ids[1]}"
export LOOMERA_PHASE714_HALTED_ID="${ids[2]}"
export PYTHONPATH="$PWD"

export LOOMERA_PHASE714_ACTIVE_LEADER=original
export LOOMERA_PHASE714_ALLOW_TEST_SEED=1
python -m unittest discover -s tests -p 'phase7_replica_promotion_fixture_test.py' -v
python tests/phase7_replica_promotion_drill.py prepare
unset LOOMERA_PHASE714_ALLOW_TEST_SEED

echo "Phase 7.14: real Docker stop of original primary"
docker stop --time 10 "$primary" >/dev/null
python - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(1)
    if sock.connect_ex(("127.0.0.1", 6393)) == 0:
        raise SystemExit("Old primary is still reachable after stop")
PY

# Explicit MANUAL promotion, not Sentinel or consensus-backed failover.
docker exec "$replica" redis-cli REPLICAOF NO ONE | grep -q '^OK'
role_is "$replica" master
export LOOMERA_PHASE714_ACTIVE_LEADER=promoted
python tests/phase7_replica_promotion_drill.py after-promotion

# Critical safety evidence: old primary *does* reboot as master, and may
# accept direct writes until reconfigured. The test adapter denies writes on
# its endpoint using CI-provided active leader, but this is NOT real fencing.
echo "Phase 7.14: restart OLD primary, inspect split-brain exposure"
docker start "$primary" >/dev/null
ready "$primary" 6393
role_is "$primary" master
python tests/phase7_replica_promotion_drill.py before-rejoin

echo "Phase 7.14: explicitly demote old primary into read-only replica"
docker exec "$primary" redis-cli REPLICAOF "$replica" 6379 | grep -q '^OK'
role_is "$primary" slave
replica_link_up "$primary"
python tests/phase7_replica_promotion_drill.py after-rejoin

echo "Phase 7.14 isolated Redis replica promotion + read-only rejoin PASSED"
# EXIT trap removes ONLY named Phase 7.14 test containers, volumes, network.
