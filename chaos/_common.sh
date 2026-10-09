#!/usr/bin/env bash
# shared by all chaos scripts
set -euo pipefail
NS="${NS:-demo}"
DEP="${DEP:-demo-app}"
CTX="kind-self-healing"
k() { kubectl --context "$CTX" -n "$NS" "$@"; }
watch_hint() {
  echo
  echo "Watch the healing:"
  echo "  kubectl --context $CTX -n $NS get pods -w"
  echo "  kubectl --context $CTX -n self-healing logs deploy/healer-agent -f"
  echo "  curl -s localhost:8080/incidents   (after: make ui-agent)"
}
