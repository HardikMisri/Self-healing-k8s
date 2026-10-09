"""Rollback target selection is the subtle part: restarts create identical ReplicaSets."""
from unittest.mock import MagicMock

from kubernetes import client

from healer.kube import KubeClient, REVISION_ANN, RESTART_ANN
from healer.models import Target

T = Target(namespace="demo", deployment="demo-app")


def template(env="false", restarted=None, hash_="h"):
    ann = {RESTART_ANN: restarted} if restarted else None
    return client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "demo-app", "pod-template-hash": hash_}, annotations=ann),
        spec=client.V1PodSpec(containers=[client.V1Container(
            name="app", image="demo-app:dev", env=[client.V1EnvVar(name="CRASH_ON_START", value=env)])]),
    )


def rs(rev, tpl):
    return client.V1ReplicaSet(
        metadata=client.V1ObjectMeta(name=f"rs{rev}", annotations={REVISION_ANN: str(rev)},
                                     owner_references=[client.V1OwnerReference(
                                         api_version="apps/v1", kind="Deployment", name="demo-app", uid="u1")]),
        spec=client.V1ReplicaSetSpec(selector=client.V1LabelSelector(match_labels={"app": "demo-app"}), template=tpl))


def kube_with(current_tpl, replica_sets):
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="demo-app", uid="u1"),
        spec=client.V1DeploymentSpec(selector=client.V1LabelSelector(match_labels={"app": "demo-app"}),
                                     template=current_tpl))
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = dep
    apps.list_namespaced_replica_set.return_value = client.V1ReplicaSetList(items=replica_sets)
    return KubeClient(core=MagicMock(), apps=apps, autoscaling=MagicMock(), api_client=client.ApiClient()), apps


def test_rolls_back_to_previous_distinct_template():
    k, _ = kube_with(template("true"), [rs(1, template("false", hash_="a")), rs(2, template("true", hash_="b"))])
    assert k.rollback_target(T).metadata.name == "rs1"


def test_skips_restart_only_revisions():
    # rev1 good, rev2 bad, rev3 = restart of bad (identical spec) -> must still go back to rev1
    reps = [rs(1, template("false", hash_="a")), rs(2, template("true", hash_="b")),
            rs(3, template("true", restarted="2026-01-01T00:00:00+00:00", hash_="c"))]
    k, _ = kube_with(template("true", restarted="2026-01-01T00:00:00+00:00", hash_="c"), reps)
    assert k.rollback_target(T).metadata.name == "rs1"


def test_no_target_when_all_history_identical():
    k, _ = kube_with(template("false", hash_="b"), [rs(1, template("false", hash_="a")), rs(2, template("false", hash_="b"))])
    assert k.rollback_target(T) is None


def test_rollback_sends_json_patch_without_pod_template_hash():
    k, apps = kube_with(template("true"), [rs(1, template("false", hash_="a")), rs(2, template("true", hash_="b"))])
    k.rollback(T)
    patch = apps.patch_namespaced_deployment.call_args.args[2]
    assert isinstance(patch, list) and patch[0]["op"] == "replace" and patch[0]["path"] == "/spec/template"
    assert "pod-template-hash" not in patch[0]["value"]["metadata"]["labels"]
    assert patch[0]["value"]["spec"]["containers"][0]["env"][0]["value"] == "false"
