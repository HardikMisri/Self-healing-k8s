#!/usr/bin/env bash
# Open-loop load: ~3 req/s x 100ms CPU = ~0.3 core against a 0.2-core limit per pod. Expected: SCALE UP.
source "$(dirname "$0")/_common.sh"
k delete pod loadgen --ignore-not-found >/dev/null
k run loadgen --image=busybox:1.36 --restart=Never -- /bin/sh -c \
  'end=$(( $(date +%s) + 900 )); while [ $(date +%s) -lt $end ]; do for i in 1 2 3; do wget -q -T 30 -O /dev/null "http://demo-app/burn?ms=100" & done; sleep 1; done'
echo "load generator started (runs 15 min, stop it with chaos/reset.sh)"
watch_hint
