from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.pto_candidates import canonical_edit_payload
from rcsd_topo_poc.modules.p05_neural_road_generation import pto_lineage
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_lineage import load_strategy_replay_cases
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import (
    PTOCandidateConfig,
    PTOStrategyReplay,
)


def test_canonical_payload_ignores_artifact_source_role() -> None:
    first = {
        "id": "10",
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        "properties": {"id": 10, "source": 1},
        "source_role": "strategy_output",
    }
    second = {**first, "source_role": "label_truth"}
    left = canonical_edit_payload(
        stage="FINAL_NODE",
        object_kind="Node",
        group_id="FINAL_NODE:BASE:10",
        action="COPY",
        base_object_id="10",
        output_payloads=[first],
    )
    right = canonical_edit_payload(
        stage="FINAL_NODE",
        object_kind="Node",
        group_id="FINAL_NODE:BASE:10",
        action="COPY",
        base_object_id="10",
        output_payloads=[second],
    )
    assert left == right
    assert "source_role" not in left["output_payloads"][0]


def test_candidate_config_rejects_duplicate_strategy_case_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicates"):
        PTOStrategyReplay(
            family="T10-Error",
            code_root=tmp_path,
            code_commit="a" * 40,
            run_root=tmp_path,
            expected_case_ids=("1", "1"),
        )


def test_candidate_config_requires_strategy_replay(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        PTOCandidateConfig(
            strategy_replays=(),
            allowed_data_root=tmp_path,
            output_root=tmp_path,
            run_id="run",
        )


def test_lineage_rejects_approved_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    replay = PTOStrategyReplay(
        family="T10-Error",
        code_root=tmp_path,
        code_commit="a" * 40,
        run_root=tmp_path,
    )
    config = PTOCandidateConfig(
        strategy_replays=(replay,),
        allowed_data_root=tmp_path,
        output_root=tmp_path,
        run_id="run",
        excluded_business_ids=("1213556_1263661",),
        expected_case_count=1,
        verify_git_commit=False,
    )
    monkeypatch.setattr(
        pto_lineage,
        "_validate_replay_header",
        lambda *_args, **_kwargs: (
            tmp_path,
            {
                "cases": [
                    {
                        "case_id": "segment_1213556_1263661",
                        "overall_status": "passed",
                        "stage_statuses": {"t06_step3": "passed"},
                    }
                ]
            },
        ),
    )
    with pytest.raises(ValueError, match="approved exclusion"):
        load_strategy_replay_cases(config)
