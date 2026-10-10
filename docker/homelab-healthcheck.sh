#!/bin/sh
# Docker HEALTHCHECK for the homelab image.
#
# The gateway rewrites $HERMES_HOME/state/gateway.heartbeat every 30s from a
# task on its main event loop (gateway.shutdown_watchdog.loop_heartbeat_forever).
# A frozen or deadlocked loop stops the rewrites, so a stale file means the
# gateway cannot answer anyone. Swarm only replaces a task that reports
# unhealthy; without this check it stays "Running" while nobody gets a reply.
#
# The default of 90s (three missed beats) matches the staleness budget in
# hermes_cli.gateway.DEFAULT_LOOP_LIVENESS_STALE_AFTER_S.
heartbeat_file="${HERMES_HOME:-/opt/data}/state/gateway.heartbeat"
maximum_age_seconds="${HERMES_HEALTHCHECK_MAX_AGE_SECONDS:-90}"

modified_at=$(stat -c %Y "$heartbeat_file" 2>/dev/null) || {
    echo "unhealthy: $heartbeat_file is missing" >&2
    exit 1
}
age_seconds=$(( $(date +%s) - modified_at ))
if [ "$age_seconds" -gt "$maximum_age_seconds" ]; then
    echo "unhealthy: gateway heartbeat is ${age_seconds}s old (limit ${maximum_age_seconds}s)" >&2
    exit 1
fi
