from conftest import make_ctx
from healer.executor import Executor
from healer.guardrails import Guardrails
from healer.incidents import IncidentStore
from healer.models import Alert, Decision, Target
from healer.orchestrator import Orchestrator


class FakeKube:
    def __init__(self): self.calls = []
    def resolve_target(self, labels): return Target(namespace=labels["namespace"], deployment="demo-app")
    def restart(self, t): self.calls.append(("restart", t.deployment)); return "restarted"
    def rollback(self, t): self.calls.append(("rollback", t.deployment)); return "rolled back"
    def scale(self, t, n): self.calls.append(("scale", n)); return f"scaled {n}"


class FakeCtx:
    def __init__(self, **kw): self.kw = kw
    def build(self, target, alert): return make_ctx(alert.labels["alertname"], **self.kw)


class FakeBrain:
    def __init__(self, decision): self.d = decision
    def decide(self, ctx): return self.d
    def summarize(self, inc, ctx): return "summary"


class FakeVerifier:
    def __init__(self, ok=True): self.ok = ok
    def wait_for_recovery(self, t, d): return self.ok, "fake"


def build(settings, decision, kube=None, ctx=None, ok=True, tmp="/tmp/healer-orch"):
    kube = kube or FakeKube()
    return kube, Orchestrator(settings, kube, ctx or FakeCtx(waiting="CrashLoopBackOff"), FakeBrain(decision),
                              Guardrails(settings), Executor(kube, settings.dry_run), FakeVerifier(ok),
                              IncidentStore(tmp))


def alert(name="PodCrashLooping", ns="demo"):
    return Alert(labels={"alertname": name, "namespace": ns, "pod": "demo-app-abc-123"})


RB = Decision(action="rollback", root_cause="bad deploy", confidence=0.9, reasoning="r", source="rules")


def test_happy_path_recovers(settings):
    kube, o = build(settings, RB)
    inc = o.handle_alert(alert())
    assert inc.outcome == "recovered" and kube.calls == [("rollback", "demo-app")]
    assert inc.summary == "summary" and any("verification" in e.message for e in inc.timeline)


def test_not_recovered_is_reported(settings):
    _, o = build(settings, RB, ok=False)
    assert o.handle_alert(alert()).outcome == "not_recovered"


def test_dry_run_never_touches_cluster(settings):
    settings.dry_run = True
    kube, o = build(settings, RB)
    inc = o.handle_alert(alert())
    assert inc.outcome == "dry_run" and kube.calls == [] and "[dry-run]" in inc.executed_action


def test_guardrail_block_escalates_without_acting(settings):
    kube, o = build(settings, RB, ctx=FakeCtx(prev=False))
    inc = o.handle_alert(alert())
    assert inc.outcome == "escalated" and kube.calls == [] and "roll back" in inc.guardrail_note


def test_llm_escalate_does_nothing(settings):
    kube, o = build(settings, Decision(action="escalate", root_cause="db down", confidence=0.9, reasoning="r"))
    assert o.handle_alert(alert()).outcome == "escalated" and kube.calls == []


def test_namespace_outside_allowlist_ignored(settings):
    kube, o = build(settings, RB)
    assert o.handle_alert(alert(ns="kube-system")) is None and kube.calls == []


def test_cooldown_blocks_second_action_quietly(settings):
    kube, o = build(settings, RB)
    assert o.handle_alert(alert()).outcome == "recovered"
    assert o.handle_alert(alert("PodOOMKilled")) is None
    assert len(kube.calls) == 1


def test_scale_action_executes_with_clamped_replicas(settings):
    settings.max_replicas = 3
    d = Decision(action="scale_up", replicas=10, root_cause="load", confidence=0.8, reasoning="r")
    kube, o = build(settings, d, ctx=FakeCtx(desired=2))
    inc = o.handle_alert(alert("HighCPU"))
    assert kube.calls == [("scale", 3)] and inc.outcome == "recovered"
