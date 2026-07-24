from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_models import (
    JSGP3DatasetConfig,
    JSGP3OOFConfig,
    P3FoldVocabulary,
)


def test_p3_configs_validate_training_boundary() -> None:
    dataset = JSGP3DatasetConfig(
        p1_candidate_run_root=Path("p1"),
        p2_dataset_run_root=Path("p2"),
        output_root=Path("out"),
        run_id="dataset",
    )
    assert dataset.expected_candidate_count == 712_799
    with pytest.raises(ValueError, match="unique"):
        JSGP3OOFConfig(
            context_dataset_run_root=Path("context"),
            p2_dataset_run_root=Path("p2"),
            p1_candidate_run_root=Path("p1"),
            p1_oracle_run_root=Path("oracle"),
            p0_truth_run_root=Path("p0"),
            r2_oracle_run_root=Path("r2"),
            output_root=Path("out"),
            run_id="oof",
            seeds=(17, 17),
        )


def test_fold_vocabulary_has_stable_signature() -> None:
    vocabulary = P3FoldVocabulary(
        candidate_tokens={"b": 2, "a": 1},
        context_tokens={"ctx": 1},
        object_types={"JUNCTION": 1},
        train_case_keys=("train",),
        inner_validation_case_keys=("inner",),
        held_out_case_keys=("held",),
        dataset_manifest_sha256="dataset",
    )
    assert vocabulary.to_dict()["vocabulary_signature"] == vocabulary.to_dict()[
        "vocabulary_signature"
    ]
