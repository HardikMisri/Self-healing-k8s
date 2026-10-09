"""Collect everything the decision layer needs into one Context object."""
from __future__ import annotations

from .config import Settings
from .kube import KubeClient
from .models import Alert, Context, Target
from .observability import LokiClient, PrometheusClient


class ContextBuilder:
    def __init__(self, kube: KubeClient, prom: PrometheusClient, loki: LokiClient, settings: Settings):
        self.kube, self.prom, self.loki, self.s = kube, prom, loki, settings

    def build(self, target: Target, alert: Alert) -> Context:
        dep = self.kube.deployment_info(target)
        pods = self.kube.pods(target)
        events = self.kube.events(target, [p.name for p in pods])

        logs: dict[str, str] = {}
        # worst pods first: most restarts, or not ready
        worst = sorted(pods, key=lambda p: (p.ready, -p.restarts))[:2]
        for p in worst:
            prev = self.kube.pod_log(target.namespace, p.name, self.s.log_tail_lines, previous=True)
            cur = self.kube.pod_log(target.namespace, p.name, self.s.log_tail_lines)
            if prev:
                logs[f"{p.name} (previous container)"] = prev
            if cur:
                logs[f"{p.name} (current container)"] = cur
        loki_lines = self.loki.recent_lines(target.namespace, target.deployment, self.s.log_tail_lines)
        if loki_lines:
            logs["loki (last 15m, all pods incl. deleted)"] = loki_lines

        metrics = {
            "cpu_ratio_of_limit": self.prom.cpu_ratio(target.namespace, target.deployment),
            "memory_ratio_of_limit": self.prom.memory_ratio(target.namespace, target.deployment),
            "restarts_last_10m": self.prom.restarts(target.namespace, target.deployment),
        }
        return Context(
            alert_name=alert.labels.get("alertname", "unknown"),
            alert_labels=alert.labels,
            alert_summary=alert.annotations.get("summary") or alert.annotations.get("description", ""),
            deployment=dep,
            pods=pods,
            events=events,
            logs=logs,
            metrics=metrics,
        )
