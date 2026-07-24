from rcsd_topo_poc.modules.p05_neural_road_generation import (
    JSGP1CandidateConfig,
    JSGP1OracleConfig,
    build_jsg_p1_candidate_run,
    solve_jsg_p1_oracle_run,
)


def test_p1_public_api_exposes_candidate_and_oracle_stages() -> None:
    assert JSGP1CandidateConfig.__name__ == "JSGP1CandidateConfig"
    assert JSGP1OracleConfig.__name__ == "JSGP1OracleConfig"
    assert callable(build_jsg_p1_candidate_run)
    assert callable(solve_jsg_p1_oracle_run)
    assert "truth" not in JSGP1CandidateConfig.__dataclass_fields__
    assert "p0_truth_run_root" in JSGP1OracleConfig.__dataclass_fields__
