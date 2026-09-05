from __future__ import annotations

import asyncio

import pytest

import astrbot_plugin_companion_phone.backend.redroid as redroid_mod
from astrbot_plugin_companion_phone.backend.redroid import RedroidBackend
from astrbot_plugin_companion_phone.errors import BackendError

from helpers import make_cfg


class DockerScript:
    """按调用顺序 scripted 的 docker CLI 替身，记录全部 argv。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.argv: list[list[str]] = []

    async def __call__(self, *args, **kwargs):
        self.argv.append(list(args))
        self._action(args)  # 断言用；此处仅消耗响应
        response = self.responses.pop(0) if self.responses else (0, "", "")
        rc, out, err = response
        return rc, out, err

    @staticmethod
    def _action(args):
        for flag in ("version", "inspect", "run", "start", "stop", "exec"):
            if flag in args:
                return flag
        return "?"


@pytest.fixture
def backend():
    cfg = make_cfg(
        REDROID_DOCKER_ARGS=["--memory=3g"],
        REDROID_EXTRA_ARGS=["androidboot.redroid_gpu_mode=host"],
    )
    return RedroidBackend(cfg)


def _patch(backend, monkeypatch, script):
    async def fake_docker(*args, timeout=30.0):
        return await script(*args, timeout=timeout)

    monkeypatch.setattr(backend, "_docker", fake_docker)
    return script


def test_run_args_order(backend, monkeypatch):
    """docker args 必须在镜像名之前，redroid boot 参数必须在镜像名之后。"""
    script = DockerScript(
        [(0, "", ""), (1, "", "no such object"), (0, "id", ""), (0, "1", "")]
    )
    calls = []

    async def recorder(*args, timeout=30.0):
        calls.append(list(args))
        return await script(*args, timeout=timeout)

    monkeypatch.setattr(backend, "_docker", recorder)
    asyncio.run(backend.ensure_ready())

    run_cmd = next(c for c in calls if "run" in c)
    image_idx = run_cmd.index("redroid/redroid:test")
    assert (
        run_cmd[image_idx - 1] == "--memory=3g" or "--memory=3g" in run_cmd[:image_idx]
    )
    assert "androidboot.redroid_gpu_mode=host" in run_cmd[image_idx + 1 :]
    assert run_cmd.count("--privileged") == 1
    assert "127.0.0.1:26655:5555" in run_cmd


def test_ensure_ready_state_machine(backend, monkeypatch):
    # missing → create；exited → start；running → 不重复创建
    script = DockerScript(
        [
            (0, "", ""),  # version
            (1, "", "no such object"),  # inspect → missing
            (0, "id", ""),  # run
            (0, "1", ""),  # getprop
        ]
    )
    _patch(backend, monkeypatch, script)
    asyncio.run(backend.ensure_ready())
    assert script._action(script.argv[1]) == "inspect"
    assert script._action(script.argv[2]) == "run"

    script2 = DockerScript([(0, "", ""), (0, "exited", ""), (0, "", ""), (0, "1", "")])
    _patch(backend, monkeypatch, script2)
    asyncio.run(backend.ensure_ready())
    assert script2._action(script2.argv[2]) == "start"

    script3 = DockerScript([(0, "", ""), (0, "running", ""), (0, "1", "")])
    _patch(backend, monkeypatch, script3)
    asyncio.run(backend.ensure_ready())
    assert all(script3._action(c) != "run" for c in script3.argv)


def test_ensure_ready_self_heals_stopped_container(backend, monkeypatch):
    """回归锚：serial 已缓存时也要核实容器状态（外部 stop 后能自愈）。"""
    backend._serial = "127.0.0.1:26655"
    script = DockerScript(
        [
            (0, "", ""),  # version
            (0, "exited", ""),  # inspect → exited
            (0, "", ""),  # start
            (0, "1", ""),  # getprop
        ]
    )
    _patch(backend, monkeypatch, script)
    state = asyncio.run(backend.ensure_ready())
    assert state.ready
    assert script._action(script.argv[2]) == "start"


def test_docker_binary_missing_maps_to_docker_missing(backend, monkeypatch):
    """回归锚：docker 二进制缺失必须归一为 E_DOCKER_MISSING，不得裸抛 FileNotFoundError。"""

    async def missing_exec(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "docker")

    monkeypatch.setattr(redroid_mod.asyncio, "create_subprocess_exec", missing_exec)
    with pytest.raises(BackendError) as excinfo:
        asyncio.run(backend.ensure_ready())
    assert excinfo.value.code == "docker_missing"


def test_shutdown_semantics(backend, monkeypatch):
    stopped = []

    async def fake_docker(*args, timeout=30.0):
        stopped.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(backend, "_docker", fake_docker)
    backend._serial = "127.0.0.1:26655"
    asyncio.run(backend.shutdown(stop_device=False))
    assert stopped == []  # 常规卸载不杀容器
    assert backend._serial is None
    backend._serial = "127.0.0.1:26655"
    asyncio.run(backend.shutdown(stop_device=True))
    assert stopped and stopped[0][0] == "stop"
