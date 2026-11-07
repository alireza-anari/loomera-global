#!/usr/bin/env bash
# Phase 7.15: live replication network-partition drill on TWO disposable
# redis:7.4-alpine CI containers. NEVER Production or the CI 6379 service.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE715_TEST_REDIS:-}" != "1" ||
      "${LOOMERA_PHASE715_WITNESS_TEST:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.15 needs explicit GitHub-hosted synthetic grants" >&2
  exit 2
fi

base="loomera-p715-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
old="${base}-old"
new="${base}-new"
client_net="${base}-client-net"
replication_net="${base}-replication-net"
old_volume="${base}-old-aof"
new_volume="${base}-new-aof"

cleanup() {
  docker rm -f "$old" "$new" >/dev/null 2>&1 || true
  docker volume rm -f "$old_volume" "$new_volume" >/dev/null 2>&1 || true
  docker network rm "$replication_net" "$client_net" >/dev/null 2>&1 || true
  if [[ -n "${LOOMERA_PHASE715_WITNESS_ID:-}" ]]; then
    python - <<'PY' || true
import os
from loomera.globalization.otp_partition_witness_rehearsal import (
    SyntheticLocalPartitionWitness, fixture_witness_path,
)
id = os.environ["LOOMERA_PHASE715_WITNESS_ID"]
SyntheticLocalPartitionWitness(
    fixture_id=id, path=fixture_witness_path(id),
).cleanup_owned_fixture()
PY
  fi
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
for port in (6395, 6396):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("Refusing to use occupied Redis test port " + str(port))
PY

# Every network, volume and container is dedicated to this CI run. The
# replication link has its OWN bridge, separable from the host-client bridge.
docker network create --driver bridge "$client_net" >/dev/null
docker network create --driver bridge "$replication_net" >/dev/null
docker volume create "$old_volume" >/dev/null
docker volume create "$new_volume" >/dev/null
docker run -d --name "$old" \
  --network "$client_net" \
  --mount "type=volume,source=$old_volume,target=/data" \
  --publish 127.0.0.1:6395:6379 \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always \
    --save "" >/dev/null
docker run -d --name "$new" \
  --network "$client_net" \
  --mount "type=volume,source=$new_volume,target=/data" \
  --publish 127.0.0.1:6396:6379 \
  redis:7.4-alpine redis-server \
    --protected-mode no --appendonly yes --appendfsync always \
    --replica-read-only yes --save "" >/dev/null

# Replication takes place ONLY via the detachable second bridge.
docker network connect --alias p715-source "$replication_net" "$old"
docker network connect --alias p715-promoted "$replication_net" "$new"

ready() {
  local container="$1" port="$2" i
  for ((i=0; i<70; i++)); do
    if docker exec "$container" redis-cli ping 2>/dev/null | grep -qx PONG &&
      python - "$port" <<'PY' 2>/dev/null
import redis, sys
c = redis.Redis(host="127.0.0.1", port=int(sys.argv[1]), db=15,
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
  echo "Redis isolated fixture not ready: $container" >&2
  docker logs --tail 60 "$container" >&2 || true
  return 1
}

assert_role() {
  local container="$1" expected="$2" i
  for ((i=0; i<70; i++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${expected}"; then return 0; fi
    sleep 0.3
  done
  echo "Redis role mismatch ($expected) on $container" >&2
  return 1
}

assert_link() {
  local container="$1" expected="$2" i
  for ((i=0; i<80; i++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^master_link_status:${expected}"; then return 0; fi
    sleep 0.4
  done
  echo "Redis replication link did not become $expected" >&2
  docker logs --tail 45 "$container" >&2 || true
  return 1
}

ready "$old" 6395
ready "$new" 6396
docker exec "$new" redis-cli REPLICAOF p715-source 6379 | grep -q '^OK'
assert_role "$old" master
assert_role "$new" slave
assert_link "$new" up

mapfile -t ids < <(python - <<'PY'
from uuid import uuid4
for _ in range(4):
    print(uuid4().hex)
PY
)
export LOOMERA_PHASE715_OBSERVING_ID="${ids[0]}"
export LOOMERA_PHASE715_QUARANTINED_ID="${ids[1]}"
export LOOMERA_PHASE715_HALTED_ID="${ids[2]}"
export LOOMERA_PHASE715_WITNESS_ID="${ids[3]}"
export PYTHONPATH="$PWD"
export LOOMERA_PHASE715_ACTIVE_LEADER=original

# Seed/mutation grants are LIMITED TO THE PRE-PARTITION UNIT AND PREPARE STAGE.
export LOOMERA_PHASE715_ALLOW_TEST_SEED=1
export LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION=1
python -m unittest discover -s tests -p 'phase7_partition_witness_test.py' -v
python -m unittest discover -s tests -p 'phase7_partition_redis_test.py' -v
python tests/phase7_partition_dualmaster_drill.py prepare
unset LOOMERA_PHASE715_ALLOW_TEST_SEED
unset LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION

# A REAL network partition: remove ONLY the replication-specific bridge
# attachment. Both containers retain the separate client bridge and loopback
# published ports. The old primary remains online and writable.
echo "Phase 7.15: disconnecting REAL Redis replication network"
docker network disconnect "$replication_net" "$new"
ready "$old" 6395
ready "$new" 6396
assert_role "$old" master
assert_role "$new" slave
assert_link "$new" down

# Manual promotion DURING the live network partition: TWO raw Redis masters.
docker exec "$new" redis-cli REPLICAOF NO ONE | grep -q '^OK'
assert_role "$new" master
assert_role "$old" master
echo "Phase 7.15: two simultaneously running Redis masters now reachable"
python tests/phase7_partition_dualmaster_drill.py during-partition

# Reconnect network and explicitly demote the old primary. This is a human
# test-runner action, NOT Sentinel, automatic failover or consensus fencing.
echo "Phase 7.15: restoring replication network and demoting old primary"
docker network connect --alias p715-promoted "$replication_net" "$new"
docker exec "$old" redis-cli REPLICAOF p715-promoted 6379 | grep -q '^OK'
assert_role "$old" slave
assert_link "$old" up
export LOOMERA_PHASE715_ACTIVE_LEADER=promoted
python tests/phase7_partition_dualmaster_drill.py after-rejoin

echo "Phase 7.15 real dual-master network partition and terminal witness halt PASSED"
# Exit trap deletes ONLY these two CI containers, two networks, two volumes,
# and this run's named local SQLite synthetic witness.
