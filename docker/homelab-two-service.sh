#!/bin/bash
# /opt/hermes/docker/homelab-two-service.sh
#
# Runs the Hermes dashboard AND gateway in ONE container, without s6-overlay.
#
# Why: titan's /etc/docker/daemon.json sets "init": true, so /sbin/docker-init
# (tini) is always PID 1 and s6-overlay refuses to start — s6-svscan must be
# PID 1 because only PID 1 reaps re-parented orphans. Upstream's entrypoint
# detects this and falls back to running a single unsupervised command, so the
# supervised dashboard never starts.
#
# We don't need s6 here: tini is already PID 1 and does the orphan reaping,
# which was s6's job. We just need two children. Upstream sanctions running the
# gateway under a foreign process manager via --no-supervise (see also
# --external-supervisor).
#
# Both processes must share a PID namespace: the dashboard decides whether the
# gateway is alive with is_gateway_running(), which reads a PID file from
# /opt/data and checks that the PID exists. Across two containers that check
# always fails (and can delete the PID file as stale), which is what breaks the
# Android client's Desktop Gateway WebSocket transport.
#
# If either process exits, this script exits so Swarm recycles the container —
# that is our substitute for supervision.
set -e

# The non-PID-1 fallback in entrypoint-dispatch.sh seeds these before running
# the bootstrap; mirror it exactly.
export PATH="/command:/package/admin/s6/command:${PATH}"
/opt/hermes/docker/stage2-hook.sh

# main-wrapper.sh rehydrates env, drops root -> hermes via s6-setuidgid, and
# routes its args to `hermes <args>`. It execs, so each child below IS the
# real process.
/opt/hermes/docker/main-wrapper.sh \
    dashboard --host "${HERMES_DASHBOARD_HOST:-0.0.0.0}" \
              --port "${HERMES_DASHBOARD_PORT:-9119}" --no-open &
dashboard_pid=$!

/opt/hermes/docker/main-wrapper.sh gateway run --no-supervise &
gateway_pid=$!

terminate() {
    kill "$dashboard_pid" "$gateway_pid" 2>/dev/null || true
    wait "$dashboard_pid" "$gateway_pid" 2>/dev/null || true
}
trap 'terminate; exit 143' TERM INT

# Exit as soon as EITHER child dies, carrying its status out to Swarm.
wait -n
exit_code=$?
echo "[homelab] a supervised process exited (status=$exit_code); stopping container so Swarm recycles it" >&2
terminate
exit "$exit_code"
