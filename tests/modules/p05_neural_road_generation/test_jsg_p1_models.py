from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    JSGP1Candidate,
    JSGP1CandidateConfig,
    P1ObjectType,
    P1Stage,
)


def test_candidate_identity_is_stable_and_truth_flags_are_closed() -> None:
    kwargs = {
        "case_key": "T10:fixture",
        "stage": P1Stage.PTO_A,
        "object_type": P1ObjectType.JUNCTION,
        "object_key": "j1",
        "group_id": "PTO_A:JUNCTION:j1",
        "payload": {"state": "REVIEW", "junction_id": "j1"},
        "dependencies": ("b", "a", "a"),
        "evidence_refs": (EvidenceRef("t01", "input.gpkg", "abc", "j1"),),
        "source_kinds": ("T01_INFERENCE_EVIDENCE",),
    }
    first = JSGP1Candidate.build(**kwargs)
    second = JSGP1Candidate.build(**kwargs)

    assert first.candidate_id == second.candidate_id
    assert first.dependencies == ("a", "b")
    assert first.truth_derived is False
    assert first.label_only is False
    assert first.to_dict()["stage"] == "PTO_A"


def test_candidate_config_has_no_truth_or_label_input() -> None:
    config = JSGP1CandidateConfig(Path("pto"), Path("out"), "run")
    assert "truth" not in config.__dataclass_fields__
    assert "label" not in config.__dataclass_fields__


def test_candidate_config_rejects_empty_run_id() -> None:
    with pytest.raises(ValueError, match="run_id"):
        JSGP1CandidateConfig(Path("pto"), Path("out"), "")
