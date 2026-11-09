"""审计 JSONL（PROTOCOL.md 第 9.1 节，权威 Agent 审计）。

每行一个 JSON 事件，必含字段 ts / seq / run_id / event：
  - 命令类事件含 tool, command_id, decision
  - 拒绝事件含 error_code, reasons
seq 在同一 run 的审计文件内从 1 单调递增。

路径：<audit_dir>/audit_<run_id>.jsonl，默认 audit_dir =
llm_drone/logs/drone-sim（可用环境变量 LLM_DRONE_AUDIT_DIR 覆盖，供测试隔离）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TZ_BEIJING = timezone(timedelta(hours=8))

DEFAULT_AUDIT_DIR = Path(__file__).resolve().parents[1] / "logs" / "drone-sim"
ENV_AUDIT_DIR = "LLM_DRONE_AUDIT_DIR"

_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def now_iso() -> str:
    """墙钟 ISO 8601（带 +08:00 时区）。"""
    return datetime.now(TZ_BEIJING).isoformat(timespec="milliseconds")


def safe_run_id(run_id: Optional[str]) -> str:
    """把 run_id 规范化为安全文件名片段（缺省 default）。"""
    text = str(run_id).strip() if run_id is not None else ""
    if not text:
        return "default"
    return _SAFE_RUN_ID.sub("_", text) or "default"


def audit_path_for(audit_dir: Any, run_id: Optional[str]) -> Path:
    return Path(audit_dir) / ("audit_%s.jsonl" % safe_run_id(run_id))


class AuditLogger:
    """线程安全、只增不减的 JSONL 审计写入器。"""

    def __init__(self, path: Any, run_id: Optional[str] = None, echo: bool = False):
        self.path = Path(path)
        self.run_id = safe_run_id(run_id)
        self.echo = bool(echo)
        self._lock = threading.Lock()
        parent = self.path.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._last_seq_on_disk()
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    # -------------------------------------------------------------- 内部
    def _last_seq_on_disk(self) -> int:
        if not self.path.is_file():
            return 0
        last = 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        last = max(last, int(json.loads(line).get("seq", 0)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError:
            return 0
        return last

    # -------------------------------------------------------------- 写
    def log(self, event: str, **fields: Any) -> dict:
        """写入一条审计事件并返回记录（含 seq / run_id / ts）。"""
        with self._lock:
            self._seq += 1
            record: Dict[str, Any] = {
                "ts": now_iso(),
                "seq": self._seq,
                "run_id": self.run_id,
                "event": str(event),
            }
            record.update(fields)
            line = json.dumps(record, ensure_ascii=False, default=str)
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except OSError as exc:  # pragma: no cover - 磁盘异常兜底
                print("[audit] write failed: %s" % exc, file=sys.stderr)
        if self.echo:
            print("[audit] %s" % line, file=sys.stderr)
        return record

    # -------------------------------------------------------------- 读
    def read_events(self, since_seq: int = 0) -> List[dict]:
        """读取审计文件全部事件（seq > since_seq），并按需重排。"""
        with self._lock:
            try:
                self._fh.flush()
            except (OSError, ValueError):
                pass
            events: List[dict] = []
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if int(record.get("seq", 0)) > int(since_seq):
                            events.append(record)
            except FileNotFoundError:
                pass
            return events

    def last_seq(self) -> int:
        events = self.read_events(0)
        return int(events[-1]["seq"]) if events else 0

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except (OSError, ValueError):
                pass

    def __enter__(self) -> "AuditLogger":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


class AuditManager:
    """按 run_id 切换审计文件的审计器（/v1/reset 用）。"""

    def __init__(self, audit_dir: Optional[Any] = None, run_id: Optional[str] = None, echo: bool = False):
        if audit_dir is None:
            audit_dir = os.environ.get(ENV_AUDIT_DIR) or DEFAULT_AUDIT_DIR
        self.audit_dir = Path(audit_dir)
        self.echo = bool(echo)
        self._logger: Optional[AuditLogger] = None
        self._lock = threading.Lock()
        self.switch_run(run_id or "default")

    @property
    def run_id(self) -> str:
        logger = self._logger
        return logger.run_id if logger is not None else "default"

    @property
    def path(self) -> Path:
        logger = self._logger
        if logger is None:
            return audit_path_for(self.audit_dir, "default")
        return logger.path

    def switch_run(self, run_id: Optional[str]) -> Path:
        """切换到新的审计文件（同一 run_id 复用/追加），返回文件路径。"""
        with self._lock:
            old = self._logger
            target = audit_path_for(self.audit_dir, run_id)
            if old is not None and old.path == target:
                return target
            new_logger = AuditLogger(target, run_id=run_id, echo=self.echo)
            self._logger = new_logger
            if old is not None:
                old.close()
            return target

    def log(self, event: str, **fields: Any) -> dict:
        logger = self._logger
        if logger is None:  # pragma: no cover - 构造后不可能
            raise RuntimeError("audit logger 未初始化")
        return logger.log(event, **fields)

    def read_events(self, since_seq: int = 0) -> List[dict]:
        logger = self._logger
        if logger is None:  # pragma: no cover
            return []
        return logger.read_events(since_seq)

    def last_seq(self) -> int:
        logger = self._logger
        if logger is None:  # pragma: no cover
            return 0
        return logger.last_seq()

    def close(self) -> None:
        with self._lock:
            if self._logger is not None:
                self._logger.close()
                self._logger = None

class NullAuditLogger:
    """空审计器（内存记录，便于进程内单测；接口与 AuditLogger 兼容）。"""

    def __init__(self, run_id: Optional[str] = "null"):
        self.path = "<null>"
        self.run_id = safe_run_id(run_id)
        self._events = []

    def log(self, event: str, **fields: Any) -> dict:
        record = {"ts": now_iso(), "seq": len(self._events) + 1, "run_id": self.run_id, "event": str(event)}
        record.update(fields)
        self._events.append(record)
        return record

    def read_events(self, since_seq: int = 0):
        return [e for e in self._events if int(e.get("seq", 0)) > int(since_seq)]

    def last_seq(self) -> int:
        return len(self._events)

    def close(self) -> None:
        pass

