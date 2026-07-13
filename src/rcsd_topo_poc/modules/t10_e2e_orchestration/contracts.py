from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


T10_MODULE_ID = "t10_e2e_orchestration"
T10_VERSION = "v1"

T10_V1_CHAIN = (
    "t01_data_preprocess",
    "t07_semantic_junction_anchor",
    "t03_virtual_junction_anchor",
    "t04_divmerge_virtual_polygon",
    "t05_junction_surface_fusion",
    "t06_segment_fusion_precheck",
    "t11_manual_relation_review",
    "t09_swsd_field_rule_restoration",
)

T10_T08_POLICY = (
    "T08 remains an independent pre-processing and quality repair module. "
    "T10 v1 consumes prepared external inputs but does not invoke T08."
)


@dataclass(frozen=True)
class ArtifactRequirement:
    slot: str
    owner: str
    description: str
    external: bool = False
    required: bool = True
    file_required: bool = True


@dataclass(frozen=True)
class WorkflowStepSpec:
    step_id: str
    module_id: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    notes: str = ""


EXTERNAL_INPUT_REQUIREMENTS: tuple[ArtifactRequirement, ...] = (
    ArtifactRequirement("prepared_swsd_nodes", "external", "SWSD nodes after independent T08/prepared-data quality gate.", True),
    ArtifactRequirement("prepared_swsd_roads", "external", "SWSD roads after independent T08/prepared-data quality gate.", True),
    ArtifactRequirement("drivezone", "external", "DriveZone polygon input shared by T07/T03/T04.", True),
    ArtifactRequirement("divstripzone", "external", "DivStripZone polygon input for T04.", True),
    ArtifactRequirement("rcsd_intersection", "external", "RCSDIntersection input for T07/T05 and case evidence.", True),
    ArtifactRequirement("rcsdroad", "external", "Original RCSDRoad input.", True),
    ArtifactRequirement("rcsdnode", "external", "Original RCSDNode input.", True),
    ArtifactRequirement("sw_restriction_tool7", "external", "T08 Tool7 explicit SWSD restriction output for T09.", True),
    ArtifactRequirement("sw_arrow_tool8", "external", "T08 Tool8 explicit SWSD lane-arrow output for T09.", True),
)

HANDOFF_REQUIREMENTS: tuple[ArtifactRequirement, ...] = (
    ArtifactRequirement("t01_segment", "t01_data_preprocess", "T01 segment.gpkg."),
    ArtifactRequirement("t01_nodes", "t01_data_preprocess", "T01 final nodes.gpkg or downstream working nodes."),
    ArtifactRequirement("t01_roads", "t01_data_preprocess", "T01 final roads.gpkg or downstream working roads."),
    ArtifactRequirement("t07_nodes", "t07_semantic_junction_anchor", "T07 Step2 nodes.gpkg for existing-surface anchors."),
    ArtifactRequirement("t07_relation_evidence", "t07_semantic_junction_anchor", "T07 relation evidence CSV/JSON."),
    ArtifactRequirement("t07_surface", "t07_semantic_junction_anchor", "T07 RCSDIntersection anchor surface GPKG."),
    ArtifactRequirement("t03_nodes", "t03_virtual_junction_anchor", "T03 downstream nodes.gpkg after virtual junction anchors."),
    ArtifactRequirement("t03_surface", "t03_virtual_junction_anchor", "T03 virtual_intersection_polygons.gpkg."),
    ArtifactRequirement("t03_relation_evidence", "t03_virtual_junction_anchor", "T03 relation evidence CSV/JSON."),
    ArtifactRequirement("t03_intersection_match", "t03_virtual_junction_anchor", "T03 intersection_match_t03.geojson."),
    ArtifactRequirement("t04_nodes", "t04_divmerge_virtual_polygon", "T04 downstream nodes.gpkg after divmerge anchors."),
    ArtifactRequirement("final_swsd_nodes", "t04_divmerge_virtual_polygon", "Final SWSD nodes.gpkg consumed by T05/T06/T11/T09."),
    ArtifactRequirement("t04_surface", "t04_divmerge_virtual_polygon", "T04 divmerge_virtual_anchor_surface.gpkg."),
    ArtifactRequirement("t04_relation_evidence", "t04_divmerge_virtual_polygon", "T04 relation evidence CSV/JSON."),
    ArtifactRequirement("t04_intersection_match", "t04_divmerge_virtual_polygon", "T04 intersection_match_t04.geojson."),
    ArtifactRequirement("t05_junction_surface", "t05_junction_surface_fusion", "T05 Phase1 junction_anchor_surface.gpkg."),
    ArtifactRequirement("t05_intersection_match_all", "t05_junction_surface_fusion", "T05 Phase2 intersection_match_all.geojson."),
    ArtifactRequirement("t05_rcsdroad_out", "t05_junction_surface_fusion", "T05 Phase2 rcsdroad_out.gpkg."),
    ArtifactRequirement("t05_rcsdnode_out", "t05_junction_surface_fusion", "T05 Phase2 rcsdnode_out.gpkg."),
    ArtifactRequirement("t06_frcsd_road", "t06_segment_fusion_precheck", "T06 Step3 F-RCSD Road output."),
    ArtifactRequirement("t06_frcsd_node", "t06_segment_fusion_precheck", "T06 Step3 F-RCSD Node output."),
    ArtifactRequirement(
        "t06_swsd_frcsd_segment_relation",
        "t06_segment_fusion_precheck",
        "T06 Step3 SWSD-to-FRCSD segment relation index.",
    ),
    ArtifactRequirement("t11_relation_repair_candidates", "t11_manual_relation_review", "T11 relation repair candidates CSV."),
    ArtifactRequirement("t11_relation_repair_summary", "t11_manual_relation_review", "T11 candidate extraction summary JSON."),
    ArtifactRequirement("t09_restored_field_rules", "t09_swsd_field_rule_restoration", "T09 restored field rules output."),
)

