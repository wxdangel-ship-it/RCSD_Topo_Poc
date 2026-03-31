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
            str(tmp_path / "segment.gpkg"),
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--drivezone_path",
            str(tmp_path / "drivezone.gpkg"),
            "--out_dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["segment_path"] == str(tmp_path / "segment.gpkg")
    assert captured["nodes_path"] == str(tmp_path / "nodes.gpkg")
    assert captured["drivezone_path"] == str(tmp_path / "drivezone.gpkg")
    assert captured["out_root"] == str(tmp_path / "out")


def test_t02_stage2_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["segment_path"] = args.segment_path
        captured["nodes_path"] = args.nodes_path
        captured["intersection_path"] = args.intersection_path
        captured["out_root"] = args.out_root
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_stage2_anchor_recognition", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-stage2-anchor-recognition",
            "--segment_path",
            str(tmp_path / "segment.gpkg"),
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--intersection_path",
            str(tmp_path / "intersection.gpkg"),
            "--out_dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["segment_path"] == str(tmp_path / "segment.gpkg")
    assert captured["nodes_path"] == str(tmp_path / "nodes.gpkg")
    assert captured["intersection_path"] == str(tmp_path / "intersection.gpkg")
    assert captured["out_root"] == str(tmp_path / "out")


def test_t02_fix_node_error_2_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["node_error2_path"] = args.node_error2_path
        captured["nodes_path"] = args.nodes_path
        captured["roads_path"] = args.roads_path
        captured["intersection_path"] = args.intersection_path
        captured["nodes_fix_path"] = args.nodes_fix_path
        captured["roads_fix_path"] = args.roads_fix_path
        captured["report_path"] = args.report_path
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_fix_node_error_2", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-fix-node-error-2",
            "--node_error2_path",
            str(tmp_path / "node_error_2.gpkg"),
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--roads_path",
            str(tmp_path / "roads.gpkg"),
            "--intersection_path",
            str(tmp_path / "intersection.gpkg"),
            "--nodes_fix_path",
            str(tmp_path / "nodes_fix.gpkg"),
            "--roads_fix_path",
            str(tmp_path / "roads_fix.gpkg"),
            "--report_path",
            str(tmp_path / "fix_report.json"),
        ]
    )

    assert exit_code == 0
    assert captured["node_error2_path"] == str(tmp_path / "node_error_2.gpkg")
    assert captured["nodes_path"] == str(tmp_path / "nodes.gpkg")
    assert captured["roads_path"] == str(tmp_path / "roads.gpkg")
    assert captured["intersection_path"] == str(tmp_path / "intersection.gpkg")
    assert captured["nodes_fix_path"] == str(tmp_path / "nodes_fix.gpkg")
    assert captured["roads_fix_path"] == str(tmp_path / "roads_fix.gpkg")
    assert captured["report_path"] == str(tmp_path / "fix_report.json")


def test_t02_virtual_intersection_poc_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["input_mode"] = args.input_mode
        captured["nodes_path"] = args.nodes_path
        captured["roads_path"] = args.roads_path
        captured["drivezone_path"] = args.drivezone_path
        captured["rcsdroad_path"] = args.rcsdroad_path
        captured["rcsdnode_path"] = args.rcsdnode_path
        captured["mainnodeid"] = args.mainnodeid
        captured["out_root"] = args.out_root
        captured["max_cases"] = args.max_cases
        captured["workers"] = args.workers
        captured["buffer_m"] = args.buffer_m
        captured["debug"] = args.debug
        captured["debug_render_root"] = args.debug_render_root
        captured["review_mode"] = args.review_mode
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_virtual_intersection_poc", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-virtual-intersection-poc",
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--roads_path",
            str(tmp_path / "roads.gpkg"),
            "--drivezone_path",
            str(tmp_path / "drivezone.gpkg"),
            "--rcsdroad_path",
            str(tmp_path / "rcsdroad.gpkg"),
            "--rcsdnode_path",
            str(tmp_path / "rcsdnode.gpkg"),
            "--mainnodeid",
            "100",
            "--out_dir",
            str(tmp_path / "out"),
            "--buffer-m",
            "120",
            "--debug-render-root",
            str(tmp_path / "renders"),
            "--review-mode",
            "--debug",
        ]
    )

    assert exit_code == 0
    assert captured["input_mode"] == "case-package"
    assert captured["nodes_path"] == str(tmp_path / "nodes.gpkg")
    assert captured["roads_path"] == str(tmp_path / "roads.gpkg")
    assert captured["drivezone_path"] == str(tmp_path / "drivezone.gpkg")
    assert captured["rcsdroad_path"] == str(tmp_path / "rcsdroad.gpkg")
    assert captured["rcsdnode_path"] == str(tmp_path / "rcsdnode.gpkg")
    assert captured["mainnodeid"] == "100"
    assert captured["out_root"] == str(tmp_path / "out")
    assert captured["max_cases"] is None
    assert captured["workers"] == 1
    assert captured["buffer_m"] == 120.0
    assert captured["debug"] is True
    assert captured["debug_render_root"] == str(tmp_path / "renders")
    assert captured["review_mode"] is True


