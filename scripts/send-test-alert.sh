#!/usr/bin/env bash
# Fire a fake Alertmanager webhook at the agent (after `make ui-agent`) to test the loop without Prometheus.
# usage: scripts/send-test-alert.sh <alertname> <pod>
set -euo pipefail
ALERT="${1:-PodCrashLooping}"; POD="${2:?usage: $0 <alertname> <pod-name>}"
curl -sS -X POST "${AGENT_URL:-http://localhost:8080}/alerts" -H 'Content-Type: application/json' \
  ${HEALER_WEBHOOK_TOKEN:+-H "Authorization: Bearer $HEALER_WEBHOOK_TOKEN"} \
  -d "{\"status\":\"firing\",\"alerts\":[{\"status\":\"firing\",\"labels\":{\"alertname\":\"$ALERT\",\"namespace\":\"demo\",\"pod\":\"$POD\"}}]}"
echo
