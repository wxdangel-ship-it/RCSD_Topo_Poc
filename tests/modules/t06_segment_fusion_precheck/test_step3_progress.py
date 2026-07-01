import json
import threading

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_progress import Step3ProgressWatchdog


def test_step3_progress_watchdog_writes_sidecars(tmp_path):
    step_root = tmp_path / "step3_segment_replacement"
    watchdog = Step3ProgressWatchdog(step_root, enabled=True, interval_sec=5)

    watchdog.start(run_id="unit_test")
    watchdog.stage("run_standard_step3")
    watchdog._sample()
    watchdog.finish("done")

    progress_path = step_root / "t06_step3_progress.jsonl"
    heartbeat_path = step_root / "t06_step3_heartbeat.json"
    stackdump_path = step_root / "t06_step3_stackdump.log"

    assert progress_path.is_file()
    assert heartbeat_path.is_file()
    assert stackdump_path.is_file()

    events = [json.loads(line)["event"] for line in progress_path.read_text(encoding="utf-8").splitlines()]
    assert "stage" in events
    assert "heartbeat" in events
    assert "finish" in events

    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["phase"] == "done"
    assert heartbeat["status"] == "done"
    assert "elapsed_sec" in heartbeat
    assert "phase=run_standard_step3" in stackdump_path.read_text(encoding="utf-8")


def test_step3_heartbeat_uses_thread_local_tmp_files(tmp_path, monkeypatch):
    step_root = tmp_path / "step3_segment_replacement"
    watchdog = Step3ProgressWatchdog(step_root, enabled=True, interval_sec=5)
    barrier = threading.Barrier(2)
    original_write_text = type(watchdog.heartbeat_path).write_text

    def delayed_write_text(path, *args, **kwargs):
        result = original_write_text(path, *args, **kwargs)
        if path.name.startswith(".t06_step3_heartbeat.json.") and path.name.endswith(".tmp"):
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(type(watchdog.heartbeat_path), "write_text", delayed_write_text)

    errors: list[BaseException] = []

    def write_heartbeat(phase: str) -> None:
        try:
            watchdog._write_heartbeat({"phase": phase})
        except BaseException as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    threads = [
        threading.Thread(target=write_heartbeat, args=("main_stage",)),
        threading.Thread(target=write_heartbeat, args=("watchdog_sample",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    heartbeat = json.loads((step_root / "t06_step3_heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["phase"] in {"main_stage", "watchdog_sample"}
