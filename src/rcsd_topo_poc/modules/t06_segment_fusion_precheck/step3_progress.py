from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Step3ProgressWatchdog:
    def __init__(self, step_root: Path, *, enabled: bool, interval_sec: float = 60.0) -> None:
        self.step_root = step_root
        self.enabled = enabled
        self.interval_sec = max(5.0, float(interval_sec))
        self.progress_path = step_root / "t06_step3_progress.jsonl"
        self.heartbeat_path = step_root / "t06_step3_heartbeat.json"
        self.stackdump_path = step_root / "t06_step3_stackdump.log"
        self._phase = "init"
        self._started_at = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stackdump_file = None

    def start(self, **fields: Any) -> None:
        if not self.enabled:
            return
        self.step_root.mkdir(parents=True, exist_ok=True)
        self._install_stackdump()
        self.stage("init", **fields)
        self._thread = threading.Thread(target=self._run, name="t06-step3-progress-watchdog", daemon=True)
        self._thread.start()

    def stage(self, name: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self._phase = name
        payload = {"phase": name, **fields, **self._runtime_fields()}
        self._write_event("stage", **payload)
        self._write_heartbeat(payload)
        print(f"[T06 Step3] stage={name} elapsed={payload['elapsed_sec']}s", flush=True)

    def finish(self, status: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        payload = {"phase": "done", "status": status, **fields, **self._runtime_fields()}
        self._write_event("finish", **payload)
        self._write_heartbeat(payload)
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

    def _run(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self._sample()

    def _sample(self) -> None:
        stack = self._main_thread_stack()
        top = stack[-1].strip() if stack else None
        payload = {
            "phase": self._phase,
            "top_frame": top,
            "stackdump_path": str(self.stackdump_path),
            **self._runtime_fields(),
        }
        self._write_event("heartbeat", **payload)
        self._write_heartbeat(payload)
        self._append_stackdump(stack)
        print(f"[T06 Step3] heartbeat phase={self._phase} elapsed={payload['elapsed_sec']}s top={top}", flush=True)

    def _install_stackdump(self) -> None:
        if not hasattr(signal, "SIGUSR1"):
            return
        try:
            self._stackdump_file = self.stackdump_path.open("a", encoding="utf-8")
            faulthandler.register(signal.SIGUSR1, file=self._stackdump_file, all_threads=True, chain=False)
        except Exception as exc:  # pragma: no cover - platform/runtime dependent
            self._write_event("stackdump_unavailable", error=str(exc), **self._runtime_fields())

    def _append_stackdump(self, stack: list[str]) -> None:
        try:
            with self.stackdump_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n===== {datetime.now(timezone.utc).isoformat()} pid={os.getpid()} phase={self._phase} =====\n")
                if stack:
                    handle.writelines(stack)
                else:
                    handle.write("main thread stack unavailable\n")
                handle.flush()
        except OSError:
            pass

    def _main_thread_stack(self) -> list[str]:
        main_ident = threading.main_thread().ident
        if main_ident is None:
            return []
        frame = sys._current_frames().get(main_ident)
        if frame is None:
            return []
        return traceback.format_stack(frame)

    def _runtime_fields(self) -> dict[str, Any]:
        return {"pid": os.getpid(), "elapsed_sec": round(time.monotonic() - self._started_at, 3)}

    def _write_event(self, event: str, **fields: Any) -> None:
        self._write_jsonl(self.progress_path, {"event": event, **fields})

    def _write_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **row}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _write_heartbeat(self, fields: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **fields}
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.heartbeat_path.with_name(
            f".{self.heartbeat_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.heartbeat_path)
