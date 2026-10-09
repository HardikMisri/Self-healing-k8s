"""Deterministic safety checks that run AFTER the LLM and BEFORE the cluster is touched."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .kube import scale_step  # noqa: F401  (re-exported for callers)
from .models import Context, Decision, Target


@dataclass
class GuardrailResult:
    allowed: bool
    decision: Decision
    reason: str | None = None


class Guardrails:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.s = settings
        self.clock = clock
        self._history: dict[tuple[str, str], list[float]] = defaultdict(list)

    # -- history ---------------------------------------------------------
    def record(self, target: Target) -> None:
        self._history[target.key].append(self.clock())

    def precheck(self, target: Target) -> str | None:
        """Cheap checks done BEFORE spending an LLM call."""
        if target.namespace not in self.s.namespaces:
            return f"namespace '{target.namespace}' is not in the allowlist"
        now = self.clock()
        hist = [t for t in self._history[target.key] if now - t < 3600]
        self._history[target.key] = hist
        if hist and now - hist[-1] < self.s.cooldown_seconds:
            return f"cooldown: last action {int(now - hist[-1])}s ago (< {self.s.cooldown_seconds}s)"
        if len(hist) >= self.s.max_actions_per_hour:
            return f"hourly cap reached ({self.s.max_actions_per_hour} actions); a human should look"
        return None

    # -- decision validation --------------------------------------------
    def check(self, target: Target, ctx: Context, decision: Decision) -> GuardrailResult:
        def block(reason: str) -> GuardrailResult:
            return GuardrailResult(False, decision, reason)

        if target.namespace not in self.s.namespaces:
            return block(f"namespace '{target.namespace}' is not in the allowlist")
        if self.s.require_opt_in_label and ctx.deployment.labels.get(self.s.opt_in_label) != "enabled":
            return block(f"deployment lacks opt-in label {self.s.opt_in_label}=enabled")
        if decision.action == "escalate":
            return GuardrailResult(True, decision)
        if decision.confidence < self.s.min_confidence:
            return block(f"confidence {decision.confidence:.2f} below threshold {self.s.min_confidence}")
        if (reason := self.precheck(target)) is not None:
            return block(reason)

        d = ctx.deployment
        if decision.action == "rollback" and not d.previous_revision_available:
            return block("no earlier distinct revision to roll back to")
        if decision.action == "scale_up":
            if d.hpa_managed:
                return block("deployment is managed by an HPA; refusing to fight the autoscaler")
            wanted = decision.replicas or d.desired + 1
            wanted = min(wanted, self.s.max_replicas)
            if wanted <= d.desired:
                return block(f"already at/above max replicas ({self.s.max_replicas})")
            decision = decision.model_copy(update={"replicas": wanted})
        return GuardrailResult(True, decision)
