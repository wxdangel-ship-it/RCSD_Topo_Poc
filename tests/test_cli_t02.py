from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc import cli


def test_t02_stage1_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["segment_path"] = args.segment_path
        captured["nodes_path"] = args.nodes_path
        captured["drivezone_path"] = args.drivezone_path
        captured["out_root"] = args.out_root
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_stage1_drivezone_gate", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-stage1-drivezone-gate",
            "--segment_path",
            str(tmp_path / "segment.geojson"),
            "--nodes_path",
            str(tmp_path / "nodes.geojson"),
            "--drivezone_path",
            str(tmp_path / "drivezone.geojson"),
            "--out_dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["segment_path"] == str(tmp_path / "segment.geojson")
    assert captured["nodes_path"] == str(tmp_path / "nodes.geojson")
    assert captured["drivezone_path"] == str(tmp_path / "drivezone.geojson")
    assert captured["out_root"] == str(tmp_path / "out")


def test_t02_stage2_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["nodes_path"] = args.nodes_path
        captured["intersection_path"] = args.intersection_path
        captured["out_root"] = args.out_root
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_stage2_anchor_recognition", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-stage2-anchor-recognition",
            "--nodes_path",
            str(tmp_path / "nodes.geojson"),
            "--intersection_path",
            str(tmp_path / "intersection.geojson"),
            "--out_dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["nodes_path"] == str(tmp_path / "nodes.geojson")
    assert captured["intersection_path"] == str(tmp_path / "intersection.geojson")
    assert captured["out_root"] == str(tmp_path / "out")

