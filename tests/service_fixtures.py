from __future__ import annotations

import pytest

import astrbot_plugin_companion_phone.service as service_mod
from astrbot_plugin_companion_phone.backend.base import BackendState
from astrbot_plugin_companion_phone.service import PhoneService

from helpers import make_cfg


class FakeBackend:
    def __init__(self):
        self.state = BackendState(
            ready=True, adb_serial="fake:5555", detail={"mode": "fake"}
        )

    async def ensure_ready(self):
        return self.state

    async def health(self):
        return self.state

    async def shutdown(self, *, stop_device):
        pass

    def describe(self):
        return {"mode": "fake"}


class FakeSession:
    def __init__(self, backend):
        self.backend = backend
        self.calls = []

    async def connect(self):
        pass

    async def close(self):
        pass

    async def assert_ready(self):
        pass

    async def current_app(self):
        return {"package": "com.android.browser", "activity": ".Main"}

    async def screen_size(self):
        return [1080, 2400]

    async def screen_on(self):
        return True

    async def ui_tree(self, max_nodes):
        return [
            {"rid": 1, "text": "搜索", "bounds": [0, 100, 200, 200], "clickable": True},
            {
                "rid": 2,
                "text": "发送",
                "bounds": [0, 2200, 1080, 2300],
                "clickable": True,
            },
        ]

    async def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG-fake")
        return path

    async def tap(self, x, y):
        self.calls.append(("tap", x, y))

    async def click_text(self, text):
        self.calls.append(("click_text", text))
        return [0, 0, 100, 100]

    async def input_text(self, text, clear):
        self.calls.append(("input_text", text, clear))
        return False

    async def swipe(self, sx, sy, ex, ey, duration_s):
        self.calls.append(("swipe", sx, sy, ex, ey))

    async def press_key(self, key):
        self.calls.append(("press_key", key))

    async def app_start(self, package):
        self.calls.append(("app_start", package))

    async def app_stop(self, package):
        self.calls.append(("app_stop", package))

    async def wait_text(self, text, timeout_s):
        return True

    async def dismiss_popups(self):
        self.calls.append(("dismiss_popups",))
        return 0


def install_fake_backend(monkeypatch) -> None:
    monkeypatch.setattr(service_mod, "create_backend", lambda cfg: FakeBackend())


def make_service(tmp_path, cfg=None) -> PhoneService:
    holder: dict = {}

    def factory(backend):
        session = FakeSession(backend)
        holder["session"] = session
        return session

    svc = PhoneService(lambda: cfg or make_cfg(), tmp_path, session_factory=factory)
    svc._fake = holder
    return svc


@pytest.fixture
def service(tmp_path, monkeypatch):
    install_fake_backend(monkeypatch)
    return make_service(tmp_path)
