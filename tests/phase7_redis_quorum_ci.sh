#!/usr/bin/env bash
# Phase 7.17: 5 isolated Redis Docker processes on one ephemeral CI runner.
# Three independent witness AOF volumes, two replicated data AOF volumes.
# Manual election / no Raft, no production quorum, NO live OTP or session.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE717_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.17 requires explicit disposable GitHub CI grant" >&2
  exit 2
fi

base="loomera-p717-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
old="${base}-old"
new="${base}-new"
wa="${base}-vote-a"
wb="${base}-vote-b"
wc="${base}-vote-c"
client_net="${base}-client"
repl_net="${base}-replication"
vol_old="${base}-old-aof"
vol_new="${base}-new-aof"
vol_a="${base}-a-aof"
vol_b="${base}-b-aof"
vol_c="${base}-c-aof"

cleanup() {
  docker rm -f "$old" "$new" "$wa" "$wb" "$wc" >/dev/null 2>&1 || true
  docker volume rm -f "$vol_old" "$vol_new" "$vol_a" "$vol_b" "$vol_c" >/dev/null 2>&1 || true
  docker network rm "$repl_net" "$client_net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
for port in (6403, 6404, 6405, 6406, 6407):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("Refusing occupied isolated Redis port " + str(port))
PY

docker network create --driver bridge "$client_net" >/dev/null
docker network create --driver bridge "$repl_net" >/dev/null
for v in "$vol_old" "$vol_new" "$vol_a" "$vol_b" "$vol_c"; do
  docker volume create "$v" >/dev/null
done

# The data nodes share only the disposable replication bridge. Witness nodes
# do NOT participate in Redis replication and each has a separate AOF volume.
docker run -d --name "$old" --network "$client_net" \
  --mount "type=volume,source=$vol_old,target=/data" \
  --publish 127.0.0.1:6403:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --save "" >/dev/null
docker run -d --name "$new" --network "$client_net" \
  --mount "type=volume,source=$vol_new,target=/data" \
  --publish 127.0.0.1:6404:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always \
    --replica-read-only yes --repl-ping-replica-period 2 \
    --repl-timeout 8 --save "" >/dev/null

for spec in "$wa:$vol_a:6405" "$wb:$vol_b:6406" "$wc:$vol_c:6407"; do
  IFS=: read -r container volume port <<< "$spec"
  docker run -d --name "$container" --network "$client_net" \
    --mount "type=volume,source=$volume,target=/data" \
    --publish "127.0.0.1:${port}:6379" \
    redis:7.4-alpine redis-server --protected-mode no \
      --appendonly yes --appendfsync always --save "" >/dev/null
done

docker network connect --alias p717-original "$repl_net" "$old"
docker network connect --alias p717-promoted "$repl_net" "$new"

ready() {
  local name="$1" port="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$name" redis-cli ping 2>/dev/null | grep -qx PONG &&
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
    then return 0; fi
    sleep 0.5
  done
  echo "isolated Redis container not ready: $name" >&2
  docker logs --tail 60 "$name" >&2 || true
  return 1
}
role() {
  local container="$1" wanted="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${wanted}"; then return 0; fi
    sleep 0.3
  done
  echo "Redis role $wanted not observed: $container" >&2
  return 1
}
link() {
  local container="$1" wanted="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^master_link_status:${wanted}"; then return 0; fi
    sleep 0.35
  done
  echo "Redis link $wanted not observed: $container" >&2
  return 1
}

ready "$old" 6403
ready "$new" 6404
ready "$wa" 6405
ready "$wb" 6406
ready "$wc" 6407

docker exec "$new" redis-cli REPLICAOF p717-original 6379 | grep -q '^OK'
role "$old" master
role "$new" slave
link "$new" up
for container in "$wa" "$wb" "$wc"; do role "$container" master; done

mapfile -t ids < <(python - <<'PY'
from uuid import uuid4
for _ in range(4):
    print(uuid4().hex)
PY
)
export LOOMERA_PHASE717_ID="${ids[0]}"
export LOOMERA_PHASE717_TOKEN_A="${ids[1]}"
export LOOMERA_PHASE717_TOKEN_B="${ids[2]}"
export LOOMERA_PHASE717_TOKEN_C="${ids[3]}"
export PYTHONPATH="$PWD"

# Prepare-stage-only synthetic authorization, never used in live software.
export LOOMERA_PHASE717_ALLOW_SEED=1
export LOOMERA_PHASE717_ALLOW_TEST_VOTE=1
export LOOMERA_PHASE717_ALLOW_TEST_HALT=1
python -m unittest discover -s tests -p 'phase7_quorum_voter_test.py' -v
python tests/phase7_quorum_failure_drill.py prepare
unset LOOMERA_PHASE717_ALLOW_SEED
unset LOOMERA_PHASE717_ALLOW_TEST_VOTE
unset LOOMERA_PHASE717_ALLOW_TEST_HALT

echo "Phase 7.17: physically disconnect data replication-only bridge"
docker network disconnect "$repl_net" "$new"
ready "$old" 6403
ready "$new" 6404
role "$old" master
role "$new" slave
docker exec "$new" redis-cli CLIENT KILL TYPE MASTER >/dev/null
link "$new" down

# Positive proof of real replication disconnection, not just INFO text.
python - <<'PY'
import os, redis
source = redis.Redis(host="127.0.0.1", port=6403, db=15, socket_timeout=4)
key = "loomera:phase717:synthetic-write-only:" + os.environ["LOOMERA_PHASE717_ID"] + ":probe"
try:
    assert source.set(key, "source-only-after-link-break", ex=60)
    assert source.wait(1, 1500) == 0, "new source write was unexpectedly replicated"
finally:
    source.close()
print("Phase 7.17: WAIT=0 confirmed on newly issued source write")
PY

docker exec "$new" redis-cli REPLICAOF NO ONE | grep -q '^OK'
role "$new" master
role "$old" master
python - <<'PY'
import os, redis
promoted = redis.Redis(host="127.0.0.1", port=6404, db=15, socket_timeout=5)
key = "loomera:phase717:synthetic-write-only:" + os.environ["LOOMERA_PHASE717_ID"] + ":probe"
try:
    assert promoted.ping()
    assert promoted.get(key) is None, "post-partition probe crossed to promoted Redis"
finally:
    promoted.close()
print("Phase 7.17: promoted Redis lacks post-disconnect source write")
PY

export LOOMERA_PHASE717_ALLOW_TEST_VOTE=1
export LOOMERA_PHASE717_ALLOW_TEST_ADOPT=1
export LOOMERA_PHASE717_ALLOW_TEST_WRITE=1
python tests/phase7_quorum_failure_drill.py after-partition
unset LOOMERA_PHASE717_ALLOW_TEST_VOTE
unset LOOMERA_PHASE717_ALLOW_TEST_ADOPT

echo "Phase 7.17: stop TWO of three voter processes to lose majority"
docker stop --time 5 "$wb" "$wc" >/dev/null
python tests/phase7_quorum_failure_drill.py witness-loss
docker start "$wb" "$wc" >/dev/null
ready "$wb" 6406
ready "$wc" 6407
unset LOOMERA_PHASE717_ALLOW_TEST_WRITE

echo "Phase 7.17: reconnect old data master as replica, and halt witnesses"
docker network connect --alias p717-promoted "$repl_net" "$new"
docker exec "$old" redis-cli REPLICAOF p717-promoted 6379 | grep -q '^OK'
role "$old" slave
link "$old" up
export LOOMERA_PHASE717_ALLOW_TEST_HALT=1
python tests/phase7_quorum_failure_drill.py after-rejoin
unset LOOMERA_PHASE717_ALLOW_TEST_HALT

echo "Phase 7.17 real 3-voter majority/loss, dual-master raw bypass drill PASSED"
# EXIT trap deletes ONLY dedicated Phase 7.17 containers, networks, volumes.