DIRECTORY_ONLY_HANDOFF_KEYS = frozenset(
    {
        "t03_dir",
        "t04_dir",
        "t05_dir",
        "t05_phase1_root",
        "t05_phase2_root",
        "t06_dir",
        "t07_dir",
        "t09_dir",
        "t11_dir",
    }
)

WORKFLOW_STEPS: tuple[WorkflowStepSpec, ...] = (
    WorkflowStepSpec(
        "t01",
        "t01_data_preprocess",
        consumes=("prepared_swsd_nodes", "prepared_swsd_roads"),
        produces=("t01_segment", "t01_nodes", "t01_roads"),
    ),
    WorkflowStepSpec(
        "t07",
        "t07_semantic_junction_anchor",
        consumes=("t01_nodes", "drivezone", "rcsd_intersection", "rcsdnode"),
        produces=("t07_nodes", "t07_relation_evidence", "t07_surface"),
    ),
    WorkflowStepSpec(
        "t03",
        "t03_virtual_junction_anchor",
        consumes=("t07_nodes", "prepared_swsd_roads", "drivezone", "rcsdroad", "rcsdnode"),
        produces=("t03_nodes", "t03_surface", "t03_relation_evidence", "t03_intersection_match"),
    ),
    WorkflowStepSpec(
        "t04",
        "t04_divmerge_virtual_polygon",
        consumes=("t03_nodes", "prepared_swsd_roads", "drivezone", "divstripzone", "rcsdroad", "rcsdnode"),
        produces=("t04_nodes", "final_swsd_nodes", "t04_surface", "t04_relation_evidence", "t04_intersection_match"),
    ),
    WorkflowStepSpec(
        "t05",
        "t05_junction_surface_fusion",
        consumes=(
            "rcsd_intersection",
            "t07_relation_evidence",
            "t03_surface",
            "t03_relation_evidence",
            "t04_surface",
            "t04_relation_evidence",
            "final_swsd_nodes",
            "rcsdroad",
            "rcsdnode",
        ),
        produces=("t05_junction_surface", "t05_intersection_match_all", "t05_rcsdroad_out", "t05_rcsdnode_out"),
        notes="T10 requires explicit T05 input/output files; directory-only module roots are rejected.",
    ),
    WorkflowStepSpec(
        "t06",
        "t06_segment_fusion_precheck",
        consumes=("t01_segment", "t01_roads", "final_swsd_nodes", "t05_intersection_match_all", "t05_rcsdroad_out", "t05_rcsdnode_out"),
        produces=("t06_frcsd_road", "t06_frcsd_node", "t06_swsd_frcsd_segment_relation"),
    ),
    WorkflowStepSpec(
        "t11",
        "t11_manual_relation_review",
        consumes=(
            "t01_segment",
            "t01_roads",
            "final_swsd_nodes",
            "t05_rcsdroad_out",
            "t05_rcsdnode_out",
            "t06_frcsd_road",
            "t06_frcsd_node",
            "t06_swsd_frcsd_segment_relation",
        ),
        produces=("t11_relation_repair_candidates", "t11_relation_repair_summary"),
        notes="T11 is audit-only. T09 remains a direct consumer of T06 business outputs.",
    ),
    WorkflowStepSpec(
        "t09",
        "t09_swsd_field_rule_restoration",
        consumes=(
            "final_swsd_nodes",
            "t06_frcsd_road",
            "t06_frcsd_node",
            "t06_swsd_frcsd_segment_relation",
            "sw_restriction_tool7",
            "sw_arrow_tool8",
        ),
        produces=("t09_restored_field_rules",),
        notes="Current T09 implementation/docs alignment is tracked as a T10 risk.",
    ),
)


def all_requirements() -> tuple[ArtifactRequirement, ...]:
    return EXTERNAL_INPUT_REQUIREMENTS + HANDOFF_REQUIREMENTS


def requirement_slots(requirements: Iterable[ArtifactRequirement]) -> tuple[str, ...]:
    return tuple(requirement.slot for requirement in requirements)


def requirement_by_slot(slot: str) -> ArtifactRequirement | None:
    for requirement in all_requirements():
        if requirement.slot == slot:
            return requirement
    return None
