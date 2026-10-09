#!/usr/bin/env bash
# Simulate "database unreachable": app crashes with ECONNREFUSED. Expected: ESCALATE (no restart/rollback).
source "$(dirname "$0")/_common.sh"
k set env "deploy/$DEP" CRASH_ON_START=true
# also make the crash line look like a dependency failure
k set env "deploy/$DEP" CRASH_MESSAGE="Error: connect ECONNREFUSED 10.96.0.50:5432 (postgres)"
watch_hint
