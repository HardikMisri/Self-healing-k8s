from __future__ import annotations

import logging

from .kube import KubeClient
from .models import Decision, Target

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, kube: KubeClient, dry_run: bool):
        self.kube, self.dry_run = kube, dry_run

    def execute(self, target: Target, decision: Decision) -> str:
        label = {"restart": "restart", "rollback": "rollback", "scale_up": f"scale to {decision.replicas}"}[decision.action]
        if self.dry_run:
            return f"[dry-run] would {label} {target}"
        if decision.action == "restart":
            return self.kube.restart(target)
        if decision.action == "rollback":
            return self.kube.rollback(target)
        if decision.action == "scale_up":
            assert decision.replicas is not None
            return self.kube.scale(target, decision.replicas)
        raise ValueError(f"cannot execute action {decision.action}")
