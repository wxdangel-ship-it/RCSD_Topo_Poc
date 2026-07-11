from __future__ import annotations

from tests.modules.t10_e2e_orchestration.t10_contract_test_support import *  # noqa: F401,F403


def test_t10_relation_graph_bridge_candidate_extends_existing_side_group(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    case_run_dir = run_root / "cases" / "9001"
    registry = (
        case_run_dir
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s1','s2']\",\"['p1','p2']\",\"[['p1','p2']]\",audit",
            ]
        ),
        encoding="utf-8",
    )
    probe = registry.parent / "t06_rcsd_buffer_only_probe.csv"
    probe.write_text(
        "\n".join(
            [
                "swsd_segment_id,probe_status,buffer_only_candidate_status,failure_business_category,"
                "original_rcsd_pair_nodes,candidate_rcsd_node_ids",
                "s1_s2,completed,corridor_found,directionality_mismatch_fixable,"
                "\"['p1','p2']\",\"['p1','p2','bridge','noise']\"",
            ]
        ),
        encoding="utf-8",
    )

    t05_dir = case_run_dir / "t05" / "t05_phase2"
    t05_dir.mkdir(parents=True)
    (t05_dir / "relation_graph_consumability_audit.csv").write_text(
        "\n".join(
            [
                "target_id,base_id,relation_status,graph_consumable,graph_consumability_status,"
                "matched_rcsdnode_ids,incident_rcsdnode_ids,source_modules,source_case_ids,scenes,reasons,"
                "recommended_action",
                "s1,p1,0,1,base_node_graph_incident,p1,p1,T07,s1,direct,matched,consume_as_relation",
                "s2,p2,0,1,base_node_graph_incident,p2,p2,T07,s2,direct,matched,consume_as_relation",
                "side,bridge,0,1,base_node_graph_incident,bridge,bridge,T07,side,direct,matched,consume_as_relation",
                "mid,mid_base,0,1,base_node_group_graph_incident,"
                "mid_group|mid_context|mid_base,mid_group|mid_context,T07|T10_SIDE_GROUP,"
                "mid|9001,direct,multiple_base_id_merged,consume_as_relation",
            ]
        ),
        encoding="utf-8",
    )
    (t05_dir / "rcsd_junctionization_audit.csv").write_text(
        "\n".join(
            [
                "target_id,surface_id,source_module,source_case_id,scene,action,status,base_id,reason,"
                "original_rcsdroad_ids,new_rcsdroad_ids,original_rcsdnode_ids,new_rcsdnode_ids,"
                "grouped_rcsdnode_ids,selected_main_rcsdnode_id,projection_point_count,split_point_count,"
                "skipped_reason,geometry_mode,multi_base_relation,blocking_error",
                "mid,JAS:mid,T07|T10_SIDE_GROUP,mid|9001,direct,group_existing_rcsd_nodes,0,"
                "mid_base,multiple_base_id_merged,,,mid_group|mid_base,,mid_group|mid_base,"
                "mid_base,0,0,,success_line,1,0",
            ]
        ),
        encoding="utf-8",
    )
    write_gpkg(
        t05_dir / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "r1", "snodeid": "p2", "enodeid": "bridge"}, "geometry": LineString([(0, 0), (1, 0)])},
            {"properties": {"id": "r2", "snodeid": "bridge", "enodeid": "x1"}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "r3", "snodeid": "x1", "enodeid": "x2"}, "geometry": LineString([(2, 0), (3, 0)])},
            {"properties": {"id": "r4", "snodeid": "x2", "enodeid": "mid_context"}, "geometry": LineString([(3, 0), (4, 0)])},
            {"properties": {"id": "r5", "snodeid": "p2", "enodeid": "noise"}, "geometry": LineString([(0, 1), (1, 1)])},
        ],
        crs_text="EPSG:3857",
        layer_name="rcsdroad_out",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(case_run_dir)}],
    )

    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]
    assert artifacts.side_group_endpoint_candidate_count == 1
    assert endpoint_rows[0]["swsd_segment_id"] == "s1_s2"
    assert endpoint_rows[0]["target_id"] == "mid"
    assert endpoint_rows[0]["endpoint_index"] == "1"
    assert endpoint_rows[0]["rcsd_primary_node_id"] == "mid_base"
    assert endpoint_rows[0]["candidate_rcsdnode_ids"] == "mid_base|bridge"
    assert endpoint_rows[0]["side_group_action"] == "supplement_existing_relation_with_relation_graph_bridge"


