from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .log import logger


def mask_text(text: str, head: int = 12) -> str:
    """输入类文本只落长度与前缀，正文不进审计。"""
    text = text.strip()
    return text[:head] + ("***" if len(text) > head else "")


def _hash_umo(umo: str) -> str:
    if not umo:
        return ""
    return hashlib.sha256(umo.encode("utf-8")).hexdigest()[:12]


class AuditLog:
    """JSONL 追加审计：data/plugin_data/<plugin>/audit/YYYY-MM-DD.jsonl

    隐私约定：params 由调用方（service）预先掩码；写入失败只 warning，不影响主流程。
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
        now = datetime.now(UTC)  # 规范 §6：时区一律 UTC 存储，展示层再本地化
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
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        path = self._dir / f"{now:%Y-%m-%d}.jsonl"
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            logger.warning("companion_phone 审计写入失败", exc_info=True)

    def clear_today(self) -> bool:
        """清空当日审计文件（series.webui 面板动作）；无文件返回 False。"""
        path = self._dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            logger.warning(
                "[companion-phone] failed to clear audit file", exc_info=True
            )
            return False

    def recent(self, limit: int = 50) -> list[dict]:
        """读当天文件尾部记录（审计查询用，脱敏已由写入端保证）。"""
        path = self._dir / f"{datetime.now():%Y-%m-%d}.jsonl"
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
