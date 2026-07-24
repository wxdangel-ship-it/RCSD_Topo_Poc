from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    SchemeACarrierGraphSetScorer,
    parameter_count,
)


class SchemeASegmentSafetyHead(SchemeACarrierGraphSetScorer):
    """Candidate-set network whose output can only accept or abstain.

    The architecture deliberately matches the already-audited set encoder, but this
    head is trained only on Segment groups with frozen base-OOF signals.  Callers
    must never use its top candidate as a replacement carrier.
    """


__all__ = ["SchemeASegmentSafetyHead", "parameter_count"]
