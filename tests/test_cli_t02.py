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


def test_t02_virtual_intersection_poc_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["nodes_path"] = args.nodes_path
        captured["roads_path"] = args.roads_path
        captured["drivezone_path"] = args.drivezone_path
        captured["rcsdroad_path"] = args.rcsdroad_path
        captured["rcsdnode_path"] = args.rcsdnode_path
        captured["mainnodeid"] = args.mainnodeid
        captured["out_root"] = args.out_root
        captured["buffer_m"] = args.buffer_m
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_virtual_intersection_poc", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-virtual-intersection-poc",
            "--nodes_path",
            str(tmp_path / "nodes.geojson"),
            "--roads_path",
            str(tmp_path / "roads.geojson"),
            "--drivezone_path",
            str(tmp_path / "drivezone.geojson"),
            "--rcsdroad_path",
            str(tmp_path / "rcsdroad.geojson"),
            "--rcsdnode_path",
            str(tmp_path / "rcsdnode.geojson"),
            "--mainnodeid",
            "100",
            "--out_dir",
            str(tmp_path / "out"),
            "--buffer-m",
            "120",
        ]
    )

    assert exit_code == 0
    assert captured["nodes_path"] == str(tmp_path / "nodes.geojson")
    assert captured["roads_path"] == str(tmp_path / "roads.geojson")
    assert captured["drivezone_path"] == str(tmp_path / "drivezone.geojson")
    assert captured["rcsdroad_path"] == str(tmp_path / "rcsdroad.geojson")
    assert captured["rcsdnode_path"] == str(tmp_path / "rcsdnode.geojson")
    assert captured["mainnodeid"] == "100"
    assert captured["out_root"] == str(tmp_path / "out")
    assert captured["buffer_m"] == 120.0

