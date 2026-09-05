from __future__ import annotations

from pathlib import Path

import yaml

import astrbot_plugin_companion_phone.constants as constants

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_metadata_version_matches_constant():
    # 规范 §10：metadata.yaml version 是唯一事实源，代码常量必须同步
    metadata = yaml.safe_load(
        (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    )
    assert metadata["version"] == constants.PLUGIN_VERSION
    assert constants.__version__ == metadata["version"]


def test_immutable_identifiers_aligned():
    # 规范 §2.2：目录名 = metadata name = @register 首参
    metadata = yaml.safe_load(
        (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    )
    assert metadata["name"] == constants.PLUGIN_ID == PLUGIN_ROOT.name
    assert metadata["repo"] == constants.PLUGIN_REPOSITORY
    # 规范 §5.0：仓库地址严格匹配 https://github.com/qsbb/<plugin_id>
    assert metadata["repo"] == f"https://github.com/qsbb/{constants.PLUGIN_ID}"


def test_series_display_name():
    metadata = yaml.safe_load(
        (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    )
    assert metadata["display_name"].startswith("凝心溯溪-")
    assert metadata["display_name"] == f"凝心溯溪-{constants.PLUGIN_NAME}"
    assert metadata["desc"].lstrip().startswith("凝心溯溪系列")


def test_audit_timestamp_is_utc(tmp_path):

    from astrbot_plugin_companion_phone.audit import AuditLog

    audit = AuditLog(tmp_path)
    audit.record(
        umo="test:umo",
        mode="real",
        action="tap",
        params={},
        outcome="ok",
    )
    record = audit.recent(1)[0]
    assert "+00:00" in record["ts"]  # 规范 §6：UTC 存储
