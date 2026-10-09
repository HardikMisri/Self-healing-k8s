#!/usr/bin/env bash
# Back to a healthy baseline.
source "$(dirname "$0")/_common.sh"
k delete pod loadgen --ignore-not-found >/dev/null
k scale "deploy/$DEP" --replicas=2
k set env "deploy/$DEP" CRASH_ON_START=false LEAK_MEMORY=false CRASH_MESSAGE-
k set image "deploy/$DEP" app=demo-app:dev
k rollout status "deploy/$DEP" --timeout=120s
