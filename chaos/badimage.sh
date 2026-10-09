#!/usr/bin/env bash
# Deploy a tag that does not exist -> ErrImagePull/ImagePullBackOff. Expected: ROLLBACK.
source "$(dirname "$0")/_common.sh"
k set image "deploy/$DEP" app=demo-app:does-not-exist
watch_hint