def test_t10_upstream_feedback_excludes_side_group_without_new_rcsd_nodes(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s1','s2']\",\"['100','200']\",\"[['100','200']]\",audit",
                "s3_s4,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s3','s4']\",\"['300','400']\",\"[['300','401']]\",audit",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    segments = json.loads(artifacts.segments_json.read_text(encoding="utf-8"))["rows"]
    side_group_rows = json.loads(artifacts.side_group_candidates_json.read_text(encoding="utf-8"))["rows"]
    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]

    assert {row["swsd_segment_id"] for row in segments} == {"s1_s2", "s3_s4"}
    assert artifacts.side_group_candidate_count == 1
    assert artifacts.side_group_endpoint_candidate_count == 1
    assert side_group_rows[0]["swsd_segment_id"] == "s3_s4"
    assert {row["target_id"] for row in endpoint_rows} == {"s4"}
    assert {row["swsd_segment_id"] for row in endpoint_rows} == {"s3_s4"}


def test_t10_case_runner_blocks_downstream_after_failed_stage(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_run_stage(**kwargs):
        stage_id = kwargs["stage_id"]
        calls.append(stage_id)
        assert stage_id == "t01"
        return (
            {
                "stage_id": "t01",
                "stage": "t01",
                "module_id": "t01_data_preprocess",
                "status": "failed",
                "outputs": {"t01_roads": str(tmp_path / "partial_roads.gpkg")},
            },
            {"t01_roads": str(tmp_path / "partial_roads.gpkg")},
        )

    monkeypatch.setattr(t10_case_runner, "_run_stage", fake_run_stage)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="run_001",
        stop_after="t03",
        continue_on_error=True,
        exit_on_incomplete=True,
    )

    case_summary_path = artifacts.run_root / "cases" / "9001" / "t10_e2e_case_run_summary.json"
    case_summary = json.loads(case_summary_path.read_text(encoding="utf-8"))
    t07_stage = json.loads((artifacts.run_root / "cases" / "9001" / "t07" / "t07_stage.json").read_text(encoding="utf-8"))

    assert calls == ["t01"]
    assert case_summary["overall_status"] == "failed"
    assert case_summary["stage_statuses"] == {"t01": "failed", "t07": "blocked", "t03": "blocked"}
    assert t07_stage["stage"] == "t07"
    assert t07_stage["blocked_reason"] == "Previous stage did not produce required handoff."


def test_t10_case_runner_discovers_flat_multi_case_package(tmp_path: Path) -> None:
    package_dir = tmp_path / "flat_package"
    for case_id in ("9001", "2001"):
        case_dir = package_dir / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "t10_case_evidence_manifest.json").write_text(
            json.dumps({"scope": {"case_id": case_id}, "included_external_inputs": []}),
            encoding="utf-8",
        )
    (package_dir / "_source_bundles").mkdir()

    case_dirs = t10_case_runner._discover_case_dirs(package_root=package_dir, case_ids=None)
    selected_case_dirs = t10_case_runner._discover_case_dirs(package_root=package_dir, case_ids=["9001"])

    assert [path.name for path in case_dirs] == ["2001", "9001"]
    assert [path.name for path in selected_case_dirs] == ["9001"]


def test_t10_feedback_iteration_passes_endpoint_candidates_and_keeps_no_regression_guard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["old_segment", "new_segment"] if side_group_endpoint_candidate_path else ["old_segment"],
            emit_side_group_problem=side_group_endpoint_candidate_path is None,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=1,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    comparison = summary["feedback_comparison"]
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[1].name == "t10_upstream_side_group_endpoint_candidates.csv"
    assert summary["passed"] is True
    assert summary["feedback_regression_guard_passed"] is True
    assert comparison["removed_replaced_segment_ids"] == []
    assert comparison["added_replaced_segment_ids"] == ["new_segment"]
    assert summary["feedback_iteration_completed_count"] == 1


def test_t10_feedback_iteration_stops_when_endpoint_candidates_converge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["kept_segment"],
            emit_side_group_problem=True,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=2,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1] is not None
    assert summary["feedback_iteration_pass_count"] == 2
    assert summary["feedback_iteration_completed_count"] == 1
    assert manifest["final_iteration"]["feedback_stop_reason"] == "feedback_candidates_converged"


