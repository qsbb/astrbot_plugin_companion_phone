from __future__ import annotations

import json

from astrbot_plugin_companion_phone import series_diagnostics as sd
from astrbot_plugin_companion_phone.constants import PLUGIN_ID, PLUGIN_NAME

REQUIRED_KEYS = {
    "seq",
    "timestamp",
    "plugin_id",
    "plugin_name",
    "level",
    "code",
    "summary",
    "details",
}
CONTRACT_KEYS = {
    "name",
    "version",
    "series_id",
    "plugin_id",
    "plugin_name",
    "capabilities",
    "storage",
    "astrbot_log_propagation",
}


def test_contract_shape():
    # 调用被测的真实实现（而非测试自造 dict），防止实现漂移时测试仍然恒真（F-19）
    contract = sd.diagnostic_log_contract()
    assert set(contract) == CONTRACT_KEYS
    assert contract["name"] == "series.diagnostics"
    assert contract["version"] == "1.0"
    assert contract["series_id"] == "ningxin_suxi"
    assert contract["plugin_id"] == PLUGIN_ID
    assert contract["plugin_name"] == PLUGIN_NAME
    assert contract["storage"] == "memory_only"
    assert contract["astrbot_log_propagation"] is False


def test_event_structure_and_cursor():
    sd.diagnostic_clear()
    sd.diagnostic_event("a.test", "事件一")
    sd.diagnostic_event("b.test", "事件二", level="WARNING", details={"port": 26655})
    result = sd.diagnostic_events(after_seq=0, limit=200)
    assert set(result) == {"events", "next_seq", "dropped_before", "stream_id"}
    assert len(result["events"]) == 2
    assert result["next_seq"] == result["events"][-1]["seq"]
    ev = result["events"][-1]
    assert set(ev) == REQUIRED_KEYS
    assert ev["level"] == "WARNING"
    assert ev["code"] == "b.test"
    assert ev["details"]["port"] == 26655
    assert "T" in ev["timestamp"] and "+00:00" in ev["timestamp"]  # UTC ISO


def test_redaction_preserves_structure():
    sd.diagnostic_clear()
    details = {
        "url": "http://127.0.0.1:26655",
        "api_key": "sk-abcdef123456",
        "nested": {"token": "tok", "note": "keep me"},
        "items": [{"password": "p", "size": 3}],
    }
    sd.diagnostic_event("sec.test", "脱敏", details=details)
    ev = sd.diagnostic_events(0, 200)["events"][-1]
    text = json.dumps(ev, ensure_ascii=False)
    # 规范 5.1：键名与结构保留（"token" 键名仍在），仅值被替换
    assert "sk-abcdef123456" not in text
    assert '"token": "tok"' not in text
    assert '"password": "p"' not in text
    assert ev["details"]["url"] == "http://127.0.0.1:26655"  # 排障数据保留
    assert ev["details"]["api_key"] == "<已隐藏>"
    assert ev["details"]["nested"]["token"] == "<已隐藏>"
    assert ev["details"]["nested"]["note"] == "keep me"
    assert ev["details"]["items"][0]["password"] == "<已隐藏>"


def test_ring_buffer_limit():
    sd.diagnostic_clear()
    for i in range(1005):
        sd.diagnostic_event("flood", f"e{i}")
    result = sd.diagnostic_events(0, 1000)
    assert len(result["events"]) == 1000
    assert result["dropped_before"] == 5
    seqs = [e["seq"] for e in result["events"]]
    assert seqs == list(range(seqs[0], seqs[0] + 1000))


def test_clear_keeps_seq_monotonic():
    """回归锚：clear 后 seq 持续单调，聚合端旧游标不会吞掉新事件（F-20）。"""
    sd.diagnostic_clear()
    sd.diagnostic_event("before", "清空前")
    last_seq = sd.diagnostic_events(0, 200)["events"][-1]["seq"]
    sd.diagnostic_clear()
    sd.diagnostic_event("after", "清空后")
    result = sd.diagnostic_events(0, 200)
    assert len(result["events"]) == 1
    assert result["events"][0]["seq"] > last_seq  # seq 不回绕
    result2 = sd.diagnostic_events(last_seq, 200)
    assert len(result2["events"]) == 1  # 旧游标依然能读到清空后的新事件
    assert result2["stream_id"]  # stream_id 保持，表示进程未重启
