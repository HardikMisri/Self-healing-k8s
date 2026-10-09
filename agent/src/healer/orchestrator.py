"""The control loop: alert -> context -> decision -> guardrails -> execute -> verify -> report."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import Counter

from .brain import Brain, template_summary
from .config import Settings
from .context import ContextBuilder
from .executor import Executor
from .guardrails import Guardrails
from .incidents import IncidentStore
from .kube import KubeClient
from .models import Alert, Context, Incident
from .verifier import Verifier

log = logging.getLogger(__name__)

INCIDENTS = Counter("healer_incidents_total", "Incidents handled", ["action", "outcome"])


class Orchestrator:
    def __init__(self, settings: Settings, kube: KubeClient, ctx_builder: ContextBuilder,
                 brain: Brain, guardrails: Guardrails, executor: Executor,
                 verifier: Verifier, store: IncidentStore):
        self.s, self.kube, self.ctxb, self.brain = settings, kube, ctx_builder, brain
        self.guard, self.exec, self.verifier, self.store = guardrails, executor, verifier, store
        self._inflight: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="healer")

    def submit(self, alert: Alert) -> None:
        self._pool.submit(self._safe_handle, alert)

    def _safe_handle(self, alert: Alert) -> None:
        try:
            self.handle_alert(alert)
        except Exception:
            log.exception("unhandled error while processing alert")

    def handle_alert(self, alert: Alert) -> Incident | None:
        name = alert.labels.get("alertname", "unknown")
        ns = alert.labels.get("namespace", "")
        if ns not in self.s.namespaces:
            log.info("ignoring %s: namespace '%s' not allowlisted", name, ns)
            return None

        target = self.kube.resolve_target(alert.labels)
        if target is None:
            log.info("ignoring %s: cannot resolve a Deployment from labels %s", name, alert.labels)
            return None

        with self._lock:
            if target.key in self._inflight:
                log.info("%s already being handled; dropping duplicate %s", target, name)
                return None
            self._inflight.add(target.key)
        try:
            return self._run(alert, target)
        finally:
            with self._lock:
                self._inflight.discard(target.key)

    def _finish(self, inc: Incident, ctx: Context | None) -> Incident:
        try:
            inc.summary = self.brain.summarize(inc, ctx)
        except Exception:
            inc.summary = template_summary(inc)
        inc.log(f"outcome: {inc.outcome}")
        INCIDENTS.labels(inc.decision.action if inc.decision else "none", inc.outcome).inc()
        self.store.save(inc, ctx)
        log.info("incident %s %s: %s", inc.id, inc.target, inc.outcome)
        return inc

    def _run(self, alert: Alert, target) -> Incident | None:
        inc = Incident(target=str(target), alert_name=alert.labels.get("alertname", "unknown"),
                       dry_run=self.s.dry_run)
        inc.log(f"alert received for {target}")
        ctx: Context | None = None
        try:
            if (reason := self.guard.precheck(target)) is not None:
                log.info("skipping %s: %s", target, reason)
                return None  # quiet: duplicates/cooldown are not new incidents

            ctx = self.ctxb.build(target, alert)
            inc.log(f"context collected: {len(ctx.pods)} pods, {len(ctx.events)} events, {len(ctx.logs)} log sources")

            decision = self.brain.decide(ctx)
            inc.decision = decision
            inc.log(f"decision [{decision.source}]: {decision.action} (confidence {decision.confidence:.2f}) - {decision.root_cause}")

            result = self.guard.check(target, ctx, decision)
            decision = inc.decision = result.decision
            if not result.allowed:
                inc.guardrail_note = result.reason
                inc.outcome = "escalated"
                inc.log(f"guardrail blocked action: {result.reason}")
                return self._finish(inc, ctx)
            if decision.action == "escalate":
                inc.outcome = "escalated"
                inc.log("decision is to escalate to a human; no automatic action")
                return self._finish(inc, ctx)

            inc.executed_action = self.exec.execute(target, decision)
            inc.log(f"executed: {inc.executed_action}")
            if self.s.dry_run:
                inc.outcome = "dry_run"
                return self._finish(inc, ctx)

            self.guard.record(target)
            ok, why = self.verifier.wait_for_recovery(target, decision)
            inc.outcome = "recovered" if ok else "not_recovered"
            inc.log(f"verification: {why}")
            if not ok:
                inc.guardrail_note = "automatic remediation did not restore health; human attention needed"
            return self._finish(inc, ctx)
        except Exception as e:
            log.exception("incident for %s failed", target)
            inc.outcome = "error"
            inc.log(f"error: {type(e).__name__}: {e}")
            return self._finish(inc, ctx)
