#!/usr/bin/env bash
# Phase 7.19: PHYSICAL Redis client bridge cut; separate bypass stays writable.
# Exact disposable GitHub Docker objects only, never customer infrastructure.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${LOOMERA_PHASE719_TEST_REDIS:-}" != "1" ||
      -z "${GITHUB_RUN_ID:-}" || -z "${GITHUB_RUN_ATTEMPT:-}" ]]; then
  echo "Phase 7.19 requires explicit disposable GitHub CI grant" >&2
  exit 2
fi

base="loomera-p719-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
old="${base}-old"
promoted="${base}-promoted"
writer="${base}-writer"
client_net="${base}-client"
repl_net="${base}-repl"
bypass_net="${base}-bypass"
old_vol="${base}-old-aof"
promoted_vol="${base}-promoted-aof"

cleanup() {
  docker rm -f "$writer" "$promoted" "$old" >/dev/null 2>&1 || true
  docker volume rm -f "$old_vol" "$promoted_vol" >/dev/null 2>&1 || true
  docker network rm "$client_net" "$repl_net" "$bypass_net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker info >/dev/null
python - <<'PY'
import socket
for port in (6410, 6411):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit("Refusing occupied isolated port " + str(port))
PY

docker network create --driver bridge "$bypass_net" >/dev/null
docker network create --driver bridge "$client_net" >/dev/null
docker network create --driver bridge "$repl_net" >/dev/null
docker volume create "$old_vol" >/dev/null
docker volume create "$promoted_vol" >/dev/null

# Data servers are initially published from a dedicated bypass bridge, so
# removing the separate client bridge cannot silently revoke host access.
docker run -d --name "$old" --network "$bypass_net" \
  --mount "type=volume,source=$old_vol,target=/data" \
  --publish 127.0.0.1:6410:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --save "" >/dev/null
docker run -d --name "$promoted" --network "$bypass_net" \
  --mount "type=volume,source=$promoted_vol,target=/data" \
  --publish 127.0.0.1:6411:6379 \
  redis:7.4-alpine redis-server --protected-mode no \
    --appendonly yes --appendfsync always --replica-read-only yes \
    --repl-ping-replica-period 2 --repl-timeout 8 --save "" >/dev/null

docker network connect --alias p719-old-client "$client_net" "$old"
docker network connect --alias p719-new-client "$client_net" "$promoted"
docker network connect --alias p719-old-repl "$repl_net" "$old"
docker network connect --alias p719-new-repl "$repl_net" "$promoted"

# Only client bridge; no bypass network membership or published port.
docker run -d --name "$writer" --network "$client_net" \
  redis:7.4-alpine sh -c 'sleep 600' >/dev/null

ready() {
  local container="$1" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$container" redis-cli PING 2>/dev/null | grep -qx PONG; then
      return 0
    fi
    sleep 0.3
  done
  echo "Isolated Redis not ready: $container" >&2
  return 1
}
role() {
  local container="$1" expected="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^role:${expected}"; then return 0; fi
    sleep 0.3
  done
  echo "Redis role not observed: $container $expected" >&2
  return 1
}
link() {
  local container="$1" expected="$2" attempt
  for ((attempt=0; attempt<80; attempt++)); do
    if docker exec "$container" redis-cli INFO replication 2>/dev/null |
       grep -q "^master_link_status:${expected}"; then return 0; fi
    sleep 0.35
  done
  echo "Redis upstream link not observed: $container $expected" >&2
  return 1
}

ready "$old"
ready "$promoted"
docker exec "$writer" sh -c 'true' >/dev/null
docker exec "$promoted" redis-cli REPLICAOF p719-old-repl 6379 | grep -q '^OK'
role "$old" master
role "$promoted" slave
link "$promoted" up

export LOOMERA_PHASE719_ID="$(python - <<'PY'
from uuid import uuid4
print(uuid4().hex)
PY
)"
export PYTHONPATH="$PWD"

key="loomera:phase719:synthetic-network-only:${LOOMERA_PHASE719_ID}:state"
lua="return redis.call('HSET', KEYS[1], 'writer', ARGV[1])"

client_raw_eval() {
  local hostname="$1" label="$2" result
  result="$(timeout 8s docker exec "$writer" redis-cli --raw \
    -h "$hostname" -p 6379 -n 15 EVAL "$lua" 1 "$key" "$label")"
  if [[ "$result" != "0" && "$result" != "1" ]]; then
    echo "unexpected synthetic Redis raw EVAL response: $result" >&2
    return 1
  fi
}

python tests/phase7_network_ingress_drill.py seed
client_raw_eval p719-old-client "bridge-before"
python tests/phase7_network_ingress_drill.py bridge-before

echo "Phase 7.19: physically disconnect replication-only bridge"
docker network disconnect "$repl_net" "$promoted"
docker exec "$promoted" redis-cli CLIENT KILL TYPE MASTER >/dev/null
link "$promoted" down
docker exec "$promoted" redis-cli REPLICAOF NO ONE | grep -q '^OK'
role "$old" master
role "$promoted" master
python tests/phase7_network_ingress_drill.py after-partition

client_raw_eval p719-old-client "stale-client"
python tests/phase7_network_ingress_drill.py pre-client-fence

# Capture *previous* client network IP. Proving only DNS alias fails would
# be insufficient: also verify the old IP no longer accepts raw EVAL.
old_client_ip="$(docker inspect "$old" --format '{{json .NetworkSettings.Networks}}' |
  python -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]]["IPAddress"])' "$client_net")"
python - "$old_client_ip" <<'PY'
import ipaddress, sys
assert ipaddress.ip_address(sys.argv[1]).version == 4
PY

echo "Phase 7.19: physically remove old primary from client bridge only"
docker network disconnect "$client_net" "$old"
role "$old" master
role "$promoted" master
client_raw_eval p719-new-client "promoted-client"

# The same surviving client-container is now unable to EVAL the old master
# through either DNS or its previous client-interface address.
for target in p719-old-client "$old_client_ip"; do
  if timeout 8s docker exec "$writer" redis-cli --raw \
      -h "$target" -p 6379 -n 15 EVAL "$lua" 1 "$key" "must-not-write" \
      >/dev/null 2>&1; then
    echo "SECURITY FAIL: client route still writes old primary via $target" >&2
    exit 1
  fi
done

# Host port was intentionally bound through ANOTHER bridge. This must still
# accept a RAW EVAL to prove the first cut did not globally fence old Redis.
python tests/phase7_network_ingress_drill.py post-client-fence

echo "Phase 7.19 DONE: bridge-client raw EVAL denied while host old RAW EVAL BYPASSES"
