from __future__ import annotations

import asyncio
import time

from ..constants import E_CONTAINER_FAILED, E_DOCKER_MISSING, MODE_REDROID
from ..errors import BackendError
from .base import BackendState, DeviceBackend

_DOCKER_TIMEOUT_SECONDS = 30.0
_RUN_TIMEOUT_SECONDS = 120.0
_BOOT_TIMEOUT_SECONDS = 300.0
_BOOT_POLL_INTERVAL = 5.0


class RedroidBackend(DeviceBackend):
    """通过 docker CLI 管理 Redroid 容器，产出 127.0.0.1:<port> 的 ADB serial。

    docker 调用统一走 asyncio.create_subprocess_exec（无额外依赖、天然异步）。
    """

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._serial: str | None = None

    async def _docker(
        self, *args: str, timeout: float = _DOCKER_TIMEOUT_SECONDS
    ) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise BackendError(
                E_DOCKER_MISSING, f"docker 命令超时：docker {' '.join(args[:3])}"
            ) from None
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )

    async def _docker_available(self) -> bool:
        rc, _, _ = await self._docker("version", "--format", "{{.Server.Version}}")
        return rc == 0

    async def _container_state(self) -> str:
        """running / exited / paused / missing / unknown。"""
        rc, out, err = await self._docker(
            "inspect", "-f", "{{.State.Status}}", self._cfg.redroid_container
        )
        if rc == 0:
            return out.strip() or "unknown"
        if "no such object" in err.lower():
            return "missing"
        raise BackendError(E_CONTAINER_FAILED, f"无法读取容器状态：{err or out}")

    async def ensure_ready(self) -> BackendState:
        if self._serial:
            return BackendState(
                ready=True, adb_serial=self._serial, detail=self.describe()
            )
        if not await self._docker_available():
            raise BackendError(E_DOCKER_MISSING, "宿主机未安装或无法访问 docker")
        state = await self._container_state()
        if state == "missing":
            await self._create_and_start()
        elif state != "running":
            rc, _, err = await self._docker("start", self._cfg.redroid_container)
            if rc != 0:
                raise BackendError(E_CONTAINER_FAILED, f"容器启动失败：{err}")
            await self._wait_boot()
        else:
            # 已运行但可能仍在引导（如宿主机刚重启、容器自启）
            await self._wait_boot()
        self._serial = f"127.0.0.1:{self._cfg.redroid_adb_port}"
        return BackendState(ready=True, adb_serial=self._serial, detail=self.describe())

    async def _create_and_start(self) -> None:
        cfg = self._cfg
        args = [
            "run",
            "-d",
            "--name",
            cfg.redroid_container,
            "--privileged",  # redroid 必需
            "-v",
            f"{cfg.redroid_data_path}:/data",  # 持久化系统数据/App/登录态
            "-p",
            f"127.0.0.1:{cfg.redroid_adb_port}:5555",  # ADB 只绑本机回环
            *cfg.redroid_extra_args,
            cfg.redroid_image,
        ]
        rc, out, err = await self._docker(*args, timeout=_RUN_TIMEOUT_SECONDS)
        if rc != 0:
            raise BackendError(E_CONTAINER_FAILED, f"容器创建失败：{err or out}")
        await self._wait_boot()

    async def _wait_boot(self) -> None:
        deadline = time.monotonic() + _BOOT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            rc, out, _ = await self._docker(
                "exec", self._cfg.redroid_container, "getprop", "sys.boot_completed"
            )
            if rc == 0 and out.strip() == "1":
                return
            await asyncio.sleep(_BOOT_POLL_INTERVAL)
        raise BackendError(
            E_CONTAINER_FAILED, "容器引导超时（sys.boot_completed 未就绪）"
        )

    async def health(self) -> BackendState:
        try:
            state = await self._container_state()
        except BackendError as exc:
            return BackendState(ready=False, adb_serial="", detail={"error": exc.code})
        return BackendState(
            ready=state == "running" and self._serial is not None,
            adb_serial=self._serial or "",
            detail={**self.describe(), "container_state": state},
        )

    async def shutdown(self, *, stop_device: bool) -> None:
        # stop 保留数据卷，不 rm；插件常规卸载不传 stop_device，避免重载杀掉「手机」
        if stop_device and self._serial:
            await self._docker("stop", self._cfg.redroid_container, timeout=60.0)
        self._serial = None

    def describe(self) -> dict:
        cfg = self._cfg
        return {
            "mode": MODE_REDROID,
            "container": cfg.redroid_container,
            "image": cfg.redroid_image,
            "adb_host": "127.0.0.1",
            "adb_port": cfg.redroid_adb_port,
        }
