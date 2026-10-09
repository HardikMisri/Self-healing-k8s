CLUSTER      ?= self-healing
KPS_VERSION  ?= 92.1.1
LOKI_VERSION ?= 2.10.3
KIND_NODE_IMAGE ?=
CTX          := kind-$(CLUSTER)
KUBECTL      := kubectl --context $(CTX)
HELM         := helm --kube-context $(CTX)

.DEFAULT_GOAL := help
.PHONY: help preflight cluster observability images demo agent secret up down test \
	    ui-grafana ui-prometheus ui-agent logs incidents chaos-crashloop chaos-oom chaos-badimage \
	    chaos-cpu chaos-dependency chaos-reset status

help: ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

preflight: ## check docker/kind/kubectl/helm, RAM, ports
	@./scripts/preflight.sh

cluster: ## create the kind cluster
	@kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config kind/kind-config.yaml $(if $(KIND_NODE_IMAGE),--image $(KIND_NODE_IMAGE),)
	@$(KUBECTL) wait --for=condition=Ready nodes --all --timeout=180s

observability: ## install Prometheus+Alertmanager+Grafana and Loki+Promtail, alert rules, dashboard
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo add grafana https://grafana.github.io/helm-charts
	helm repo update
	$(HELM) upgrade --install kps prometheus-community/kube-prometheus-stack -n monitoring --create-namespace \
	    --version $(KPS_VERSION) -f observability/kube-prometheus-stack-values.yaml --wait --timeout 10m
	$(HELM) upgrade --install loki grafana/loki-stack -n monitoring \
	    --version $(LOKI_VERSION) -f observability/loki-stack-values.yaml --wait --timeout 5m
	$(KUBECTL) apply -f observability/alert-rules.yaml -f observability/grafana-dashboard.yaml

images: ## build agent + demo images and load them into kind
	docker build -t healer-agent:dev agent
	docker build -t demo-app:dev demo-app
	kind load docker-image healer-agent:dev demo-app:dev --name $(CLUSTER)

demo: ## deploy the demo workload
	$(KUBECTL) apply -f demo-app/k8s/00-namespace.yaml
	$(KUBECTL) apply -f demo-app/k8s/10-demo-app.yaml
	$(KUBECTL) -n demo rollout restart deploy/demo-app
	$(KUBECTL) -n demo rollout status deploy/demo-app --timeout=180s

secret: ## store ANTHROPIC_API_KEY (if exported) as a cluster Secret
	@$(KUBECTL) apply -f deploy/00-namespace.yaml
	@if [ -n "$$ANTHROPIC_API_KEY" ]; then \
	    $(KUBECTL) -n self-healing create secret generic healer-secrets --from-literal=ANTHROPIC_API_KEY="$$ANTHROPIC_API_KEY" --dry-run=client -o yaml | $(KUBECTL) apply -f - ; \
	    echo "LLM mode enabled"; \
	else echo "ANTHROPIC_API_KEY not set -> rules-only mode"; fi

agent: secret ## deploy the healing agent
	$(KUBECTL) apply -f demo-app/k8s/00-namespace.yaml
	$(KUBECTL) apply -f deploy/10-rbac.yaml -f deploy/20-agent.yaml
	$(KUBECTL) -n self-healing rollout restart deploy/healer-agent
	$(KUBECTL) -n self-healing rollout status deploy/healer-agent --timeout=180s

up: preflight cluster observability images demo agent ## everything, from nothing
	@echo; echo "Ready. Try: make chaos-crashloop   then   make logs"

down: ## delete the cluster
	kind delete cluster --name $(CLUSTER)

test: ## run unit tests
	cd agent && python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt && .venv/bin/python -m pytest -q

status: ## quick health overview
	$(KUBECTL) get pods -A | grep -E 'demo|self-healing|monitoring' || true
	@curl -s localhost:8080/healthz || echo "(agent not port-forwarded; run make ui-agent)"

ui-grafana: ## Grafana on http://localhost:3000 (admin/admin)
	$(KUBECTL) -n monitoring port-forward svc/kps-grafana 3000:80
ui-prometheus: ## Prometheus on http://localhost:9090
	$(KUBECTL) -n monitoring port-forward svc/kps-prometheus 9090:9090
ui-agent: ## agent API on http://localhost:8080 (/incidents, /healthz)
	$(KUBECTL) -n self-healing port-forward svc/healer-agent 8080:8080

logs: ## follow agent logs
	$(KUBECTL) -n self-healing logs deploy/healer-agent -f --tail=50
incidents: ## print the latest incident reports from the agent pod
	$(KUBECTL) -n self-healing exec deploy/healer-agent -- sh -c 'for f in $$(ls -t /data/incidents/*.md 2>/dev/null | head -3); do echo "=== $$f"; cat $$f; done'

chaos-crashloop: ## bad config rollout -> expect ROLLBACK
	./chaos/crashloop.sh
chaos-oom: ## memory leak rollout -> expect ROLLBACK
	./chaos/oom.sh
chaos-badimage: ## nonexistent image tag -> expect ROLLBACK
	./chaos/badimage.sh
chaos-cpu: ## CPU saturation -> expect SCALE UP
	./chaos/cpu.sh
chaos-dependency: ## fake DB outage -> expect ESCALATE (no action)
	./chaos/dependency.sh
chaos-reset: ## back to healthy baseline
	./chaos/reset.sh
