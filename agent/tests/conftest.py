import pytest

from healer.config import Settings
from healer.models import Context, DeploymentInfo, PodInfo


@pytest.fixture
def settings():
    return Settings(dry_run=False, allowed_namespaces="demo", incident_dir="/tmp/healer-test-incidents",
                    verify_timeout_seconds=30, verify_interval_seconds=0, verify_stable_checks=2,
                    anthropic_api_key=None, llm_provider="rules")


def make_ctx(alert="PodCrashLooping", *, waiting=None, terminated=None, rollout_age=60, prev=True,
             hpa=False, desired=2, logs=None, labels=None, ns="demo"):
    dep = DeploymentInfo(
        name="demo-app", namespace=ns, labels=labels if labels is not None else {"self-healing": "enabled"},
        desired=desired, ready=desired, available=desired, updated=desired, revision=3,
        rollout_age_seconds=rollout_age, previous_revision_available=prev, hpa_managed=hpa,
    )
    pod = PodInfo(name="demo-app-abc-123", phase="Running", ready=waiting is None, restarts=4,
                  waiting_reason=waiting, last_terminated_reason=terminated)
    return Context(alert_name=alert, deployment=dep, pods=[pod], logs=logs or {},
                   metrics={"cpu_ratio_of_limit": 0.97})
