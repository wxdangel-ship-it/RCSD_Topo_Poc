from __future__ import annotations

import faulthandler
import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Step2Progress:
    def __init__(self, step_root: Path, enabled: bool, total: int, slow_unit_sec: float = 30.0) -> None:
        self.enabled = enabled
        self.total = total
        self.slow_unit_sec = slow_unit_sec
        self.progress_path = step_root / "t06_step2_progress.jsonl"
        self.heartbeat_path = step_root / "t06_step2_heartbeat.json"
        self.slow_units_path = step_root / "t06_step2_slow_units.jsonl"
        self.slow_groups_path = step_root / "t06_step2_slow_groups.jsonl"
        self.stackdump_path = step_root / "t06_step2_stackdump.log"
        self._phase = "init"
        self._unit: dict[str, Any] | None = None
        self._group: dict[str, Any] | None = None
        self._stackdump_file = None
        if self.enabled:
            self._install_stackdump()
            self.stage("init", total=total)

    def unit(self, index: int, segment_id: str) -> None:
        if not self.enabled:
            return
        self._close_unit()
        self._phase = "main_loop"
        self._unit = {"index": index, "segment_id": segment_id, "started_at": time.monotonic()}
        fields = {"phase": self._phase, "index": index, "total": self.total, "segment_id": segment_id}
        self._write_heartbeat(fields)
        if index == 1 or index % 1000 == 0:
            self._write_event("unit_progress", **fields)

    def unit_done(self) -> None:
        if self.enabled:
            self._close_unit()

    def group(self, index: int, *, segment_id: str, failure_business_count: int) -> None:
        if not self.enabled:
            return
        self._close_group()
        self._phase = "group_audit"
        self._group = {"index": index, "segment_id": segment_id, "started_at": time.monotonic()}
        fields = {
            "phase": self._phase,
            "index": index,
            "segment_id": segment_id,
            "failure_business_count": failure_business_count,
        }
        self._write_heartbeat(fields)
        if index == 1 or index % 100 == 0:
            self._write_event("group_progress", **fields)

    def group_done(self, **fields: Any) -> None:
        if self.enabled:
            self._close_group(extra_fields=fields)

    def stage(self, name: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self._close_unit()
        self._close_group()
        self._phase = name
        payload = {"phase": name, **fields}
        self._write_event("stage", **payload)
        self._write_heartbeat(payload)

    def finish(self, **fields: Any) -> None:
        if not self.enabled:
            return
        self._close_unit()
        self._close_group()
        self._write_event("finish", phase="done", **fields)
        self._write_heartbeat({"phase": "done", **fields})
        self.close()

    def close(self) -> None:
        if self._stackdump_file is None:
            return
        try:
            if hasattr(signal, "SIGUSR1"):
                faulthandler.unregister(signal.SIGUSR1)
        except Exception:
            pass
        self._stackdump_file.close()
        self._stackdump_file = None

    def _close_unit(self) -> None:
        if self._unit is None:
            return
        elapsed = time.monotonic() - float(self._unit["started_at"])
        if elapsed >= self.slow_unit_sec:
            self._write_jsonl(
                self.slow_units_path,
                {
                    "event": "slow_unit",
                    "elapsed_sec": round(elapsed, 3),
                    "index": self._unit["index"],
                    "total": self.total,
                    "segment_id": self._unit["segment_id"],
                },
            )
        self._unit = None

    def _close_group(self, extra_fields: dict[str, Any] | None = None) -> None:
        if self._group is None:
            return
        elapsed = time.monotonic() - float(self._group["started_at"])
        payload = {
            "elapsed_sec": round(elapsed, 3),
            "index": self._group["index"],
            "segment_id": self._group["segment_id"],
            **(extra_fields or {}),
        }
        if elapsed >= self.slow_unit_sec:
            self._write_jsonl(self.slow_groups_path, {"event": "slow_group", **payload})
        self._group = None

    def _install_stackdump(self) -> None:
        if not hasattr(signal, "SIGUSR1"):
            return
        try:
            self._stackdump_file = self.stackdump_path.open("a", encoding="utf-8")
            faulthandler.register(signal.SIGUSR1, file=self._stackdump_file, all_threads=True, chain=False)
        except Exception as exc:  # pragma: no cover - platform/runtime dependent
            self._write_jsonl(self.progress_path, {"event": "stackdump_unavailable", "error": str(exc)})

    def _write_event(self, event: str, **fields: Any) -> None:
        self._write_jsonl(self.progress_path, {"event": event, **fields})

    def _write_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), **row}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _write_heartbeat(self, fields: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), **fields}
        tmp = self.heartbeat_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.heartbeat_path)
