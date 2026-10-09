"""After acting, confirm the workload is genuinely healthy (and stays healthy) before declaring success."""
from __future__ import annotations

import logging
import time
from typing import Callable

from .config import Settings
from .kube import BAD_WAITING, KubeClient
from .models import Decision, Target
from .observability import PrometheusClient

log = logging.getLogger(__name__)


class Verifier:
    def __init__(self, kube: KubeClient, prom: PrometheusClient, settings: Settings,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.kube, self.prom, self.s, self.sleep, self.clock = kube, prom, settings, sleep, clock

    def _healthy(self, target: Target, decision: Decision) -> tuple[bool, str]:
        info = self.kube.deployment_info(target)
        pods = self.kube.pods(target)
        if info.desired == 0:
            return False, "deployment has 0 desired replicas"
        if decision.action == "scale_up" and decision.replicas and info.desired != decision.replicas:
            return False, f"desired replicas {info.desired} != {decision.replicas}"
        if info.updated < info.desired or info.available < info.desired:
            return False, f"rollout incomplete (updated={info.updated}, available={info.available}, desired={info.desired})"
        bad = [p.name for p in pods if p.waiting_reason in BAD_WAITING or not p.ready]
        if bad:
            return False, f"unhealthy pods: {', '.join(bad)}"
        if decision.action == "scale_up":
            cpu = self.prom.cpu_ratio(target.namespace, target.deployment, window="1m")
            if cpu is not None and cpu >= self.s.cpu_alert_threshold:
                return False, f"CPU still {cpu:.0%} of limit"
        return True, "healthy"

    def wait_for_recovery(self, target: Target, decision: Decision) -> tuple[bool, str]:
        deadline = self.clock() + self.s.verify_timeout_seconds
        streak, last_reason = 0, "not checked"
        last_restarts: int | None = None
        while self.clock() < deadline:
            try:
                ok, last_reason = self._healthy(target, decision)
                restarts = sum(p.restarts for p in self.kube.pods(target))
            except Exception as e:
                ok, last_reason, restarts = False, f"check failed: {e}", last_restarts
            if ok and last_restarts is not None and restarts is not None and restarts > last_restarts:
                ok, last_reason = False, "container restarted during verification"
            last_restarts = restarts
            streak = streak + 1 if ok else 0
            if streak >= self.s.verify_stable_checks:
                return True, f"healthy for {streak} consecutive checks"
            self.sleep(self.s.verify_interval_seconds)
        return False, f"timed out after {self.s.verify_timeout_seconds}s: {last_reason}"
