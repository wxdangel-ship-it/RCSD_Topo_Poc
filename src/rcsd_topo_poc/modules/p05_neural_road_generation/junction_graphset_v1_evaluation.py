from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_materializer import (
    MaterializedJunctionResult,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorState,
    JunctionPredictionError,
    JunctionResultPrediction,
    QualityState,
    SurfaceMode,
)


@dataclass(frozen=True)
class CompleteResultSignature:
    step1_state: str
    surface_mode: str
    selected_surface_keys: tuple[str, ...]
    virtual_surface_member_keys: tuple[str, ...]
    anchor_state: str
    associated_node_keys: tuple[str, ...]
    associated_road_keys: tuple[str, ...]
    main_anchor_key: str | None
    node_equivalence_keys: tuple[tuple[str, ...], ...]
    road_breaks: tuple[tuple[str, tuple[float, ...]], ...]
    topology_signature: str
    quality_state: str

    @classmethod
    def from_prediction(
        cls,
        prediction: JunctionResultPrediction,
    ) -> CompleteResultSignature:
        if prediction.abstain or prediction.anchor_result.state != AnchorState.SUCCESS:
            raise JunctionPredictionError(
                "a complete automatic signature requires a successful anchor result"
            )
        return cls(
            step1_state=prediction.step1_drivezone_state.value,
            surface_mode=prediction.surface_plan.mode.value,
            selected_surface_keys=tuple(
                sorted(
                    ref.key
                    for ref in prediction.surface_plan.selected_rcsdintersection_refs
                )
            ),
            virtual_surface_member_keys=tuple(
                sorted(ref.key for ref in prediction.surface_plan.virtual_member_refs)
            ),
            anchor_state=prediction.anchor_result.state.value,
            associated_node_keys=tuple(
                sorted(ref.key for ref in prediction.anchor_result.associated_rcsd_node_refs)
            ),
            associated_road_keys=tuple(
                sorted(ref.key for ref in prediction.anchor_result.associated_rcsd_road_refs)
            ),
            main_anchor_key=(
                prediction.anchor_result.selected_main_anchor.key
                if prediction.anchor_result.selected_main_anchor is not None
                else None
            ),
            node_equivalence_keys=tuple(
                sorted(
                    tuple(sorted(ref.key for ref in group.node_refs))
                    for group in prediction.anchor_result.node_equivalence_classes
                )
            ),
            road_breaks=tuple(
                sorted(
                    (
                        operation.road_ref.key,
                        tuple(float(value) for value in operation.fractions),
                    )
                    for operation in prediction.anchor_result.road_break_operations
                )
            ),
            topology_signature=prediction.post_materialization_topology_signature or "",
            quality_state=prediction.quality_state.value,
        )

    def equivalent_to(
        self,
        expected: CompleteResultSignature,
        *,
        break_fraction_tolerance: float,
    ) -> bool:
        if break_fraction_tolerance < 0.0:
            raise ValueError("break_fraction_tolerance must be non-negative")
        without_breaks = (
            "step1_state",
            "surface_mode",
            "selected_surface_keys",
            "virtual_surface_member_keys",
            "anchor_state",
            "associated_node_keys",
            "associated_road_keys",
            "main_anchor_key",
            "node_equivalence_keys",
            "topology_signature",
            "quality_state",
        )
        if any(getattr(self, field) != getattr(expected, field) for field in without_breaks):
            return False
        if len(self.road_breaks) != len(expected.road_breaks):
            return False
        for actual_break, expected_break in zip(self.road_breaks, expected.road_breaks):
            actual_road, actual_fractions = actual_break
            expected_road, expected_fractions = expected_break
            if actual_road != expected_road or len(actual_fractions) != len(expected_fractions):
                return False
            if any(
                abs(actual - target) > break_fraction_tolerance
                for actual, target in zip(actual_fractions, expected_fractions)
            ):
                return False
        return True


@dataclass(frozen=True)
class JunctionEvaluationGold:
    truth_known: bool
    acceptable_automatic_results: tuple[CompleteResultSignature, ...] = ()
    expected_abnormal_or_abstain: bool = False
    acceptable_fallback_graph_signatures: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.truth_known and (
            self.acceptable_automatic_results
            or self.acceptable_fallback_graph_signatures
        ):
            raise JunctionPredictionError(
                "unknown truth cannot carry invented acceptable results"
            )
        if (
            self.truth_known
            and not self.expected_abnormal_or_abstain
            and not self.acceptable_automatic_results
        ):
            raise JunctionPredictionError(
                "known normal truth requires an acceptable automatic result"
            )


@dataclass(frozen=True)
class JunctionEvaluationItem:
    case_key: str
    prediction: JunctionResultPrediction
    materialized: MaterializedJunctionResult
    gold: JunctionEvaluationGold
    fallback_graph_signature: str | None = None


@dataclass(frozen=True)
class CaseSafetyMetrics:
    case_key: str
    total: int
    known_truth: int
    automatic_accepted: int
    automatic_exact: int
    fallback_count: int
    fallback_exact: int
    final_exact: int
    dangerous_automatic: int
    unknown_automatic: int
    abnormal_expected: int
    abnormal_detected: int

    @property
    def final_exact_rate(self) -> float:
        return self.final_exact / self.known_truth if self.known_truth else 0.0