def test_t10_feedback_iteration_accumulates_endpoint_candidates_across_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        if len(calls) == 1:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment"],
                emit_side_group_problem=True,
                side_group_segment_id="a1_a2",
                side_group_candidate_pair="101|201",
            )
        elif len(calls) == 2:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment", "first_feedback_segment"],
                emit_side_group_problem=True,
                side_group_segment_id="b1_b2",
                side_group_candidate_pair="301|401",
            )
        else:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment", "first_feedback_segment", "second_feedback_segment"],
                emit_side_group_problem=False,
            )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=2,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert len(calls) == 3
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[2] is not None
    cumulative_rows = list(csv.DictReader(calls[2].open(newline="", encoding="utf-8")))
    assert {row["swsd_segment_id"] for row in cumulative_rows} == {"a1_a2", "b1_b2"}
    assert summary["feedback_comparison"]["added_replaced_segment_ids"] == [
        "first_feedback_segment",
        "second_feedback_segment",
    ]
    assert summary["feedback_regression_guard_passed"] is True


def test_t10_feedback_iteration_passes_pair_anchor_endpoint_clusters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        pair_anchor_endpoint_cluster_path = kwargs.get("pair_anchor_endpoint_cluster_path")
        calls.append(pair_anchor_endpoint_cluster_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["old_segment", "pair_anchor_feedback_segment"]
            if pair_anchor_endpoint_cluster_path
            else ["old_segment"],
            emit_side_group_problem=False,
            emit_pair_anchor_problem=pair_anchor_endpoint_cluster_path is None,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=1,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[1].name == "iteration_00_auto_pair_anchor_endpoint_clusters.csv"
    assert summary["feedback_comparison"]["added_replaced_segment_ids"] == ["pair_anchor_feedback_segment"]
    assert summary["feedback_regression_guard_passed"] is True


def test_t10_feedback_regression_guard_detects_removed_replaced_segment(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    _write_feedback_iteration_case_outputs(
        baseline / "cases" / "9001",
        replaced_segments=["kept_segment", "removed_segment"],
        emit_side_group_problem=False,
    )
    _write_feedback_iteration_case_outputs(
        final / "cases" / "9001",
        replaced_segments=["kept_segment"],
        emit_side_group_problem=False,
    )

    comparison = t10_case_runner._compare_feedback_iteration_outputs(
        baseline_run_root=baseline,
        final_run_root=final,
    )

    assert comparison["removed_replaced_segment_ids"] == ["removed_segment"]
    assert comparison["added_replaced_segment_ids"] == []


def test_t10_case_runner_summary_exposes_completion_status(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "9001"
    case_dir.mkdir(parents=True)

    def fake_discover_case_dirs(*, package_root, case_ids):
        return [case_dir]

    def fake_run_one_case(**kwargs):
        case_run_dir = kwargs["run_root"] / "cases" / "9001"
        case_run_dir.mkdir(parents=True)
        (case_run_dir / "t10_e2e_case_run_manifest.json").write_text("{}", encoding="utf-8")
        (case_run_dir / "t10_t06_funnel.json").write_text("{}", encoding="utf-8")
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {"t09_step3": "passed"},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    def fake_write_upstream_feedback(*, run_root, case_results):
        for name in [
            "segments",
            "summary",
            "relations",
            "relation_summary",
            "side_group_candidates",
            "side_group_endpoint_candidates",
            "pair_anchor_endpoint_clusters",
        ]:
            (run_root / f"{name}.csv").write_text("", encoding="utf-8")
            (run_root / f"{name}.json").write_text("[]", encoding="utf-8")
        return SimpleNamespace(
            segments_csv=run_root / "segments.csv",
            segments_json=run_root / "segments.json",
            summary_csv=run_root / "summary.csv",
            summary_json=run_root / "summary.json",
            relations_csv=run_root / "relations.csv",
            relations_json=run_root / "relations.json",
            relation_summary_csv=run_root / "relation_summary.csv",
            relation_summary_json=run_root / "relation_summary.json",
            side_group_candidates_csv=run_root / "side_group_candidates.csv",
            side_group_candidates_json=run_root / "side_group_candidates.json",
            side_group_endpoint_candidates_csv=run_root / "side_group_endpoint_candidates.csv",
            side_group_endpoint_candidates_json=run_root / "side_group_endpoint_candidates.json",
            pair_anchor_endpoint_clusters_csv=run_root / "pair_anchor_endpoint_clusters.csv",
            pair_anchor_endpoint_clusters_json=run_root / "pair_anchor_endpoint_clusters.json",
            segment_count=0,
            summary_count=0,
            relation_count=0,
            relation_summary_count=0,
            side_group_candidate_count=0,
            side_group_endpoint_candidate_count=0,
            pair_anchor_endpoint_cluster_count=0,
        )

    monkeypatch.setattr(t10_case_runner, "_discover_case_dirs", fake_discover_case_dirs)
    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)
    monkeypatch.setattr(t10_case_runner, "write_t10_upstream_feedback", fake_write_upstream_feedback)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="status_run",
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["passed"] is True
    assert summary["completed_case_count"] == 1
    assert summary["duration_seconds"] >= 0
    assert manifest["status"] == "passed"
    assert manifest["passed"] is True


def test_t10_case_runner_writes_t06_visual_check_summary(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "9001"
    case_dir.mkdir(parents=True)

    def fake_discover_case_dirs(*, package_root, case_ids):
        return [case_dir]

    def fake_run_one_case(**kwargs):
        case_run_dir = kwargs["run_root"] / "cases" / "9001"
        step2 = case_run_dir / "t06_step12" / "t06" / "step2_extract_rcsd_segments"
        step3 = case_run_dir / "t06_step12" / "t06" / "step3_segment_replacement"
        t07 = case_run_dir / "t07" / "t07" / "step2_anchor_recognition"
        t03 = case_run_dir / "t03" / "t03"
        t04 = case_run_dir / "t04" / "t04"
        t05 = case_run_dir / "t05" / "t05_phase1"
        for path in [case_run_dir / "t01", step2, step3, t07, t03, t04, t05]:
            path.mkdir(parents=True, exist_ok=True)
        write_gpkg(
            case_run_dir / "t01" / "segment.gpkg",
            [{"properties": {"id": "s1_s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="segment",
        )
        write_gpkg(
            case_run_dir / "t01" / "roads.gpkg",
            [{"properties": {"id": "sw1", "snodeid": "s1", "enodeid": "s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="roads",
        )
        write_gpkg(
            t07 / "nodes.gpkg",
            [
                {"properties": {"id": "s1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "s2"}, "geometry": Point(10, 0)},
            ],
            crs_text="EPSG:3857",
            layer_name="nodes",
        )
        for path in [
            t07 / "t07_rcsdintersection_anchor_surface.gpkg",
            t03 / "virtual_intersection_polygons.gpkg",
            t04 / "divmerge_virtual_anchor_surface.gpkg",
            t04 / "divmerge_virtual_anchor_surface_audit.gpkg",
            t05 / "junction_anchor_surface.gpkg",
        ]:
            write_gpkg(
                path,
                [{"properties": {"id": "surface1"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=path.stem,
            )
        for name in [
            "t06_rcsd_segment_replaceable.gpkg",
            "t06_segment_replacement_plan.gpkg",
            "t06_segment_replacement_problem_registry.gpkg",
        ]:
            write_gpkg(
                step2 / name,
                [{"properties": {"swsd_segment_id": "s1_s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=Path(name).stem,
            )
        write_gpkg(
            step3 / "t06_frcsd_road.gpkg",
            [
                {
                    "properties": {"id": "rc_right", "snodeid": "r1", "enodeid": "r2", "source": 1, "formway": 128},
                    "geometry": LineString([(0, 0), (10, 0)]),
                },
                {
                    "properties": {"id": "sw_right", "snodeid": "s1", "enodeid": "s2", "source": 2, "formway": 128},
                    "geometry": LineString([(0, 0), (10, 0)]),
                },
            ],
            crs_text="EPSG:3857",
            layer_name="t06_frcsd_road",
        )
        write_gpkg(
            step3 / "t06_frcsd_node.gpkg",
            [
                {"properties": {"id": "r1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "r2"}, "geometry": Point(10, 0)},
                {"properties": {"id": "s1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "s2"}, "geometry": Point(10, 0)},
            ],
            crs_text="EPSG:3857",
            layer_name="t06_frcsd_node",
        )
        write_gpkg(
            step3 / "t06_step3_swsd_frcsd_segment_relation.gpkg",
            [{"properties": {"swsd_segment_id": "s1_s2", "relation_status": "replaced"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="t06_step3_swsd_frcsd_segment_relation",
        )
        for path in [
            step3 / "t06_step3_topology_connectivity_audit.gpkg",
            step3 / "t06_step3_surface_topology_audit.gpkg",
        ]:
            write_gpkg(
                path,
                [{"properties": {"audit_status": "pass"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=path.stem,
            )
        (step2 / "t06_step2_summary.json").write_text(
            json.dumps(
                {
                    "replaceable_count": 1,
                    "replacement_plan_count": 1,
                    "replacement_plan_ready_count": 1,
                    "problem_registry_count": 0,
                    "rejected_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (step3 / "t06_step3_summary.json").write_text(
            json.dumps(
                {
                    "replacement_unit_success_count": 1,
                    "replacement_unit_failure_count": 0,
                    "removed_swsd_road_count": 1,
                    "added_rcsd_road_count": 1,
                    "frcsd_road_count": 2,
                    "frcsd_node_count": 4,
                }
            ),
            encoding="utf-8",
        )
        (case_run_dir / "t10_e2e_case_run_manifest.json").write_text("{}", encoding="utf-8")
        (case_run_dir / "t10_t06_funnel.json").write_text("{}", encoding="utf-8")
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {"t06_step3": "passed"},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    def fake_write_upstream_feedback(*, run_root, case_results):
        for name in [
            "segments",
            "summary",
            "relations",
            "relation_summary",
            "side_group_candidates",
            "side_group_endpoint_candidates",
            "pair_anchor_endpoint_clusters",
        ]:
            (run_root / f"{name}.csv").write_text("", encoding="utf-8")
            (run_root / f"{name}.json").write_text("[]", encoding="utf-8")
        return SimpleNamespace(
            segments_csv=run_root / "segments.csv",
            segments_json=run_root / "segments.json",
            summary_csv=run_root / "summary.csv",
            summary_json=run_root / "summary.json",
            relations_csv=run_root / "relations.csv",
            relations_json=run_root / "relations.json",
            relation_summary_csv=run_root / "relation_summary.csv",
            relation_summary_json=run_root / "relation_summary.json",
            side_group_candidates_csv=run_root / "side_group_candidates.csv",
            side_group_candidates_json=run_root / "side_group_candidates.json",
            side_group_endpoint_candidates_csv=run_root / "side_group_endpoint_candidates.csv",
            side_group_endpoint_candidates_json=run_root / "side_group_endpoint_candidates.json",
            pair_anchor_endpoint_clusters_csv=run_root / "pair_anchor_endpoint_clusters.csv",
            pair_anchor_endpoint_clusters_json=run_root / "pair_anchor_endpoint_clusters.json",
            segment_count=0,
            summary_count=0,
            relation_count=0,
            relation_summary_count=0,
            side_group_candidate_count=0,
            side_group_endpoint_candidate_count=0,
            pair_anchor_endpoint_cluster_count=0,
        )

    monkeypatch.setattr(t10_case_runner, "_discover_case_dirs", fake_discover_case_dirs)
    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)
    monkeypatch.setattr(t10_case_runner, "write_t10_upstream_feedback", fake_write_upstream_feedback)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="visual_check_run",
    )

    run_summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    visual_summary = json.loads(artifacts.t06_visual_check_summary_json.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(artifacts.t06_visual_check_summary_csv.open(newline="", encoding="utf-8")))
    row = rows[0]

    assert Path(run_summary["t06_visual_check_summary_json"]).is_file()
    assert visual_summary["case_count"] == 1
    assert row["case_id"] == "9001"
    assert row["crs_status"] == "passed"
    assert row["missing_visual_layer_count"] == "0"
    assert row["advance_right_count"] == "2"
    assert row["advance_right_rcsd_count"] == "1"
    assert row["advance_right_swsd_count"] == "1"
    assert row["swsd_advance_duplicate_ge20pct_count"] == "1"
    assert row["advance_endpoint_missing_road_count"] == "0"
    assert row["spatial_check_status"] == "passed"


def test_t10_t06_visual_check_tolerates_geometryless_plan_rows(tmp_path: Path) -> None:
    import fiona

    road = tmp_path / "t06_frcsd_road.gpkg"
    node = tmp_path / "t06_frcsd_node.gpkg"
    plan = tmp_path / "t06_segment_replacement_plan.gpkg"
    write_gpkg(
        road,
        [{"properties": {"id": "r1", "snodeid": "n1", "enodeid": "n2", "source": 1, "formway": 128}, "geometry": LineString([(0, 0), (1, 0)])}],
        crs_text="EPSG:3857",
        layer_name="t06_frcsd_road",
    )
    write_gpkg(
        node,
        [
            {"properties": {"id": "n1"}, "geometry": Point(0, 0)},
            {"properties": {"id": "n2"}, "geometry": Point(1, 0)},
        ],
        crs_text="EPSG:3857",
        layer_name="t06_frcsd_node",
    )
    with fiona.open(
        plan,
        "w",
        driver="GPKG",
        layer="t06_segment_replacement_plan",
        crs="EPSG:3857",
        schema={"geometry": "None", "properties": {"swsd_segment_id": "str"}},
    ) as collection:
        collection.write({"properties": {"swsd_segment_id": "s1_s2"}, "geometry": None})

    metrics = t10_case_runner._t06_visual_spatial_metrics(
        {
            "t06_frcsd_road_gpkg": road,
            "t06_frcsd_node_gpkg": node,
            "t06_segment_replacement_plan_gpkg": plan,
        }
    )

    assert metrics["crs_status"] == "passed"
    assert metrics["spatial_check_status"] == "passed"
    assert metrics["advance_right_count"] == 1
    assert metrics["advance_endpoint_missing_road_count"] == 0


def test_t10_innernet_full_pipeline_finalize_existing_run_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    run_root = tmp_path / "t10_existing_run"
    t06_step3 = run_root / "t06_segment_fusion_precheck" / "t06_innernet_precheck" / "step3_segment_replacement"
    t09_step3 = run_root / "t09_swsd_field_rule_restoration" / "t09_step3"
    t06_step3.mkdir(parents=True)
    t09_step3.mkdir(parents=True)
    frcsd_road = t06_step3 / "t06_frcsd_road.gpkg"
    frcsd_node = t06_step3 / "t06_frcsd_node.gpkg"
    frcsd_restriction = t09_step3 / "frcsd_restriction.gpkg"
    frcsd_road.touch()
    frcsd_node.touch()
    frcsd_restriction.touch()
    manifest = {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "repo_dir": str(repo_root),
        "created_at_utc": "2026-06-20T00:00:00+00:00",
        "status": "running",
        "passed": False,
        "inputs": {},
        "outputs": {},
        "stage_order": ["t06_step3", "t09"],
        "stages": {
            "t06_step3": {
                "stage_id": "t06_step3",
                "module_id": "T06",
                "status": "passed",
                "outputs": {
                    "frcsd_road": str(frcsd_road),
                    "frcsd_node": str(frcsd_node),
                },
            },
            "t09": {
                "stage_id": "t09",
                "module_id": "T09",
                "status": "passed",
                "outputs": {
                    "frcsd_restriction": str(frcsd_restriction),
                },
            },
        },
    }
    (run_root / "t10_innernet_full_pipeline_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/t10_run_innernet_full_pipeline.sh"],
        cwd=repo_root,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHON_BIN": sys.executable,
            "REPO_DIR": str(repo_root),
            "FINALIZE_EXISTING": "1",
            "RESUME_RUN_ROOT": str(run_root),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    summary = json.loads((run_root / "t10_innernet_full_pipeline_summary.json").read_text(encoding="utf-8"))
    updated_manifest = json.loads(
        (run_root / "t10_innernet_full_pipeline_manifest.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "passed"
    assert summary["passed"] is True
    assert summary["missing_final_outputs"] == []
    assert summary["t06_frcsd_road"] == str(frcsd_road)
    assert summary["t06_frcsd_node"] == str(frcsd_node)
    assert summary["t09_frcsd_restriction"] == str(frcsd_restriction)
    assert updated_manifest["status"] == "passed"
    assert updated_manifest["passed"] is True
