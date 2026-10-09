#!/usr/bin/env bash
# Memory leak rollout: pods grow ~10 MiB/s until OOMKilled (limit 128Mi). Expected: ROLLBACK.
source "$(dirname "$0")/_common.sh"
k set env "deploy/$DEP" LEAK_MEMORY=true
watch_hint
