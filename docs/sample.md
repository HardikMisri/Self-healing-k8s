<!-- make incidents -->

kubectl --context kind-self-healing -n self-healing exec deploy/healer-agent -- sh -c 'for f in $(ls -t /data/incidents/_.md 2>/dev/null | head -3); do echo "=== $f"; cat $f; done'
hardikmisri@Hardiks-MacBook-Air self-healing-k8s % make incidents
kubectl --context kind-self-healing -n self-healing exec deploy/healer-agent -- sh -c 'for f in $(ls -t /data/incidents/_.md 2>/dev/null | head -3); do echo "=== $f"; cat $f; done'
=== /data/incidents/238eaf9b.md

# Incident 238eaf9b: PodCrashLooping on demo/demo-app

- **Time:** 2026-10-09T11:20:20+00:00
- **Outcome:** recovered
- **Action taken:** rolled demo/demo-app back to revision 2
- **Root cause (rules, confidence 0.85):** Crash loop started after a recent rollout (76s ago).
- **Chosen remediation:** `rollback`
- **Reasoning:** Failure correlates with the newest revision; reverting is the safest fix.

## Summary

Alert PodCrashLooping on demo/demo-app. Root cause (rules, confidence 0.85): Crash loop started after a recent rollout (76s ago). Chosen action: rollback. Outcome: recovered.

## Timeline

- `2026-10-09T11:20:20+00:00` alert received for demo/demo-app
- `2026-10-09T11:20:20+00:00` context collected: 3 pods, 15 events, 5 log sources
- `2026-10-09T11:20:20+00:00` decision [rules]: rollback (confidence 0.85) - Crash loop started after a recent rollout (76s ago).
- `2026-10-09T11:20:20+00:00` executed: rolled demo/demo-app back to revision 2
- `2026-10-09T11:20:36+00:00` verification: healthy for 3 consecutive checks
- `2026-10-09T11:20:36+00:00` outcome: recovered

## Evidence

- Metrics: `{'cpu_ratio_of_limit': 0.0117415850417263, 'memory_ratio_of_limit': 0.27386474609375, 'restarts_last_10m': 6.9257228564286315}`
- Pod `demo-app-7b75f78d49-5mprn`: restarts=3, waiting=CrashLoopBackOff, last_terminated=Error (exit 1)
- Pod `demo-app-7b75f78d49-t2ngs`: restarts=3, waiting=CrashLoopBackOff, last_terminated=Error (exit 1)
- Pod `demo-app-7fc58bd456-9nnsg`: restarts=0, waiting=None, last_terminated=None (exit None)

### Recent warning events

- [Normal] Pod/demo-app-7b75f78d49-t2ngs: Started: Container started
- [Warning] Pod/demo-app-7b75f78d49-t2ngs: Unhealthy: Readiness probe failed: Get "http://10.244.1.16:8000/healthz": dial tcp 10.244.1.16:8000: connect: connection refused
- [Normal] Pod/demo-app-7b75f78d49-5mprn: Pulled: Container image "demo-app:dev" already present on machine and can be accessed by the pod
- [Normal] Pod/demo-app-7b75f78d49-5mprn: Created: Container created
- [Normal] Pod/demo-app-7b75f78d49-5mprn: Started: Container started
- [Warning] Pod/demo-app-7b75f78d49-5mprn: Unhealthy: Readiness probe failed: Get "http://10.244.1.17:8000/healthz": dial tcp 10.244.1.17:8000: connect: connection refused
- [Warning] Pod/demo-app-7b75f78d49-t2ngs: BackOff: Back-off restarting failed container app in pod demo-app-7b75f78d49-t2ngs_demo(9053c172-e723-4a48-a5b2-b11c07c658b2)
- [Warning] Pod/demo-app-7b75f78d49-5mprn: BackOff: Back-off restarting failed container app in pod demo-app-7b75f78d49-5mprn_demo(5f2956e7-14f6-4687-8f9b-00ea7a4a2783)
  hardikmisri@Hardiks-MacBook-Air self-healing-k8s %
