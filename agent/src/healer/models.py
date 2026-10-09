from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- Alertmanager webhook payload (only the fields we use) ----
class Alert(BaseModel):
    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    fingerprint: str | None = None


class AlertmanagerPayload(BaseModel):
    status: str = "firing"
    alerts: list[Alert] = Field(default_factory=list)


# ---- cluster snapshot ----
class Target(BaseModel):
    namespace: str
    deployment: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.namespace, self.deployment)

    def __str__(self) -> str:
        return f"{self.namespace}/{self.deployment}"


class PodInfo(BaseModel):
    name: str
    phase: str
    ready: bool
    restarts: int = 0
    waiting_reason: str | None = None
    last_terminated_reason: str | None = None
    last_exit_code: int | None = None
    age_seconds: int = 0


class DeploymentInfo(BaseModel):
    name: str
    namespace: str
    labels: dict[str, str] = Field(default_factory=dict)
    desired: int = 0
    ready: int = 0
    available: int = 0
    updated: int = 0
    revision: int | None = None
    rollout_age_seconds: int | None = None
    previous_revision_available: bool = False
    hpa_managed: bool = False
    image: str | None = None


class Context(BaseModel):
    alert_name: str
    alert_labels: dict[str, str] = Field(default_factory=dict)
    alert_summary: str = ""
    deployment: DeploymentInfo
    pods: list[PodInfo] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    logs: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float | None] = Field(default_factory=dict)


# ---- decision ----
Action = Literal["restart", "rollback", "scale_up", "escalate"]


class Decision(BaseModel):
    action: Action
    replicas: int | None = None  # only for scale_up
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    source: str = "llm"  # "llm" | "rules"


# ---- incident record ----
Outcome = Literal[
    "recovered", "not_recovered", "escalated", "dry_run", "skipped", "error"
]


class TimelineEvent(BaseModel):
    ts: str = Field(default_factory=_now)
    message: str


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = Field(default_factory=_now)
    target: str
    alert_name: str
    decision: Decision | None = None
    executed_action: str | None = None
    guardrail_note: str | None = None
    dry_run: bool = False
    outcome: Outcome = "skipped"
    summary: str = ""
    timeline: list[TimelineEvent] = Field(default_factory=list)

    def log(self, message: str) -> None:
        self.timeline.append(TimelineEvent(message=message))
