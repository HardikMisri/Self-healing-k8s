from conftest import make_ctx
from healer.guardrails import Guardrails
from healer.models import Decision, Target

T = Target(namespace="demo", deployment="demo-app")


def dec(action="restart", conf=0.9, replicas=None):
    return Decision(action=action, replicas=replicas, root_cause="x", confidence=conf, reasoning="y")


def test_blocks_namespace_outside_allowlist(settings):
    r = Guardrails(settings).check(Target(namespace="prod", deployment="a"), make_ctx(ns="prod"), dec())
    assert not r.allowed and "allowlist" in r.reason


def test_blocks_without_opt_in_label(settings):
    r = Guardrails(settings).check(T, make_ctx(labels={}), dec())
    assert not r.allowed and "opt-in" in r.reason


def test_opt_in_can_be_disabled(settings):
    settings.require_opt_in_label = False
    assert Guardrails(settings).check(T, make_ctx(labels={}), dec()).allowed


def test_blocks_low_confidence(settings):
    assert not Guardrails(settings).check(T, make_ctx(), dec(conf=0.2)).allowed


def test_escalate_always_allowed_even_low_confidence(settings):
    assert Guardrails(settings).check(T, make_ctx(), dec("escalate", conf=0.1)).allowed


def test_cooldown_and_hourly_cap(settings):
    now = [0.0]
    g = Guardrails(settings, clock=lambda: now[0])
    g.record(T)
    now[0] = 10
    assert "cooldown" in g.precheck(T)
    now[0] = 400
    assert g.precheck(T) is None
    g.record(T); now[0] = 800; g.record(T); now[0] = 1200
    assert "hourly cap" in g.precheck(T)


def test_rollback_needs_previous_revision(settings):
    r = Guardrails(settings).check(T, make_ctx(prev=False), dec("rollback"))
    assert not r.allowed and "roll back" in r.reason


def test_scale_refused_for_hpa_managed(settings):
    r = Guardrails(settings).check(T, make_ctx(hpa=True), dec("scale_up", replicas=3))
    assert not r.allowed and "HPA" in r.reason


def test_scale_is_clamped_to_max(settings):
    settings.max_replicas = 4
    r = Guardrails(settings).check(T, make_ctx(desired=2), dec("scale_up", replicas=50))
    assert r.allowed and r.decision.replicas == 4


def test_scale_blocked_at_max(settings):
    settings.max_replicas = 2
    assert not Guardrails(settings).check(T, make_ctx(desired=2), dec("scale_up", replicas=3)).allowed