def test_t02_virtual_intersection_poc_cli_accepts_full_input_mode_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["input_mode"] = args.input_mode
        captured["mainnodeid"] = args.mainnodeid
        captured["max_cases"] = args.max_cases
        captured["workers"] = args.workers
        captured["out_root"] = args.out_root
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_virtual_intersection_poc", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-virtual-intersection-poc",
            "--input-mode",
            "full-input",
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--roads_path",
            str(tmp_path / "roads.gpkg"),
            "--drivezone_path",
            str(tmp_path / "drivezone.gpkg"),
            "--rcsdroad_path",
            str(tmp_path / "rcsdroad.gpkg"),
            "--rcsdnode_path",
            str(tmp_path / "rcsdnode.gpkg"),
            "--max-cases",
            "8",
            "--workers",
            "3",
            "--out_dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert captured["input_mode"] == "full-input"
    assert captured["mainnodeid"] is None
    assert captured["max_cases"] == 8
    assert captured["workers"] == 3
    assert captured["out_root"] == str(tmp_path / "out")


def test_t02_export_text_bundle_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["nodes_path"] = args.nodes_path
        captured["roads_path"] = args.roads_path
        captured["drivezone_path"] = args.drivezone_path
        captured["rcsdroad_path"] = args.rcsdroad_path
        captured["rcsdnode_path"] = args.rcsdnode_path
        captured["mainnodeid"] = args.mainnodeid
        captured["out_txt"] = args.out_txt
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_export_text_bundle", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-export-text-bundle",
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--roads_path",
            str(tmp_path / "roads.gpkg"),
            "--drivezone_path",
            str(tmp_path / "drivezone.gpkg"),
            "--rcsdroad_path",
            str(tmp_path / "rcsdroad.gpkg"),
            "--rcsdnode_path",
            str(tmp_path / "rcsdnode.gpkg"),
            "--mainnodeid",
            "100",
            "--out_txt",
            str(tmp_path / "bundle.txt"),
        ]
    )

    assert exit_code == 0
    assert captured["nodes_path"] == str(tmp_path / "nodes.gpkg")
    assert captured["roads_path"] == str(tmp_path / "roads.gpkg")
    assert captured["drivezone_path"] == str(tmp_path / "drivezone.gpkg")
    assert captured["rcsdroad_path"] == str(tmp_path / "rcsdroad.gpkg")
    assert captured["rcsdnode_path"] == str(tmp_path / "rcsdnode.gpkg")
    assert captured["mainnodeid"] == ["100"]
    assert captured["out_txt"] == str(tmp_path / "bundle.txt")


def test_t02_export_text_bundle_cli_accepts_multiple_mainnodeids(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["mainnodeid"] = args.mainnodeid
        captured["out_txt"] = args.out_txt
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_export_text_bundle", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-export-text-bundle",
            "--nodes_path",
            str(tmp_path / "nodes.gpkg"),
            "--roads_path",
            str(tmp_path / "roads.gpkg"),
            "--drivezone_path",
            str(tmp_path / "drivezone.gpkg"),
            "--rcsdroad_path",
            str(tmp_path / "rcsdroad.gpkg"),
            "--rcsdnode_path",
            str(tmp_path / "rcsdnode.gpkg"),
            "--mainnodeid",
            "100",
            "200",
            "300",
            "--out_txt",
            str(tmp_path / "bundle.txt"),
        ]
    )

    assert exit_code == 0
    assert captured["mainnodeid"] == ["100", "200", "300"]
    assert captured["out_txt"] == str(tmp_path / "bundle.txt")


def test_t02_decode_text_bundle_cli_accepts_expected_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["bundle_txt"] = args.bundle_txt
        captured["out_dir"] = args.out_dir
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_decode_text_bundle", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-decode-text-bundle",
            "--bundle_txt",
            str(tmp_path / "bundle.txt"),
            "--out_dir",
            str(tmp_path / "decoded"),
        ]
    )

    assert exit_code == 0
    assert captured["bundle_txt"] == str(tmp_path / "bundle.txt")
    assert captured["out_dir"] == str(tmp_path / "decoded")


def test_t02_decode_text_bundle_cli_allows_default_output_dir(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_cmd(args) -> int:
        captured["bundle_txt"] = args.bundle_txt
        captured["out_dir"] = args.out_dir
        return 0

    monkeypatch.setattr(cli, "_cmd_t02_decode_text_bundle", _fake_cmd)

    exit_code = cli.main(
        [
            "t02-decode-text-bundle",
            "--bundle_txt",
            str(tmp_path / "765003.txt"),
        ]
    )

    assert exit_code == 0
    assert captured["bundle_txt"] == str(tmp_path / "765003.txt")
    assert captured["out_dir"] is None
