#!/usr/bin/env bash
# Bad config rollout: new pods exit 1 five seconds after start. Expected remediation: ROLLBACK.
source "$(dirname "$0")/_common.sh"
k set env "deploy/$DEP" CRASH_ON_START=true
watch_hint
