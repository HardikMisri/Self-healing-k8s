"""Prometheus + Loki clients. Every call degrades to None/'' on failure; the agent keeps working."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)


def pod_regex(deployment: str) -> str:
    # <deployment>-<replicaset-hash>-<pod-suffix>; avoids matching "demo-app-worker-..." for "demo-app"
    return f"{deployment}-[a-z0-9]+-[a-z0-9]+"


class PrometheusClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, promql: str) -> float | None:
        try:
            r = httpx.get(
                f"{self.base_url}/api/v1/query", params={"query": promql}, timeout=self.timeout
            )
            r.raise_for_status()
            result = r.json()["data"]["result"]
            if not result:
                return None
            return float(result[0]["value"][1])
        except Exception as e:
            log.warning("prometheus query failed (%s): %s", promql[:60], e)
            return None

    def cpu_ratio(self, ns: str, deployment: str, window: str = "2m") -> float | None:
        sel = f'namespace="{ns}",pod=~"{pod_regex(deployment)}"'
        return self.query(
            f'max(sum by (pod)(rate(container_cpu_usage_seconds_total{{{sel},container!=""}}[{window}]))'
            f' / sum by (pod)(kube_pod_container_resource_limits{{{sel},resource="cpu"}}))'
        )

    def memory_ratio(self, ns: str, deployment: str) -> float | None:
        sel = f'namespace="{ns}",pod=~"{pod_regex(deployment)}"'
        return self.query(
            f'max(sum by (pod)(container_memory_working_set_bytes{{{sel},container!=""}})'
            f' / sum by (pod)(kube_pod_container_resource_limits{{{sel},resource="memory"}}))'
        )

    def restarts(self, ns: str, deployment: str, window: str = "10m") -> float | None:
        sel = f'namespace="{ns}",pod=~"{pod_regex(deployment)}"'
        return self.query(
            f"sum(increase(kube_pod_container_status_restarts_total{{{sel}}}[{window}]))"
        )


class LokiClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def recent_lines(self, ns: str, deployment: str, limit: int = 60, minutes: int = 15) -> str:
        """Recent lines across *all* pods of the deployment, including pods that no longer exist."""
        now = time.time()
        try:
            r = httpx.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": f'{{namespace="{ns}", pod=~"{pod_regex(deployment)}"}}',
                    "limit": limit,
                    "direction": "backward",
                    "start": int((now - minutes * 60) * 1e9),
                    "end": int(now * 1e9),
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            rows: list[tuple[int, str]] = []
            for stream in r.json()["data"]["result"]:
                pod = stream["stream"].get("pod", "?")
                for ts, line in stream["values"]:
                    rows.append((int(ts), f"{pod}: {line}"))
            rows.sort()
            return "\n".join(line for _, line in rows[-limit:])
        except Exception as e:
            log.warning("loki query failed: %s", e)
            return ""
