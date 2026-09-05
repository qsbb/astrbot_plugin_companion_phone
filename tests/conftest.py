from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# 离线环境注入最小 astrbot stub（核官方测试方案）；真实宿主上使用真实模块
try:
    import astrbot  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "astrbot_stub"))

from service_fixtures import install_fake_backend, make_service  # noqa: E402


@pytest.fixture
def service(tmp_path, monkeypatch):
    """共享的 PhoneService（假后端 + 假会话）；详见 service_fixtures.py。"""
    install_fake_backend(monkeypatch)
    return make_service(tmp_path)
