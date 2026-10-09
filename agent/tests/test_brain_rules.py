from conftest import make_ctx
from healer.brain import RulesBrain


def test_crashloop_after_recent_rollout_rolls_back(settings):
    d = RulesBrain(settings).decide(make_ctx("PodCrashLooping", waiting="CrashLoopBackOff", rollout_age=120))
    assert d.action == "rollback"


def test_crashloop_without_recent_change_restarts(settings):
    d = RulesBrain(settings).decide(make_ctx("PodCrashLooping", waiting="CrashLoopBackOff", rollout_age=99999))
    assert d.action == "restart"


def test_dependency_error_in_logs_escalates(settings):
    ctx = make_ctx("PodCrashLooping", waiting="CrashLoopBackOff",
                   logs={"p": "Error: connect ECONNREFUSED 10.0.0.5:5432"})
    assert RulesBrain(settings).decide(ctx).action == "escalate"


def test_image_pull_with_history_rolls_back_without_escalates(settings):
    ctx = make_ctx("PodImagePullFailure", waiting="ImagePullBackOff")
    assert RulesBrain(settings).decide(ctx).action == "rollback"
    ctx = make_ctx("PodImagePullFailure", waiting="ImagePullBackOff", prev=False)
    assert RulesBrain(settings).decide(ctx).action == "escalate"


def test_oom_recent_rolls_back_old_restarts(settings):
    assert RulesBrain(settings).decide(make_ctx("PodOOMKilled", terminated="OOMKilled")).action == "rollback"
    d = RulesBrain(settings).decide(make_ctx("PodOOMKilled", terminated="OOMKilled", rollout_age=99999))
    assert d.action == "restart"


def test_high_cpu_scales_up_with_cap(settings):
    settings.max_replicas = 3
    d = RulesBrain(settings).decide(make_ctx("HighCPU", desired=2))
    assert d.action == "scale_up" and d.replicas == 3


def test_unknown_pattern_escalates(settings):
    assert RulesBrain(settings).decide(make_ctx("Weird")).action == "escalate"