@dataclass(frozen=True)
class JunctionSafetyReport:
    total: int
    known_truth: int
    automatic_accepted: int
    automatic_exact: int
    fallback_count: int
    fallback_exact: int
    final_exact: int
    dangerous_automatic: int
    unknown_automatic: int
    abnormal_expected: int
    abnormal_detected: int
    release_enabled: bool
    case_metrics: tuple[CaseSafetyMetrics, ...]

    @property
    def automatic_coverage(self) -> float:
        return self.automatic_accepted / self.total if self.total else 0.0

    @property
    def automatic_exact_rate(self) -> float:
        return self.automatic_exact / self.known_truth if self.known_truth else 0.0

    @property
    def fallback_final_exact_rate(self) -> float:
        return self.final_exact / self.known_truth if self.known_truth else 0.0

    @property
    def abnormal_recall(self) -> float:
        return (
            self.abnormal_detected / self.abnormal_expected
            if self.abnormal_expected
            else 0.0
        )

    @property
    def worst_case_final_exact_rate(self) -> float:
        known_cases = tuple(
            metrics.final_exact_rate
            for metrics in self.case_metrics
            if metrics.known_truth
        )
        return min(known_cases) if known_cases else 0.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.update(
            {
                "automatic_coverage": self.automatic_coverage,
                "automatic_exact_rate": self.automatic_exact_rate,
                "fallback_final_exact_rate": self.fallback_final_exact_rate,
                "abnormal_recall": self.abnormal_recall,
                "worst_case_final_exact_rate": self.worst_case_final_exact_rate,
            }
        )
        return payload


@dataclass
class _MutableMetrics:
    total: int = 0
    known_truth: int = 0
    automatic_accepted: int = 0
    automatic_exact: int = 0
    fallback_count: int = 0
    fallback_exact: int = 0
    final_exact: int = 0
    dangerous_automatic: int = 0
    unknown_automatic: int = 0
    abnormal_expected: int = 0
    abnormal_detected: int = 0

    def freeze(self, case_key: str) -> CaseSafetyMetrics:
        return CaseSafetyMetrics(case_key=case_key, **asdict(self))


def _is_automatic_accept(item: JunctionEvaluationItem) -> bool:
    return (
        not item.prediction.abstain
        and not item.materialized.fallback
        and item.materialized.ledger.topology_valid
        and item.prediction.anchor_result.state == AnchorState.SUCCESS
        and item.prediction.quality_state == QualityState.NORMAL
        and item.prediction.surface_plan.mode
        in {SurfaceMode.EXISTING_RCSD_INTERSECTION, SurfaceMode.VIRTUAL_SURFACE}
    )


def evaluate_junction_results(
    items: Sequence[JunctionEvaluationItem],
    *,
    break_fraction_tolerance: float = 1e-3,
) -> JunctionSafetyReport:
    if break_fraction_tolerance < 0.0:
        raise ValueError("break_fraction_tolerance must be non-negative")
    overall = _MutableMetrics()
    by_case: dict[str, _MutableMetrics] = {}
    seen_junction_keys: set[str] = set()

    for item in items:
        if not item.case_key.strip():
            raise JunctionPredictionError("evaluation case_key is blank")
        if item.prediction.junction_key != item.materialized.junction_key:
            raise JunctionPredictionError("prediction/materialization identities differ")
        if item.prediction.junction_key in seen_junction_keys:
            raise JunctionPredictionError("evaluation contains duplicate Junction identity")
        seen_junction_keys.add(item.prediction.junction_key)
        item.gold.validate()

        case = by_case.setdefault(item.case_key, _MutableMetrics())
        targets = (overall, case)
        for metrics in targets:
            metrics.total += 1
            metrics.known_truth += int(item.gold.truth_known)
            metrics.abnormal_expected += int(item.gold.expected_abnormal_or_abstain)

        automatic = _is_automatic_accept(item)
        automatic_exact = False
        if automatic:
            actual = CompleteResultSignature.from_prediction(item.prediction)
            automatic_exact = item.gold.truth_known and any(
                actual.equivalent_to(
                    expected,
                    break_fraction_tolerance=break_fraction_tolerance,
                )
                for expected in item.gold.acceptable_automatic_results
            )
            for metrics in targets:
                metrics.automatic_accepted += 1
                metrics.automatic_exact += int(automatic_exact)
                metrics.dangerous_automatic += int(
                    item.gold.truth_known and not automatic_exact
                )
                metrics.unknown_automatic += int(not item.gold.truth_known)
                metrics.final_exact += int(automatic_exact)
        else:
            fallback_exact = (
                item.gold.truth_known
                and item.fallback_graph_signature is not None
                and item.fallback_graph_signature
                in item.gold.acceptable_fallback_graph_signatures
            )
            for metrics in targets:
                metrics.fallback_count += 1
                metrics.fallback_exact += int(fallback_exact)
                metrics.final_exact += int(fallback_exact)

        abnormal_detected = item.gold.expected_abnormal_or_abstain and not automatic
        for metrics in targets:
            metrics.abnormal_detected += int(abnormal_detected)

    case_metrics = tuple(
        by_case[case_key].freeze(case_key)
        for case_key in sorted(by_case)
    )
    return JunctionSafetyReport(
        **asdict(overall),
        release_enabled=(
            overall.dangerous_automatic == 0
            and overall.unknown_automatic == 0
        ),
        case_metrics=case_metrics,
    )
