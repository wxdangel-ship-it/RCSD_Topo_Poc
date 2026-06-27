import json

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
