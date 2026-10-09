"""Thin wrapper over the Kubernetes API: read cluster state, perform the 3 remediations."""
from __future__ import annotations

import copy
import logging
import math
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config

from .models import DeploymentInfo, PodInfo, Target

log = logging.getLogger(__name__)

REVISION_ANN = "deployment.kubernetes.io/revision"
RESTART_ANN = "kubectl.kubernetes.io/restartedAt"
BAD_WAITING = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "CreateContainerError",
    "InvalidImageName",
}


def load_kube_config() -> None:
    try:
        config.load_incluster_config()
        log.info("loaded in-cluster kube config")
    except config.ConfigException:
        config.load_kube_config()
        log.info("loaded local kubeconfig")


def _age(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def _normalize_template(template: dict[str, Any]) -> dict[str, Any]:
    """Strip fields that differ between ReplicaSets even when the spec is identical."""
    t = copy.deepcopy(template)
    meta = t.get("metadata") or {}
    (meta.get("labels") or {}).pop("pod-template-hash", None)
    (meta.get("annotations") or {}).pop(RESTART_ANN, None)
    if meta.get("annotations") == {}:
        meta.pop("annotations")
    t["metadata"] = meta
    t.get("metadata", {}).pop("creationTimestamp", None)
    return t


class KubeClient:
    def __init__(self, core=None, apps=None, autoscaling=None, api_client=None):
        self.core = core or client.CoreV1Api()
        self.apps = apps or client.AppsV1Api()
        self.autoscaling = autoscaling or client.AutoscalingV2Api()
        self.api_client = api_client or client.ApiClient()

    # ------------------------------------------------------------------ reads
    def resolve_target(self, labels: dict[str, str]) -> Target | None:
        """Alert labels -> Deployment. Accepts `deployment`, or walks pod -> ReplicaSet -> Deployment."""
        ns = labels.get("namespace")
        if not ns:
            return None
        if labels.get("deployment"):
            return Target(namespace=ns, deployment=labels["deployment"])
        pod_name = labels.get("pod")
        if not pod_name:
            return None
        pod = self.core.read_namespaced_pod(pod_name, ns)
        for ref in pod.metadata.owner_references or []:
            if ref.kind == "ReplicaSet":
                rs = self.apps.read_namespaced_replica_set(ref.name, ns)
                for rref in rs.metadata.owner_references or []:
                    if rref.kind == "Deployment":
                        return Target(namespace=ns, deployment=rref.name)
        return None  # StatefulSet/DaemonSet/bare pod: not supported -> caller escalates

    def get_deployment(self, t: Target):
        return self.apps.read_namespaced_deployment(t.deployment, t.namespace)

    def _selector(self, dep) -> str:
        return ",".join(f"{k}={v}" for k, v in (dep.spec.selector.match_labels or {}).items())

    def revisions(self, t: Target) -> list:
        """ReplicaSets owned by the deployment, newest revision first."""
        dep = self.get_deployment(t)
        rss = self.apps.list_namespaced_replica_set(
            t.namespace, label_selector=self._selector(dep)
        ).items
        owned = [
            rs
            for rs in rss
            if any(r.uid == dep.metadata.uid for r in (rs.metadata.owner_references or []))
        ]

        def rev(rs) -> int:
            return int((rs.metadata.annotations or {}).get(REVISION_ANN, "0"))

        return sorted(owned, key=rev, reverse=True)

    def rollback_target(self, t: Target):
        """Newest earlier ReplicaSet whose pod template actually differs from the current one.

        A plain `restart` creates a new ReplicaSet with an identical spec; rolling back to that
        would be a no-op, so we skip templates that only differ by restartedAt/pod-template-hash.
        """
        dep = self.get_deployment(t)
        current = _normalize_template(self.api_client.sanitize_for_serialization(dep.spec.template))
        for rs in self.revisions(t)[1:]:
            cand = _normalize_template(self.api_client.sanitize_for_serialization(rs.spec.template))
            if cand != current:
                return rs
        return None

    def deployment_info(self, t: Target) -> DeploymentInfo:
        dep = self.get_deployment(t)
        revs = self.revisions(t)
        rollout_age = None
        if revs:
            rollout_age = _age(revs[0].metadata.creation_timestamp)
        containers = dep.spec.template.spec.containers or []
        hpa_managed = False
        try:
            for h in self.autoscaling.list_namespaced_horizontal_pod_autoscaler(t.namespace).items:
                ref = h.spec.scale_target_ref
                if ref.kind == "Deployment" and ref.name == t.deployment:
                    hpa_managed = True
        except Exception as e:  # RBAC may not allow it; stay conservative below
            log.warning("could not list HPAs: %s", e)
            hpa_managed = True
        st = dep.status
        return DeploymentInfo(
            name=t.deployment,
            namespace=t.namespace,
            labels=dep.metadata.labels or {},
            desired=dep.spec.replicas or 0,
            ready=st.ready_replicas or 0,
            available=st.available_replicas or 0,
            updated=st.updated_replicas or 0,
            revision=int((dep.metadata.annotations or {}).get(REVISION_ANN, "0") or 0) or None,
            rollout_age_seconds=rollout_age,
            previous_revision_available=self.rollback_target(t) is not None,
            hpa_managed=hpa_managed,
            image=containers[0].image if containers else None,
        )

    def pods(self, t: Target) -> list[PodInfo]:
        dep = self.get_deployment(t)
        items = self.core.list_namespaced_pod(t.namespace, label_selector=self._selector(dep)).items
        out: list[PodInfo] = []
        for p in items:
            statuses = p.status.container_statuses or []
            worst = max(statuses, key=lambda s: s.restart_count or 0) if statuses else None
            waiting = terminated = exit_code = None
            for s in statuses:
                if s.state and s.state.waiting and s.state.waiting.reason:
                    waiting = s.state.waiting.reason
                if s.last_state and s.last_state.terminated:
                    terminated = s.last_state.terminated.reason
                    exit_code = s.last_state.terminated.exit_code
                elif s.state and s.state.terminated and not terminated:
                    terminated = s.state.terminated.reason
                    exit_code = s.state.terminated.exit_code
            out.append(
                PodInfo(
                    name=p.metadata.name,
                    phase=p.status.phase or "Unknown",
                    ready=bool(statuses) and all(s.ready for s in statuses),
                    restarts=(worst.restart_count if worst else 0) or 0,
                    waiting_reason=waiting,
                    last_terminated_reason=terminated,
                    last_exit_code=exit_code,
                    age_seconds=_age(p.metadata.creation_timestamp) or 0,
                )
            )
        return out

    def events(self, t: Target, pod_names: list[str], limit: int = 15) -> list[str]:
        wanted = set(pod_names) | {t.deployment}
        try:
            wanted |= {rs.metadata.name for rs in self.revisions(t)}
            items = self.core.list_namespaced_event(t.namespace).items
        except Exception as e:
            log.warning("could not list events: %s", e)
            return []
        rel = [e for e in items if e.involved_object and e.involved_object.name in wanted]

        def ts(e):
            return e.last_timestamp or e.event_time or e.metadata.creation_timestamp or datetime.min.replace(tzinfo=timezone.utc)

        rel.sort(key=ts)
        return [
            f"[{e.type}] {e.involved_object.kind}/{e.involved_object.name}: {e.reason}: {(e.message or '').strip()[:300]}"
            for e in rel[-limit:]
        ]

    def pod_log(self, namespace: str, pod: str, tail: int, previous: bool = False) -> str:
        try:
            return self.core.read_namespaced_pod_log(
                pod, namespace, tail_lines=tail, previous=previous
            )
        except Exception as e:  # no previous container, pod gone, container creating...
            log.debug("log read failed for %s (previous=%s): %s", pod, previous, e)
            return ""

    # ----------------------------------------------------------------- writes
    def restart(self, t: Target) -> str:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        body = {"spec": {"template": {"metadata": {"annotations": {RESTART_ANN: now}}}}}
        self.apps.patch_namespaced_deployment(t.deployment, t.namespace, body)
        return f"rolling restart of {t}"

    def rollback(self, t: Target) -> str:
        rs = self.rollback_target(t)
        if rs is None:
            raise RuntimeError(f"no earlier distinct revision to roll back to for {t}")
        template = self.api_client.sanitize_for_serialization(rs.spec.template)
        (template.get("metadata", {}).get("labels") or {}).pop("pod-template-hash", None)
        # JSON patch (list body) == what `kubectl rollout undo` does.
        patch = [{"op": "replace", "path": "/spec/template", "value": template}]
        self.apps.patch_namespaced_deployment(t.deployment, t.namespace, patch)
        rev = (rs.metadata.annotations or {}).get(REVISION_ANN, "?")
        return f"rolled {t} back to revision {rev}"

    def scale(self, t: Target, replicas: int) -> str:
        self.apps.patch_namespaced_deployment_scale(
            t.deployment, t.namespace, {"spec": {"replicas": replicas}}
        )
        return f"scaled {t} to {replicas} replicas"


def scale_step(current: int, max_replicas: int) -> int:
    """+50% (at least +1), capped."""
    return min(max_replicas, current + max(1, math.ceil(current * 0.5)))
