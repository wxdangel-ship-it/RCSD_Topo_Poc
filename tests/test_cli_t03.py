from __future__ import annotations

from rcsd_topo_poc import cli


def test_t03_step3_cli_uses_default_paths(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["case_root"] = args.case_root
        captured["case_id"] = args.case_id
        captured["max_cases"] = args.max_cases
        captured["workers"] = args.workers
        captured["run_id"] = args.run_id
        captured["out_root"] = args.out_root
        captured["debug"] = args.debug
        return 0

    monkeypatch.setattr(cli, "_cmd_t03_step3_legal_space", _fake_cmd)

    exit_code = cli.main(["t03-step3-legal-space"])

    assert exit_code == 0
    assert captured["case_root"] == "/mnt/e/TestData/POC_Data/T02/Anchor"
    assert captured["case_id"] is None
    assert captured["max_cases"] is None
    assert captured["workers"] == 1
    assert captured["run_id"] is None
    assert captured["out_root"] == "/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a"
    assert captured["debug"] is False


def test_t03_step3_cli_parses_custom_arguments(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["case_root"] = args.case_root
        captured["case_id"] = list(args.case_id or [])
        captured["max_cases"] = args.max_cases
        captured["workers"] = args.workers
        captured["run_id"] = args.run_id
        captured["out_root"] = args.out_root
        captured["debug"] = args.debug
        return 0

    monkeypatch.setattr(cli, "_cmd_t03_step3_legal_space", _fake_cmd)

    exit_code = cli.main(
        [
            "t03-step3-legal-space",
            "--case-root",
            "/tmp/cases",
            "--case-id",
            "100001",
            "--case-id",
            "100002",
            "--max-cases",
            "2",
            "--workers",
            "4",
            "--run-id",
            "custom-run",
            "--out-root",
            "/tmp/t03-out",
            "--debug",
        ]
    )

    assert exit_code == 0
    assert captured["case_root"] == "/tmp/cases"
    assert captured["case_id"] == ["100001", "100002"]
    assert captured["max_cases"] == 2
    assert captured["workers"] == 4
    assert captured["run_id"] == "custom-run"
    assert captured["out_root"] == "/tmp/t03-out"
    assert captured["debug"] is True
