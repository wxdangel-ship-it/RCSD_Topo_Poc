from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc import cli


def test_t01_run_skill_v1_defaults_debug_to_false(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["debug"] = args.debug
        captured["road_path"] = args.road_path
        captured["node_path"] = args.node_path
        return 0

    monkeypatch.setattr(cli, "_cmd_t01_run_skill_v1", _fake_cmd)

    exit_code = cli.main(
        [
            "t01-run-skill-v1",
            "--road-path",
            str(tmp_path / "roads.geojson"),
            "--node-path",
            str(tmp_path / "nodes.geojson"),
        ]
    )

    assert exit_code == 0
    assert captured["debug"] is False


def test_t01_step6_defaults_debug_to_false(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["debug"] = args.debug
        return 0

    monkeypatch.setattr(cli, "_cmd_t01_step6_segment_aggregation", _fake_cmd)

    exit_code = cli.main(
        [
            "t01-step6-segment-aggregation-poc",
            "--road-path",
            str(tmp_path / "roads.geojson"),
            "--node-path",
            str(tmp_path / "nodes.geojson"),
        ]
    )

    assert exit_code == 0
    assert captured["debug"] is False



def test_t01_continue_oneway_defaults_debug_to_false(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["debug"] = args.debug
        captured["continue_from_dir"] = args.continue_from_dir
        captured["out_root"] = args.out_root
        return 0

    monkeypatch.setattr(cli, "_cmd_t01_continue_oneway_segment", _fake_cmd)

    exit_code = cli.main(
        [
            "t01-continue-oneway-segment",
            "--continue-from-dir",
            str(tmp_path / "previous"),
            "--out-root",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["debug"] is False
    assert captured["continue_from_dir"] == str(tmp_path / "previous")
    assert captured["out_root"] == str(tmp_path / "out")
