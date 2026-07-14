from .runner import run_t06_segment_fusion_precheck
from .schemas import T06PrecheckArtifacts, T06Step1Artifacts, T06Step2Artifacts, T06Step3Artifacts
from .step1_identify_fusion_units import run_t06_step1_identify_fusion_units
from .step2_extract_rcsd_segments import run_t06_step2_extract_rcsd_segments

__all__ = [
    "T06PrecheckArtifacts",
    "T06Step1Artifacts",
    "T06Step2Artifacts",
    "T06Step3Artifacts",
    "run_t06_segment_fusion_precheck",
    "run_t06_step1_identify_fusion_units",
    "run_t06_step2_extract_rcsd_segments",
    "run_t06_step3_segment_replacement",
    "run_t06_rcsd_unreplaced_attribution",
]


def __getattr__(name: str):
    if name == "run_t06_step3_segment_replacement":
        from .step3_segment_replacement import run_t06_step3_segment_replacement

        globals()[name] = run_t06_step3_segment_replacement
        return run_t06_step3_segment_replacement
    if name == "run_t06_rcsd_unreplaced_attribution":
        from .rcsd_unreplaced_attribution import run_t06_rcsd_unreplaced_attribution

        globals()[name] = run_t06_rcsd_unreplaced_attribution
        return run_t06_rcsd_unreplaced_attribution
    raise AttributeError(name)
