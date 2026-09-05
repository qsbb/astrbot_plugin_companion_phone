from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .log import logger


def _hash_umo(umo: str) -> str:
    if not umo:
        return ""
    return hashlib.sha256(umo.encode("utf-8")).hexdigest()[:12]


class AuditLog:
    """JSONL 追加审计：data/plugin_data/<plugin>/audit/YYYY-MM-DD.jsonl

    隐私约定：params 由调用方（service）预先脱敏——input_text 只记长度，
    不落任何正文片段；写入失败只 warning，不影响主流程。
    日期文件名统一 UTC（规范 §6），写入/读取/清空三方一致。
    """

    def __init__(self, base_dir: Path) -> None:
        self._dir = Path(base_dir) / "audit"
        self._lock = threading.Lock()  # to_thread 并发写保护

    def record(
        self,
        *,
        umo: str,
        mode: str,
        action: str,
        params: dict[str, Any],
        outcome: str,
        error_code: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        now = datetime.now(UTC)
        entry = {
            "ts": now.isoformat(timespec="seconds"),
            "umo": _hash_umo(umo),
            "mode": mode,
            "action": action,
            "params": params,
            "outcome": outcome,
            "error_code": error_code,
            "elapsed_ms": elapsed_ms,
        }
        try:
            line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            path = self._dir / f"{now:%Y-%m-%d}.jsonl"
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except (OSError, TypeError, ValueError):
            logger.warning(
                "[companion-phone] failed to write audit record", exc_info=True
            )

    def clear_today(self) -> bool:
        """清空当日审计文件（series.webui 面板动作）；文件不存在返回 False。"""
        path = self._dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            logger.warning(
                "[companion-phone] failed to clear audit file", exc_info=True
            )
            return False

    def recent(self, limit: int = 50) -> list[dict]:
        """读当天文件尾部记录；与写入端统一 UTC 日期命名。"""
        if limit <= 0:
            return []  # 防御 lines[-0:] 切片陷阱
        path = self._dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict] = []
        for line in lines[-limit:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
