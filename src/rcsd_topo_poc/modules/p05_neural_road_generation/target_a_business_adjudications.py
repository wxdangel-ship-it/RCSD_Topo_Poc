from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserAnchorAdjudication:
    case_key: str
    segment_id: str
    anchor_id: str
    business_status: str
    acceptable_candidate_ids: tuple[str, ...]
    status_supervised: bool
    sample_weight: float
    release_decision: str | None
    fallback_scope: str | None
    reality_change_clue: bool | None
    reason: str


@dataclass(frozen=True)
class UserRoadRoleAdjudication:
    case_key: str
    segment_id: str
    road_roles: tuple[tuple[str, str], ...]
    sample_weight: float
    reason: str


@dataclass(frozen=True)
class UserRoadMembershipAdjudication:
    case_key: str
    segment_id: str
    road_memberships: tuple[tuple[str, str], ...]
    sample_weight: float
    reason: str


_USER_ANCHOR_ADJUDICATIONS = {
    (
        "T10:605415675",
        "1633165",
    ): UserAnchorAdjudication(
        case_key="T10:605415675",
        segment_id="1633165_512279283",
        anchor_id="1633165",
        business_status="SUCCESS",
        acceptable_candidate_ids=(
            "ROAD:5391329551450177|5391329551450189|"
            "5391329551450260|5391329551450265|"
            "5391330021350944|5391330021350949",
        ),
        status_supervised=True,
        sample_weight=1.0,
        release_decision=None,
        fallback_scope=None,
        reality_change_clue=None,
        reason="user_confirmed_road_only_split_single_solution_20260731",
    ),
    (
        "T10-Error:501386978_504378551",
        "621989990",
    ): UserAnchorAdjudication(
        case_key="T10-Error:501386978_504378551",
        segment_id="501386978_504378551",
        anchor_id="621989990",
        business_status="SUCCESS",
        acceptable_candidate_ids=(),
        status_supervised=True,
        sample_weight=1.0,
        release_decision="ABSTAIN",
        fallback_scope="SEGMENT",
        reality_change_clue=False,
        reason=(
            "user_visual_audit_anchorable_current_t03_strategy_failed_"
            "exact_rcsd_target_unspecified"
        ),
    ),
}

_USER_ROAD_ROLE_ADJUDICATIONS = {
    (
        "T10:706247",
        "708001_708003",
    ): UserRoadRoleAdjudication(
        case_key="T10:706247",
        segment_id="708001_708003",
        road_roles=(
            ("5391352334583582", "MAIN"),
            ("5391352334583612", "INTERNAL_CONNECTOR"),
            ("5391352334583619", "MAIN"),
        ),
        sample_weight=1.0,
        reason="user_phase1_manual_road_role_adjudication_20260729",
    ),
}

_USER_ROAD_MEMBERSHIP_ADJUDICATIONS = {
    (
        "T10:706247",
        "706285_706290",
    ): UserRoadMembershipAdjudication(
        case_key="T10:706247",
        segment_id="706285_706290",
        road_memberships=(
            ("5395379941867683", "OWNER_CURRENT_SEGMENT"),
        ),
        sample_weight=1.0,
        reason="user_phase1_manual_road_membership_adjudication_20260729",
    ),
}


def user_anchor_adjudication(
    case_key: str,
    anchor_id: str,
) -> UserAnchorAdjudication | None:
    return _USER_ANCHOR_ADJUDICATIONS.get((str(case_key), str(anchor_id)))


def user_road_role_adjudication(
    case_key: str,
    segment_id: str,
) -> UserRoadRoleAdjudication | None:
    return _USER_ROAD_ROLE_ADJUDICATIONS.get(
        (str(case_key), str(segment_id))
    )


def user_road_membership_adjudication(
    case_key: str,
    segment_id: str,
) -> UserRoadMembershipAdjudication | None:
    return _USER_ROAD_MEMBERSHIP_ADJUDICATIONS.get(
        (str(case_key), str(segment_id))
    )


__all__ = [
    "UserAnchorAdjudication",
    "UserRoadMembershipAdjudication",
    "UserRoadRoleAdjudication",
    "user_anchor_adjudication",
    "user_road_membership_adjudication",
    "user_road_role_adjudication",
]
