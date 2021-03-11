from typing import List

from kubernetes.client.models import V1Container, V1PodSpec, V1VolumeMount

from flytekit import Resources, dynamic, task
from flytekit.core import context_manager
from flytekit.extend import ExecutionState, Image, ImageConfig, SerializationSettings
from plugins.pod.flytekitplugins.pod.task import Pod, PodFunctionTask


def get_pod_spec():
    a_container = V1Container(name="a container",)
    a_container.command = ["fee", "fi", "fo", "fum"]
    a_container.volume_mounts = [V1VolumeMount(name="volume mount", mount_path="some/where",)]

    pod_spec = V1PodSpec(restart_policy="OnFailure", containers=[a_container, V1Container(name="another container")])
    return pod_spec


def test_pod_task():
    pod = Pod(pod_spec=get_pod_spec(), primary_container_name="a container")

    @task(task_config=pod, requests=Resources(cpu="10"), limits=Resources(gpu="2"), environment={"FOO": "bar"})
    def simple_pod_task(i: int):
        pass

    assert isinstance(simple_pod_task, PodFunctionTask)
    assert simple_pod_task.task_config == pod

    default_img = Image(name="default", fqn="test", tag="tag")

    custom = simple_pod_task.get_custom(
        SerializationSettings(
            project="project",
            domain="domain",
            version="version",
            env={"FOO": "baz"},
            image_config=ImageConfig(default_image=default_img, images=[default_img]),
        )
    )
    assert custom["restart_policy"] == "OnFailure"
    assert len(custom["containers"]) == 2
    primary_container = custom["containers"][0]
    assert primary_container["name"] == "a container"
    assert primary_container["args"] == [
        "pyflyte-execute",
        "--task-module",
        "plugins.tests.pod.test_pod",
        "--task-name",
        "simple_pod_task",
        "--inputs",
        "{{.input}}",
        "--output-prefix",
        "{{.outputPrefix}}",
        "--raw-output-data-prefix",
        "{{.rawOutputDataPrefix}}",
    ]
    assert primary_container["volume_mounts"][0]["mount_path"] == "some/where"
    assert primary_container["volume_mounts"][0]["name"] == "volume mount"
    assert primary_container["resources"] == {
        "requests": {"cpu": "10"},
        "limits": {"gpu": "2"},
    }
    assert primary_container["env"] == [{"name": "FOO", "value": "bar", "value_from": None}]
    assert custom["containers"][1]["name"] == "another container"

    config = simple_pod_task.get_config(
        SerializationSettings(
            project="project",
            domain="domain",
            version="version",
            env={"FOO": "baz"},
            image_config=ImageConfig(default_image=default_img, images=[default_img]),
        )
    )
    assert config["primary_container_name"] == "a container"


def test_dynamic_pod_task():
    dynamic_pod = Pod(pod_spec=get_pod_spec(), primary_container_name="a container")

    @task
    def t1(a: int) -> int:
        return a + 10

    @dynamic(
        task_config=dynamic_pod, requests=Resources(cpu="10"), limits=Resources(gpu="2"), environment={"FOO": "bar"}
    )
    def dynamic_pod_task(a: int) -> List[int]:
        s = []
        for i in range(a):
            s.append(t1(a=i))
        return s

    assert isinstance(dynamic_pod_task, PodFunctionTask)
    default_img = Image(name="default", fqn="test", tag="tag")

    custom = dynamic_pod_task.get_custom(
        SerializationSettings(
            project="project",
            domain="domain",
            version="version",
            env={"FOO": "baz"},
            image_config=ImageConfig(default_image=default_img, images=[default_img]),
        )
    )
    assert len(custom["containers"]) == 2
    primary_container = custom["containers"][0]
    assert isinstance(dynamic_pod_task.task_config, Pod)
    assert primary_container["resources"] == {
        "requests": {"cpu": "10"},
        "limits": {"gpu": "2"},
    }

    config = dynamic_pod_task.get_config(
        SerializationSettings(
            project="project",
            domain="domain",
            version="version",
            env={"FOO": "baz"},
            image_config=ImageConfig(default_image=default_img, images=[default_img]),
        )
    )
    assert config["primary_container_name"] == "a container"

    with context_manager.FlyteContext.current_context().new_serialization_settings(
        serialization_settings=SerializationSettings(
            project="test_proj",
            domain="test_domain",
            version="abc",
            image_config=ImageConfig(Image(name="name", fqn="image", tag="name")),
            env={},
        )
    ) as ctx:
        with ctx.new_execution_context(mode=ExecutionState.Mode.TASK_EXECUTION) as ctx:
            dynamic_job_spec = dynamic_pod_task.compile_into_workflow(ctx, dynamic_pod_task._task_function, a=5)
            assert len(dynamic_job_spec._nodes) == 5
