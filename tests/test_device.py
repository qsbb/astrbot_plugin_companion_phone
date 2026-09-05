from __future__ import annotations

import asyncio

import pytest

import astrbot_plugin_companion_phone.device as device_mod
from astrbot_plugin_companion_phone.device import DeviceSession
from astrbot_plugin_companion_phone.errors import DeviceError


class FakeBackend:
    async def ensure_ready(self):
        from astrbot_plugin_companion_phone.backend.base import BackendState

        return BackendState(ready=True, adb_serial="fake:5555", detail={})


class FakeSelector:
    def __init__(self, *, exists=True, bounds=None, raise_on_click=None):
        self._exists = exists
        self._bounds = bounds
        self._raise_on_click = raise_on_click

    @property
    def exists(self):
        return self._exists

    @property
    def info(self):
        return {"bounds": self._bounds} if self._bounds is not None else {}

    def click(self):
        if self._raise_on_click is not None:
            raise self._raise_on_click


class FakeD:
    def __init__(self):
        self.press_calls: list[str] = []
        self.click_calls: list[(int, int)] = []
        self.selectors: dict[str, FakeSelector] = {}
        self.dump_xml = "<hierarchy/>"
        self.swipe_calls = []
        self.size = (1080, 2400)

    def __call__(self, text: str):
        return self.selectors.get(text, FakeSelector(exists=False))

    def press(self, key):
        self.press_calls.append(key)

    def click(self, x, y):
        self.click_calls.append((x, y))

    def dump_hierarchy(self):
        return self.dump_xml

    def window_size(self):
        return self.size

    def swipe(self, sx, sy, ex, ey, duration):
        self.swipe_calls.append((sx, sy, ex, ey, duration))

    def app_current(self):
        return {"package": "com.android.browser", "activity": ".Main"}

    def screenshot(self, path):
        pass

    def send_keys(self, text):
        pass

    def set_fastinput_ime(self, enable):
        pass

    def clear_text(self):
        pass

    def app_start(self, package):
        pass


@pytest.fixture
def session(monkeypatch):
    fake_d = FakeD()
    monkeypatch.setattr(
        DeviceSession, "_connect_sync", staticmethod(lambda serial: fake_d)
    )
    sess = DeviceSession(FakeBackend())
    asyncio.run(sess.connect())
    return sess, fake_d


def test_parse_bounds_variants():
    parse = DeviceSession._parse_bounds
    assert parse("[0,0][100,200]") == [0, 0, 100, 200]
    assert parse("[10,10][5,50]") is None  # 逆向
    assert parse("[0,0][0,0]") is None  # 零尺寸
    assert parse("[-50,0][100,100]") is None  # 负坐标（刻意丢弃离屏节点）
    assert parse("garbage") is None
    assert parse("") is None


def test_normalize_bounds_shapes():
    normalize = DeviceSession._normalize_bounds
    assert normalize({"left": 1, "top": 2, "right": 3, "bottom": 4}) == [1, 2, 3, 4]
    assert normalize([5, 6, 7, 8]) == [5, 6, 7, 8]
    assert normalize(None) == [0, 0, 0, 0]


def test_press_key_recents_uses_u2_recent(session):
    sess, fake_d = session
    asyncio.run(sess.press_key("recents"))
    assert fake_d.press_calls == ["recent"]  # 回归锚：不得再出现 keyevent 164


def test_press_key_passthrough(session):
    sess, fake_d = session
    for key in ("back", "home", "enter", "del", "power", "volume_up"):
        asyncio.run(sess.press_key(key))
    assert fake_d.press_calls == ["back", "home", "enter", "del", "power", "volume_up"]


def test_click_text_bounds_normalized(session):
    sess, fake_d = session
    fake_d.selectors["搜索"] = FakeSelector(
        exists=True, bounds={"left": 1, "top": 2, "right": 3, "bottom": 4}
    )
    bounds = asyncio.run(sess.click_text("搜索"))
    assert bounds == [1, 2, 3, 4]


def test_click_text_not_found(session):
    sess, _ = session
    with pytest.raises(DeviceError) as excinfo:
        asyncio.run(sess.click_text("不存在"))
    assert excinfo.value.code == "element_not_found"


def test_click_text_vanishing_element(session, monkeypatch):
    sess, fake_d = session
    boom = type("VanishError", (Exception,), {})

    class Vanishing(FakeSelector):
        @property
        def info(self):
            raise boom()

    fake_d.selectors["搜索"] = Vanishing(exists=True)
    monkeypatch.setattr(device_mod, "_u2_element_not_found", lambda: (boom,))
    with pytest.raises(DeviceError) as excinfo:
        asyncio.run(sess.click_text("搜索"))
    assert excinfo.value.code == "element_not_found"


def test_dump_sync_filters_and_caps(session):
    sess, fake_d = session
    fake_d.dump_xml = (
        '<hierarchy><node text="按钮" bounds="[0,0][10,10]"/>'
        '<node bounds="[0,0][10,10]"/>'  # 无文本不可点 → 过滤
        '<node text="B" bounds="[0,0][10,10]"/><node text="C" bounds="[0,0][10,10]"/>'
        "</hierarchy>"
    )
    nodes = asyncio.run(sess.ui_tree(2))
    assert [n["text"] for n in nodes] == ["按钮", "B"]  # 过滤 + 截断保序
    assert asyncio.run(sess.ui_tree(0)) == []


def test_dismiss_popups_list_safety():
    from astrbot_plugin_companion_phone.device import _POPUP_TEXTS

    # 安全回归锚：权限授权按钮与中性确认按钮绝不在自动代点名单
    assert "确定" not in _POPUP_TEXTS
    assert "允许" not in _POPUP_TEXTS
    assert "始终允许" not in _POPUP_TEXTS


def test_timeout_clears_connection(session, monkeypatch):
    sess, _ = session
    monkeypatch.setattr(device_mod, "_DEVICE_OP_TIMEOUT_SECONDS", 0.01)

    def slow():
        import time

        time.sleep(0.05)

    with pytest.raises(DeviceError) as excinfo:
        asyncio.run(sess._run(slow))
    assert excinfo.value.code == "device_timeout"
    assert sess._d is None  # 超时后强制重连


def test_retry_once_after_failure(session):
    sess, fake_d = session
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection dropped")
        return "ok"

    assert asyncio.run(sess._run(flaky)) == "ok"
    assert calls["n"] == 2
