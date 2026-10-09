# Self-Healing Kubernetes

An AI agent that watches a Kubernetes cluster, diagnoses failures from logs + metrics + events, picks a remediation (**restart / rollback / scale**), executes it through the Kubernetes API, **verifies** recovery, and writes an **incident report**.

```
Failure -> Prometheus alert -> Alertmanager webhook -> Agent
        -> collect (K8s state, events, logs, Loki, PromQL) -> LLM decides -> guardrails
        -> execute (K8s API) -> verify (stable for N checks) -> incident report
```

Stack: Kubernetes (kind) · Prometheus + Alertmanager · Loki + Promtail · Grafana · Python (FastAPI, kubernetes client) · Claude (tool-use) · GitHub Actions. Architecture diagram: [docs/architecture.md](docs/architecture.md).

## Quickstart (about 10 minutes, first run downloads images)

Prereqs: Docker (>= 6 GB RAM allotted), [kind](https://kind.sigs.k8s.io), kubectl, Helm 3, make. Optional: `ANTHROPIC_API_KEY`.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # optional; without it the agent uses its deterministic rules engine
make up                               # preflight + cluster + observability + images + demo app + agent
make ui-grafana                       # http://localhost:3000  admin/admin  -> dashboard "Self-Healing Kubernetes"
```

Break things (in another terminal), and watch (`make logs`, `kubectl -n demo get pods -w`):

| Command | What breaks | Expected agent behaviour |
|---|---|---|
| `make chaos-crashloop` | new revision exits 1 after 5s | **rollback** |
| `make chaos-badimage` | nonexistent image tag | **rollback** |
| `make chaos-oom` | memory leak -> OOMKilled | **rollback** (recent rollout) |
| `make chaos-cpu` | CPU saturation under load | **scale up** (+50%, capped) |
| `make chaos-dependency` | logs show `ECONNREFUSED` to postgres | **escalate**, no action |
| `make chaos-reset` | - | healthy baseline |

Detection takes about 1 to 2 minutes (alert `for:` windows + Alertmanager `group_wait`). Reports: `make incidents`, or `make ui-agent` then `curl localhost:8080/incidents`.

No cluster handy? `make test` runs the unit tests (guardrails, rules, orchestrator, rollback selection, API) with no cluster or API key.

## Safety model

The LLM only *proposes*; deterministic code *disposes*.
- Fixed action set: restart, rollback, scale_up, escalate (escalate = do nothing, always allowed).
- Guardrails ([guardrails.py](agent/src/healer/guardrails.py)): namespace allowlist, per-deployment opt-in label `self-healing=enabled`, confidence floor, cooldown (5 min), hourly cap (3), rollback only to a *distinct* earlier template, scaling capped (`max_replicas`) and refused when an HPA owns the deployment.
- Namespaced RBAC `Role`s; no deletes, no Secrets.
- Logs are treated as untrusted prompt input.
- **`HEALER_DRY_RUN` defaults to `true` in code.** The demo ConfigMap sets it to `false` so the lab heals; on any real cluster start in dry-run and read the reports first.

## Configuration (env, prefix `HEALER_`)

| Variable | Default | Meaning |
|---|---|---|
| `DRY_RUN` | `true` | decide and report, never act |
| `ALLOWED_NAMESPACES` | `demo` | comma separated |
| `LLM_PROVIDER` | `anthropic` | `rules` forces the offline engine |
| `MODEL` | `claude-sonnet-5-5` | any Claude model id |
| `COOLDOWN_SECONDS` / `MAX_ACTIONS_PER_HOUR` | 300 / 3 | action rate limits per deployment |
| `MAX_REPLICAS` | 5 | scale ceiling |
| `MIN_CONFIDENCE` | 0.5 | below this the agent escalates |
| `VERIFY_TIMEOUT_SECONDS` | 240 | give up verifying after this |
| `WEBHOOK_TOKEN` | unset | require `Authorization: Bearer` on `/alerts` |
| `PROMETHEUS_URL`, `LOKI_URL` | in-cluster services | override when running locally |

## Onboarding your own app (e.g. Enterprise Task Manager)

1. Label the Deployment `self-healing: enabled` and make sure it has probes, resource limits and `revisionHistoryLimit >= 2`.
2. Add its namespace to the regex in `observability/alert-rules.yaml` and re-apply.
3. Add it to `HEALER_ALLOWED_NAMESPACES` and copy the `Role` + `RoleBinding` in `deploy/10-rbac.yaml` into that namespace.
4. Add a `ServiceMonitor` if you want app metrics. Do not label stateful stores (Postgres/Redis); the agent only manages Deployments.

## Layout

```
agent/        Python agent (src/healer/*, tests/, Dockerfile)
demo-app/     workload that can be broken via env vars + its k8s manifests
observability/  kube-prometheus-stack + loki-stack values, PrometheusRules, Grafana dashboard
deploy/       agent namespace, RBAC, Deployment, ServiceMonitor
chaos/        one script per failure scenario
scripts/      preflight.sh, send-test-alert.sh
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ImagePullBackOff` on `healer-agent:dev` / `demo-app:dev` | images not loaded: `make images`. Tags must not be `:latest`. |
| Prometheus pod `Pending`/OOM | give Docker >= 6 GB; `make preflight` |
| "too many open files" (Linux) | raise inotify limits (preflight prints the command) |
| No alerts reach the agent | Prometheus UI -> Alerts: is the rule firing? Alertmanager UI: is `healer-agent` receiver listed? `kubectl -n monitoring get pods` |
| Agent says `rules-only` | `ANTHROPIC_API_KEY` not set at `make agent` time; export it and rerun `make agent` |
| Metrics missing (`cpu_ratio_of_limit: null`) | kubelet/cAdvisor target down; check Prometheus -> Targets |
| Loki empty | `kubectl -n monitoring get pods | grep -E 'loki|promtail'`; agent still works from the Kubernetes log API |
| Nothing happens after the first fix | cooldown (5 min) and hourly cap are working as designed |

## Known limits / roadmap
- One remediation attempt per incident; no multi-step plans or retries with a different action yet.
- State (cooldowns, in-flight) is in memory -> single replica. Next: leader election + a persistent store.
- Deployments only (no StatefulSets/DaemonSets by design). Traces (Tempo) not wired in yet.
- Slack/PagerDuty notification on `escalated` / `not_recovered`.
- `grafana/loki-stack` is deprecated upstream; migrate to the `loki` + `alloy` charts.
