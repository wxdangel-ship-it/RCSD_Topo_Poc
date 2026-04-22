from __future__ import annotations

from ._runtime_step4_kernel_reference import *

def _resolve_multibranch_context(
    *,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    kind_2: int,
    local_roads: list[ParsedRoad],
    member_node_ids: set[str],
    drivezone_union,
    divstrip_constraint_geometry,
) -> dict[str, Any]:
    road_to_branch: dict[str, Any] = {}
    for branch in road_branches:
        for road_id in branch.road_ids:
            road_to_branch[road_id] = branch

    divstrip_geometry = None if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty else divstrip_constraint_geometry
    divstrip_probe_geometry = (
        None
        if divstrip_geometry is None
        else divstrip_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2)
    )
    candidate_items: list[dict[str, Any]] = []
    for road in local_roads:
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if candidate is None:
            continue
        source_branch = road_to_branch.get(road.road_id)
        candidate_items.append(
            {
                "item_id": road.road_id,
                "source_branch_id": None if source_branch is None else source_branch.branch_id,
                "branch": source_branch,
                "angle_deg": float(candidate["angle_deg"]),
                "road_support_m": float(candidate["road_support_m"]),
                "has_incoming_support": bool(candidate["has_incoming_support"]),
                "has_outgoing_support": bool(candidate["has_outgoing_support"]),
                "divstrip_hit": bool(divstrip_probe_geometry is not None and road.geometry.intersects(divstrip_probe_geometry)),
                "divstrip_distance_m": (
                    math.inf
                    if divstrip_probe_geometry is None
                    else float(road.geometry.distance(divstrip_probe_geometry))
                ),
                "divstrip_overlap_m": (
                    0.0
                    if divstrip_probe_geometry is None
                    else float(road.geometry.intersection(divstrip_probe_geometry).length)
                ),
            }
        )

    best_main_pair_ids: tuple[str, str] | None = None
    best_main_pair_key: tuple[int, float, float] | None = None
    for first_item, second_item in combinations(candidate_items, 2):
        angle_gap = _branch_angle_gap_deg(first_item, second_item)
        if angle_gap < 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG:
            continue
        if not (first_item["has_incoming_support"] or second_item["has_incoming_support"]):
            continue
        if not (first_item["has_outgoing_support"] or second_item["has_outgoing_support"]):
            continue
        pair_key = (
            int(first_item["source_branch_id"] in main_branch_ids) + int(second_item["source_branch_id"] in main_branch_ids),
            -abs(180.0 - angle_gap),
            float(first_item["road_support_m"] + second_item["road_support_m"]),
        )
        if best_main_pair_key is None or pair_key > best_main_pair_key:
            best_main_pair_key = pair_key
            best_main_pair_ids = (str(first_item["item_id"]), str(second_item["item_id"]))

    main_pair_ids = set(best_main_pair_ids or ())
    candidate_items = [item for item in candidate_items if item["item_id"] not in main_pair_ids]
    multibranch_enabled = len({item["source_branch_id"] for item in candidate_items if item["source_branch_id"] is not None}) >= 2
    if not multibranch_enabled:
        return {
            "enabled": False,
            "n": len(candidate_items),
            "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
            "event_candidate_count": 0,
            "event_candidates": [],
            "selected_event_index": None,
            "selected_event_branch_ids": [],
            "selected_event_source_branch_ids": [],
            "selected_side_branches": [],
            "branches_used_count": 0,
            "ambiguous": False,
        }

    event_candidates: list[dict[str, Any]] = []
    for pair in combinations(candidate_items, 2):
        if pair[0]["source_branch_id"] == pair[1]["source_branch_id"]:
            continue
        pair_ids = sorted(str(item["item_id"]) for item in pair)
        pair_branches = [item["branch"] for item in pair if item["branch"] is not None]
        if len(pair_branches) != 2:
            continue
        preferred_hits = len({str(item["source_branch_id"]) for item in pair if item["source_branch_id"] is not None} & preferred_branch_ids)
        adjacency_gap = _branch_angle_gap_deg(pair[0], pair[1])
        divstrip_hit_count = sum(1 for item in pair if item["divstrip_hit"])
        divstrip_overlap_m = float(sum(item["divstrip_overlap_m"] for item in pair))
        divstrip_distance_m = float(min(item["divstrip_distance_m"] for item in pair))
        directional_hits = (
            sum(1 for item in pair if item["has_incoming_support"])
            if kind_2 == 8
            else sum(1 for item in pair if item["has_outgoing_support"])
        )
        score = (
            float(sum(item["road_support_m"] for item in pair))
            + preferred_hits * 100.0
            + divstrip_hit_count * 50.0
            + divstrip_overlap_m * 5.0
            + directional_hits * 25.0
            - adjacency_gap * 0.1
            - divstrip_distance_m * 0.25
        )
        event_candidates.append(
            {
                "road_ids": pair_ids,
                "branches": pair_branches,
                "source_branch_ids": sorted({branch.branch_id for branch in pair_branches}),
                "score": score,
                "preferred_hits": preferred_hits,
                "divstrip_hit_count": divstrip_hit_count,
                "divstrip_overlap_m": divstrip_overlap_m,
                "divstrip_distance_m": divstrip_distance_m,
                "directional_hits": directional_hits,
                "adjacency_gap": adjacency_gap,
            }
        )

    event_candidates.sort(
        key=lambda candidate: (
            candidate["preferred_hits"],
            candidate["divstrip_hit_count"],
            candidate["divstrip_overlap_m"],
            candidate["directional_hits"],
            candidate["score"],
            -candidate["divstrip_distance_m"],
            -candidate["adjacency_gap"],
        ),
        reverse=True,
    )
    top_candidate = event_candidates[0] if event_candidates else None
    if (
        len(event_candidates) == 1
        and top_candidate is not None
        and float(top_candidate["adjacency_gap"]) >= 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG
        and int(top_candidate["preferred_hits"]) <= 1
    ):
        return {
            "enabled": False,
            "n": len(candidate_items),
            "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
            "event_candidate_count": len(event_candidates),
            "event_candidates": [],
            "selected_event_index": None,
            "selected_event_branch_ids": [],
            "selected_event_source_branch_ids": [],
            "selected_side_branches": [],
            "branches_used_count": 0,
            "ambiguous": False,
        }
    ambiguous = False
    if len(event_candidates) > 1 and top_candidate is not None:
        second_candidate = event_candidates[1]
        ambiguous = (
            abs(float(top_candidate["score"]) - float(second_candidate["score"])) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and top_candidate["divstrip_hit_count"] == second_candidate["divstrip_hit_count"]
            and abs(float(top_candidate["divstrip_overlap_m"]) - float(second_candidate["divstrip_overlap_m"])) <= 1.0
            and top_candidate["directional_hits"] == second_candidate["directional_hits"]
            and {branch.branch_id for branch in top_candidate["branches"]} != {branch.branch_id for branch in second_candidate["branches"]}
            and top_candidate["road_ids"] != second_candidate["road_ids"]
        )
    return {
        "enabled": True,
        "n": len(candidate_items),
        "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
        "event_candidate_count": len(event_candidates),
        "event_candidates": [
            {
                "road_ids": list(candidate["road_ids"]),
                "source_branch_ids": list(candidate["source_branch_ids"]),
                "score": float(candidate["score"]),
                "preferred_hits": int(candidate["preferred_hits"]),
                "divstrip_hit_count": int(candidate["divstrip_hit_count"]),
                "divstrip_overlap_m": float(candidate["divstrip_overlap_m"]),
                "divstrip_distance_m": float(candidate["divstrip_distance_m"]),
                "directional_hits": int(candidate["directional_hits"]),
                "adjacency_gap": float(candidate["adjacency_gap"]),
            }
            for candidate in event_candidates
        ],
        "selected_event_index": 0 if top_candidate is not None else None,
        "selected_event_branch_ids": [] if top_candidate is None else list(top_candidate["road_ids"]),
        "selected_event_source_branch_ids": (
            []
            if top_candidate is None
            else list(top_candidate["source_branch_ids"])
        ),
        "selected_side_branches": [] if top_candidate is None else list(top_candidate["branches"]),
        "branches_used_count": 0 if top_candidate is None else len({branch.branch_id for branch in top_candidate["branches"]}),
        "ambiguous": ambiguous,
    }


def _is_stage4_representative(node: ParsedNode) -> bool:
    representative_id = node.mainnodeid or node.node_id
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and _is_stage4_supported_node_kind(node)
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _stage4_chain_kind_2(node: ParsedNode) -> int | None:
    source_kind_2 = _node_source_kind_2(node)
    if source_kind_2 in STAGE4_KIND_2_VALUES or source_kind_2 == COMPLEX_JUNCTION_KIND:
        return source_kind_2
    if _node_source_kind(node) == COMPLEX_JUNCTION_KIND:
        return COMPLEX_JUNCTION_KIND
    return None


def _infer_operational_kind_2_from_divstrip_event(
    *,
    representative_node: ParsedNode,
    road_branches,
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
) -> dict[str, Any] | None:
    divstrip_constraint_geometry = divstrip_context["constraint_geometry"]
    if (
        divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
        or not divstrip_context["nearby"]
        or divstrip_context["ambiguous"]
    ):
        return None

    event_reference_point = divstrip_constraint_geometry.centroid
    road_lookup = {road.road_id: road for road in local_roads}
    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    for branch in road_branches:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=representative_node.geometry,
        )
        if centerline is None or centerline.is_empty:
            continue
        representative_dist = float(centerline.project(representative_node.geometry))
        event_dist = float(centerline.project(event_reference_point))
        branch_support = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            post_event_m = float(representative_dist - event_dist)
            if post_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                merge_hits += 1
                merge_score += branch_support + min(post_event_m, 40.0)
        if branch.has_outgoing_support:
            pre_event_m = float(event_dist - representative_dist)
            if pre_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                diverge_hits += 1
                diverge_score += branch_support + min(pre_event_m, 40.0)

    if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]:
        if diverge_score > 0.0:
            diverge_score += 25.0
        if merge_score > 0.0:
            merge_score += 25.0

    if merge_score <= 0.0 and diverge_score <= 0.0:
        return None

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    else:
        operational_kind_2 = 16

    ambiguous = (
        abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
        and merge_hits == diverge_hits
    )
    return {
        "operational_kind_2": operational_kind_2,
        "ambiguous": ambiguous,
        "kind_resolution_mode": (
            "continuous_chain_divstrip_event"
            if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]
            else "divstrip_event_position"
        ),
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _resolve_operational_kind_2(
    *,
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
    multibranch_context: dict[str, Any],
) -> dict[str, Any]:
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    if source_kind_2 in STAGE4_KIND_2_VALUES:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": int(source_kind_2),
            "complex_junction": False,
            "ambiguous": False,
            "kind_resolution_mode": "direct_kind_2",
            "merge_score": None,
            "diverge_score": None,
            "merge_hits": None,
            "diverge_hits": None,
        }
    divstrip_kind_resolution = None
    if len(road_branches) <= 2 or source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND:
        divstrip_kind_resolution = _infer_operational_kind_2_from_divstrip_event(
            representative_node=representative_node,
            road_branches=road_branches,
            local_roads=local_roads,
            divstrip_context=divstrip_context,
            chain_context=chain_context,
        )
    if divstrip_kind_resolution is not None and not divstrip_kind_resolution["ambiguous"]:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": divstrip_kind_resolution["operational_kind_2"],
            "complex_junction": source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND,
            "ambiguous": False,
            "kind_resolution_mode": divstrip_kind_resolution["kind_resolution_mode"],
            "merge_score": divstrip_kind_resolution["merge_score"],
            "diverge_score": divstrip_kind_resolution["diverge_score"],
            "merge_hits": divstrip_kind_resolution["merge_hits"],
            "diverge_hits": divstrip_kind_resolution["diverge_hits"],
        }
    if source_kind != COMPLEX_JUNCTION_KIND and source_kind_2 != COMPLEX_JUNCTION_KIND:
        raise Stage4RunError(
            REASON_MAINNODEID_OUT_OF_SCOPE,
            (
                f"mainnodeid='{normalize_id(representative_node.mainnodeid or representative_node.node_id)}' "
                f"has unsupported kind={source_kind}, kind_2={source_kind_2}."
            ),
        )

    side_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    preferred_complex_branches = [
        branch
        for branch in road_branches
        if branch.branch_id in preferred_branch_ids
    ]
    if not side_branches and len(preferred_complex_branches) == 1:
        preferred_branch = preferred_complex_branches[0]
        if preferred_branch.has_incoming_support and not preferred_branch.has_outgoing_support:
            return {
                "source_kind": source_kind,
                "source_kind_2": source_kind_2,
                "operational_kind_2": 8,
                "complex_junction": True,
                "ambiguous": False,
                "kind_resolution_mode": "complex_divstrip_preferred_branch",
                "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
                "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
                "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
                "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
            }
        if preferred_branch.has_outgoing_support and not preferred_branch.has_incoming_support:
            return {
                "source_kind": source_kind,
                "source_kind_2": source_kind_2,
                "operational_kind_2": 16,
                "complex_junction": True,
                "ambiguous": False,
                "kind_resolution_mode": "complex_divstrip_preferred_branch",
                "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
                "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
                "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
                "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
            }
    if (
        not side_branches
        and multibranch_context.get("enabled", False)
        and multibranch_context.get("selected_event_index") is not None
        and not multibranch_context.get("ambiguous", False)
    ):
        fallback_kind_2 = 16
        if divstrip_kind_resolution is not None:
            fallback_kind_2 = int(divstrip_kind_resolution["operational_kind_2"])
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": fallback_kind_2,
            "complex_junction": True,
            "ambiguous": False,
            "kind_resolution_mode": "complex_multibranch_event",
            "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
            "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
            "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
            "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
        }

    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    merge_preferred_hits = 0
    diverge_preferred_hits = 0
    for branch in side_branches:
        branch_score = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            merge_hits += 1
            merge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                merge_preferred_hits += 1
                merge_score += 100.0
        if branch.has_outgoing_support:
            diverge_hits += 1
            diverge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                diverge_preferred_hits += 1
                diverge_score += 100.0

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    elif merge_preferred_hits > diverge_preferred_hits:
        operational_kind_2 = 8
    else:
        operational_kind_2 = 16

    ambiguous = (
        not side_branches
        or (
            abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and merge_hits == diverge_hits
            and merge_preferred_hits == diverge_preferred_hits
        )
    )
    return {
        "source_kind": source_kind,
        "source_kind_2": source_kind_2,
        "operational_kind_2": operational_kind_2,
        "complex_junction": True,
        "ambiguous": ambiguous,
        "kind_resolution_mode": "complex_branch_direction",
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _build_continuous_chain_context(
    *,
    representative_node: ParsedNode,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    enabled: bool = True,
) -> dict[str, Any]:
    representative_mainnodeid = normalize_id(representative_node.mainnodeid or representative_node.node_id)
    if not enabled:
        return {
            "chain_component_id": representative_mainnodeid,
            "related_mainnodeids": [],
            "is_in_continuous_chain": False,
            "chain_node_count": 1,
            "chain_node_offset_m": None,
            "sequential_ok": False,
            "related_seed_nodes": [],
        }

    chain_candidates, chain_trace = _chain_candidates_from_topology(
        representative_node_id=representative_node.node_id,
        representative_chain_kind_2=_stage4_chain_kind_2(representative_node),
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=CHAIN_CONTEXT_EVENT_SPAN_M,
    )

    chain_candidates.sort(key=lambda item: item[1])
    related_mainnodeids = [normalize_id(candidate.mainnodeid or candidate.node_id) for candidate, _ in chain_candidates]
    nearest_offset_m = None if not chain_candidates else round(abs(chain_candidates[0][1]), 3)
    sequential_ok = any(
        abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M
        for _, offset_m in chain_candidates
    )
    related_directions = [1 if offset_m >= 0.0 else -1 for _, offset_m in chain_candidates]
    has_forward_chain = any(sign > 0 for sign in related_directions)
    has_backward_chain = any(sign < 0 for sign in related_directions)
    chain_node_ids = [normalize_id(candidate.node_id) for candidate, _ in chain_candidates]
    chain_member_ids = [representative_mainnodeid, *related_mainnodeids]
    return {
        "chain_component_id": "__".join(sorted(chain_member_ids)) if len(chain_member_ids) > 1 else representative_mainnodeid,
        "related_mainnodeids": related_mainnodeids,
        "is_in_continuous_chain": bool(chain_candidates),
        "chain_node_count": 1 + len(chain_candidates),
        "chain_node_offset_m": nearest_offset_m,
        "sequential_ok": sequential_ok,
        "chain_bidirectional": has_forward_chain and has_backward_chain,
        "chain_node_ids": chain_node_ids,
        "chain_node_trace": chain_trace,
        "related_seed_nodes": [candidate for candidate, offset_m in chain_candidates if abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M],
    }


def _build_stage4_interpretation_review_signals(
    *,
    divstrip_context: dict[str, Any],
    multibranch_context: dict[str, Any],
    kind_resolution: dict[str, Any],
    chain_context: dict[str, Any],
) -> tuple[str, ...]:
    review_signals: list[str] = []
    if bool(multibranch_context.get("ambiguous", False)):
        review_signals.append(STATUS_MULTIBRANCH_EVENT_AMBIGUOUS)
    if bool(divstrip_context.get("ambiguous", False)):
        review_signals.append(STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS)
    if (
        bool(chain_context.get("is_in_continuous_chain", False))
        and bool(chain_context.get("sequential_ok", False))
        and not bool(kind_resolution.get("complex_junction", False))
        and bool(chain_context.get("chain_bidirectional", False))
    ):
        review_signals.append(STATUS_CONTINUOUS_CHAIN_REVIEW)
    if bool(kind_resolution.get("ambiguous", False)):
        review_signals.append(STATUS_COMPLEX_KIND_AMBIGUOUS)
    return tuple(review_signals)


def _build_stage4_interpretation_risk_signals(
    *,
    review_signals: tuple[str, ...],
    reverse_tip_used: bool,
    fallback_mode: str | None,
) -> tuple[str, ...]:
    risk_signals = list(review_signals)
    if reverse_tip_used:
        risk_signals.append("reverse_tip_used")
    if fallback_mode is not None:
        risk_signals.append("fallback_to_weak_evidence")
    return tuple(risk_signals)


def _evaluate_stage4_legacy_step5_readiness(
    *,
    selected_branch_ids: Sequence[str],
    event_reference: Mapping[str, Any],
) -> Stage4LegacyStep5Readiness:
    reasons: list[str] = []
    if not selected_branch_ids:
        reasons.append("selected_branch_ids_empty")
    if event_reference.get("origin_point") is None:
        reasons.append("missing_event_origin")
    return Stage4LegacyStep5Readiness(
        ready=not reasons,
        reasons=tuple(reasons),
    )


def _build_stage4_event_interpretation(
    *,
    representative_node: ParsedNode,
    representative_source_kind_2: int | None,
    mainnodeid_norm: str,
    seed_union,
    group_nodes: Sequence[ParsedNode],
    patch_size_m: float,
    seed_center,
    drivezone_union,
    local_roads: list[ParsedRoad],
    local_rcsd_roads: list[ParsedRoad],
    local_rcsd_nodes: list[ParsedNode],
    local_divstrip_features: list[LoadedFeature],
    road_branches: list[Any],
    main_branch_ids: set[str],
    member_node_ids: set[str],
    event_branch_ids: set[str] | None = None,
    boundary_branch_ids: Sequence[str] | None = None,
    preferred_axis_branch_id: str | None = None,
    context_augmented_node_ids: set[str] | None = None,
    degraded_scope_reason: str | None = None,
    direct_target_rc_nodes: list[ParsedNode],
    exact_target_rc_nodes: list[ParsedNode],
    primary_main_rc_node: ParsedNode | None,
    rcsdnode_seed_mode: str,
    chain_context: dict[str, Any],
    excluded_component_geometries: list[Any] | None = None,
    excluded_axis_positions: list[tuple[str, float]] | None = None,
) -> Stage4EventInterpretationResult:
    provisional_multibranch_kind_2 = (
        int(representative_source_kind_2)
        if representative_source_kind_2 in STAGE4_KIND_2_VALUES
        else 16
    )
    explicit_event_branch_ids = {
        str(branch_id)
        for branch_id in (event_branch_ids or set())
        if branch_id is not None
    }
    explicit_boundary_branch_ids = tuple(
        str(branch_id)
        for branch_id in (boundary_branch_ids or ())
        if branch_id is not None
    )
    divstrip_context_raw = _analyze_divstrip_context(
        local_divstrip_features=local_divstrip_features,
        seed_union=seed_union,
        road_branches=road_branches,
        local_roads=local_roads,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=explicit_event_branch_ids or None,
        allow_compound_pair_merge=_is_complex_stage4_node(representative_node) or len(group_nodes) > 1,
        excluded_component_geometries=excluded_component_geometries,
    )
    preferred_branch_ids = set(divstrip_context_raw["preferred_branch_ids"]) | explicit_event_branch_ids
    multibranch_context_raw = _resolve_multibranch_context(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        preferred_branch_ids=preferred_branch_ids,
        kind_2=provisional_multibranch_kind_2,
        local_roads=local_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
        divstrip_constraint_geometry=divstrip_context_raw["constraint_geometry"],
    )
    kind_resolution_raw = _resolve_operational_kind_2(
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        preferred_branch_ids=preferred_branch_ids,
        local_roads=local_roads,
        divstrip_context=divstrip_context_raw,
        chain_context=chain_context,
        multibranch_context=multibranch_context_raw,
    )
    operational_kind_2 = kind_resolution_raw["operational_kind_2"]
    if operational_kind_2 != provisional_multibranch_kind_2:
        multibranch_context_raw = _resolve_multibranch_context(
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            preferred_branch_ids=preferred_branch_ids,
            kind_2=operational_kind_2,
            local_roads=local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=divstrip_context_raw["constraint_geometry"],
        )
    forward_side_branches = _select_stage4_side_branches(
        road_branches,
        kind_2=operational_kind_2,
        preferred_branch_ids=preferred_branch_ids,
    )
    position_source_forward = divstrip_context_raw["selection_mode"]
    reverse_trigger: str | None = None
    reverse_tip_attempted = False
    reverse_tip_used = False
    position_source_reverse: str | None = None
    reverse_side_branches: list[Any] = []
    if explicit_event_branch_ids:
        selected_side_branches = [
            branch for branch in road_branches if str(branch.branch_id) in explicit_event_branch_ids
        ]
    else:
        selected_side_branches = (
            list(multibranch_context_raw["selected_side_branches"])
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_side_branches"]
            else list(forward_side_branches)
        )

    selected_event_branch_ids = (
        sorted(explicit_event_branch_ids)
        if explicit_event_branch_ids
        else (
            multibranch_context_raw["selected_event_branch_ids"]
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_event_branch_ids"]
            else sorted(branch.branch_id for branch in selected_side_branches)
        )
    )
    refined_divstrip_context_raw = _analyze_divstrip_context(
        local_divstrip_features=local_divstrip_features,
        seed_union=seed_union,
        road_branches=road_branches,
        local_roads=local_roads,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=set(selected_event_branch_ids),
        allow_compound_pair_merge=kind_resolution_raw["complex_junction"] or len(group_nodes) > 1,
        excluded_component_geometries=excluded_component_geometries,
    )
    if (
        refined_divstrip_context_raw["nearby"]
        or refined_divstrip_context_raw["ambiguous"]
        or refined_divstrip_context_raw["selected_component_ids"]
    ):
        divstrip_context_raw = refined_divstrip_context_raw
        preferred_branch_ids = set(divstrip_context_raw["preferred_branch_ids"]) | explicit_event_branch_ids
    position_source_forward = divstrip_context_raw["selection_mode"]
    position_source_final = (
        position_source_reverse
        if reverse_tip_used and position_source_reverse is not None
        else ("multibranch_event" if multibranch_context_raw["enabled"] else position_source_forward)
    )
    selected_branch_ids = (
        list(explicit_boundary_branch_ids)
        if explicit_boundary_branch_ids
        else (
            sorted(multibranch_context_raw["selected_event_source_branch_ids"])
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_event_source_branch_ids"]
            else sorted(main_branch_ids | {branch.branch_id for branch in selected_side_branches})
        )
    )
    selected_road_ids = sorted(
        {
            road_id
            for branch in road_branches
            if branch.branch_id in selected_branch_ids
            for road_id in branch.road_ids
        }
    )
    selected_event_road_ids = {
        road_id
        for branch in road_branches
        if branch.branch_id in set(selected_event_branch_ids)
        for road_id in branch.road_ids
    }
    selected_rcsdroad_ids: set[str] = set()
    _, _, rc_branches = _build_stage4_road_branches_for_member_nodes(
        local_rcsd_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
        include_internal_roads=False,
        support_center=None,
    )
    for rc_branch in rc_branches:
        for road_branch in road_branches:
            if road_branch.branch_id not in selected_branch_ids:
                continue
            angle_gap = abs(road_branch.angle_deg - rc_branch.angle_deg)
            wrapped_angle_gap = min(angle_gap, 360.0 - angle_gap)
            if angle_gap <= 35.0 or wrapped_angle_gap <= 35.0:
                selected_rcsdroad_ids.update(rc_branch.road_ids)
                break
    rcsdroad_selection_mode = "angle_match"
    if not selected_rcsdroad_ids:
        nearby_rcsd_roads = [
            road
            for road in local_rcsd_roads
            if road.geometry.distance(seed_center) <= max(30.0, patch_size_m / 5.0)
        ]
        inside_nearby_rcsd_roads = [
            road
            for road in nearby_rcsd_roads
            if drivezone_union.buffer(0).covers(road.geometry)
        ]
        fallback_rcsd_roads = inside_nearby_rcsd_roads or nearby_rcsd_roads
        selected_rcsdroad_ids = {road.road_id for road in fallback_rcsd_roads}
        rcsdroad_selection_mode = (
            "fallback_nearby_inside_only"
            if inside_nearby_rcsd_roads
            else "fallback_nearby_any"
        )

    selected_roads = [road for road in local_roads if road.road_id in selected_road_ids]
    selected_event_roads = [road for road in local_roads if road.road_id in selected_event_road_ids]
    selected_rcsd_roads = [road for road in local_rcsd_roads if road.road_id in selected_rcsdroad_ids]
    complex_local_support_roads: list[ParsedRoad] = []
    if kind_resolution_raw["complex_junction"] or len(group_nodes) > 1:
        complex_support_seed_union = unary_union(
            [
                *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
                *[
                    node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
                    for node in chain_context["related_seed_nodes"]
                ],
            ]
        )
        if complex_support_seed_union is not None and not complex_support_seed_union.is_empty:
            selected_road_id_set = set(selected_road_ids)
            complex_local_support_roads = [
                road
                for road in local_roads
                if road.road_id not in selected_road_id_set
                and road.geometry is not None
                and not road.geometry.is_empty
                and float(road.geometry.distance(complex_support_seed_union))
                <= EVENT_COMPLEX_LOCAL_SUPPORT_ROAD_DISTANCE_M
            ]
    selected_rcsd_buffer = unary_union(
        [
            road.geometry.buffer(max(1.5, RC_ROAD_BUFFER_M), cap_style=2, join_style=2)
            for road in selected_rcsd_roads
        ]
    )
    selected_rcsdnode_ids = {
        node.node_id
        for node in local_rcsd_nodes
        if node.mainnodeid == mainnodeid_norm
        or (
            selected_rcsd_roads
            and not selected_rcsd_buffer.is_empty
            and selected_rcsd_buffer.intersects(node.geometry)
        )
    }
    if primary_main_rc_node is None:
        inferred_rcsdnode_seed = _infer_primary_main_rc_node_from_local_context(
            local_rcsd_nodes=local_rcsd_nodes,
            selected_rcsd_roads=selected_rcsd_roads,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            kind_2=operational_kind_2,
        )
        if inferred_rcsdnode_seed["primary_main_rc_node"] is not None:
            primary_main_rc_node = inferred_rcsdnode_seed["primary_main_rc_node"]
            rcsdnode_seed_mode = inferred_rcsdnode_seed["seed_mode"]
    if primary_main_rc_node is not None:
        selected_rcsdnode_ids.add(primary_main_rc_node.node_id)
    if not selected_rcsdnode_ids:
        selected_rcsdnode_ids = {node.node_id for node in direct_target_rc_nodes}
    effective_target_rc_nodes: list[ParsedNode] = list(direct_target_rc_nodes)
    selected_rcsd_nodes = [node for node in local_rcsd_nodes if node.node_id in selected_rcsdnode_ids]
    if selected_rcsd_roads:
        _validate_drivezone_containment(
            drivezone_union=drivezone_union,
            features=selected_rcsd_roads,
            label="RCSDRoad",
        )
    if selected_rcsd_nodes:
        _validate_drivezone_containment(
            drivezone_union=drivezone_union,
            features=selected_rcsd_nodes,
            label="RCSDNode",
        )

    seed_support_geometries = [
        *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
        *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in exact_target_rc_nodes],
    ]
    if chain_context["sequential_ok"]:
        seed_support_geometries.extend(
            node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
            for node in chain_context["related_seed_nodes"]
        )
    divstrip_constraint_geometry = divstrip_context_raw["constraint_geometry"]
    event_anchor_geometry = divstrip_context_raw["event_anchor_geometry"]
    localized_divstrip_reference_geometry = _localize_divstrip_reference_geometry(
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        selected_roads=selected_roads,
        event_anchor_geometry=event_anchor_geometry,
        representative_node=representative_node,
        drivezone_union=drivezone_union,
    )
    event_axis_branch = _resolve_event_axis_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=operational_kind_2,
        preferred_axis_branch_id=preferred_axis_branch_id,
    )
    event_axis_branch_id = None if event_axis_branch is None else event_axis_branch.branch_id
    if (
        primary_main_rc_node is None
        and not direct_target_rc_nodes
        and event_axis_branch_id is not None
        and event_axis_branch_id not in selected_branch_ids
    ):
        inferred_rcsdnode_seed = _infer_primary_main_rc_node_from_local_context(
            local_rcsd_nodes=local_rcsd_nodes,
            selected_rcsd_roads=selected_rcsd_roads,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            kind_2=operational_kind_2,
            preferred_trunk_branch_id=event_axis_branch_id,
        )
        if inferred_rcsdnode_seed["primary_main_rc_node"] is not None:
            primary_main_rc_node = inferred_rcsdnode_seed["primary_main_rc_node"]
            rcsdnode_seed_mode = inferred_rcsdnode_seed["seed_mode"]
            selected_rcsdnode_ids.add(primary_main_rc_node.node_id)
            effective_target_rc_nodes = [primary_main_rc_node]
            if primary_main_rc_node.node_id not in {node.node_id for node in selected_rcsd_nodes}:
                _validate_drivezone_containment(
                    drivezone_union=drivezone_union,
                    features=[primary_main_rc_node],
                    label="RCSDNode",
                )
                selected_rcsd_nodes = [
                    node for node in local_rcsd_nodes if node.node_id in selected_rcsdnode_ids
                ]
    road_lookup = {road.road_id: road for road in local_roads}
    event_axis_centerline = (
        None
        if event_axis_branch is None
        else _resolve_branch_centerline(
            branch=event_axis_branch,
            road_lookup=road_lookup,
            reference_point=event_anchor_geometry.centroid
            if event_anchor_geometry is not None and not event_anchor_geometry.is_empty
            else representative_node.geometry,
        )
    )
    provisional_event_origin = (
        representative_node.geometry
        if event_axis_centerline is None or event_axis_centerline.is_empty
        else nearest_points(event_axis_centerline, representative_node.geometry)[0]
    )
    initial_event_axis_unit_vector = _resolve_event_axis_unit_vector(
        axis_centerline=event_axis_centerline,
        origin_point=provisional_event_origin,
    )
    cross_section_boundary_branch_ids = (
        set(explicit_boundary_branch_ids)
        if explicit_boundary_branch_ids
        else (
            set(main_branch_ids)
            if (
                kind_resolution_raw["complex_junction"]
                or multibranch_context_raw["enabled"]
                or len(divstrip_context_raw["selected_component_ids"]) > 1
            )
            else set(selected_branch_ids)
        )
    )
    boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
        road_branches=road_branches,
        selected_branch_ids=cross_section_boundary_branch_ids,
        kind_2=operational_kind_2,
    )
    if (
        not explicit_boundary_branch_ids
        and (boundary_branch_a is None or boundary_branch_b is None)
        and cross_section_boundary_branch_ids != set(selected_branch_ids)
    ):
        boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
            road_branches=road_branches,
            selected_branch_ids=set(selected_branch_ids),
            kind_2=operational_kind_2,
        )
    branch_a_centerline = (
        None
        if boundary_branch_a is None
        else _resolve_branch_centerline(
            branch=boundary_branch_a,
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
    )
    branch_b_centerline = (
        None
        if boundary_branch_b is None
        else _resolve_branch_centerline(
            branch=boundary_branch_b,
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
    )
    if (
        not explicit_boundary_branch_ids
        and (kind_resolution_raw["complex_junction"] or multibranch_context_raw["enabled"])
        and len(multibranch_context_raw.get("main_pair_item_ids", [])) >= 2
    ):
        main_pair_item_ids = [str(item_id) for item_id in multibranch_context_raw["main_pair_item_ids"][:2]]
        main_pair_branch_a_centerline = _resolve_centerline_from_road_ids(
            road_ids=[main_pair_item_ids[0]],
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
        main_pair_branch_b_centerline = _resolve_centerline_from_road_ids(
            road_ids=[main_pair_item_ids[1]],
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
        if (
            main_pair_branch_a_centerline is not None
            and not main_pair_branch_a_centerline.is_empty
            and main_pair_branch_b_centerline is not None
            and not main_pair_branch_b_centerline.is_empty
        ):
            branch_a_centerline = main_pair_branch_a_centerline
            branch_b_centerline = main_pair_branch_b_centerline
    event_cross_half_len_m = _resolve_event_cross_half_len(
        origin_point=provisional_event_origin,
        axis_centerline=event_axis_centerline,
        axis_unit_vector=initial_event_axis_unit_vector,
        event_anchor_geometry=event_anchor_geometry,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        selected_roads=selected_roads,
        selected_rcsd_roads=selected_rcsd_roads,
        patch_size_m=patch_size_m,
    )
    excluded_axis_s_values: list[float] = []
    if excluded_axis_positions and event_axis_branch_id is not None:
        target_axis_id = str(event_axis_branch_id)
        for prior_axis_id, prior_s in excluded_axis_positions:
            if str(prior_axis_id) == target_axis_id:
                excluded_axis_s_values.append(float(prior_s))
    event_reference_raw = _resolve_event_reference_point(
        representative_node=representative_node,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=localized_divstrip_reference_geometry,
        all_divstrip_geometry=unary_union(
            [feature.geometry for feature in local_divstrip_features if feature.geometry is not None and not feature.geometry.is_empty]
        ) if local_divstrip_features else GeometryCollection(),
        axis_centerline=event_axis_centerline,
        axis_unit_vector=initial_event_axis_unit_vector,
        kind_2=operational_kind_2,
        drivezone_union=drivezone_union,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        cross_half_len_m=event_cross_half_len_m,
        patch_size_m=patch_size_m,
        excluded_axis_s_values=excluded_axis_s_values or None,
    )
    branch_middle_gate_signal = str(event_reference_raw.get("branch_middle_gate_signal") or "").strip() or None
    branch_middle_gate_passed = bool(event_reference_raw.get("branch_middle_gate_passed", True))
    hard_rejection_signals: list[str] = []
    strict_branch_middle_enforcement = bool(
        explicit_event_branch_ids
        or explicit_boundary_branch_ids
        or preferred_axis_branch_id is not None
        or degraded_scope_reason is not None
        or excluded_component_geometries
        or excluded_axis_positions
    )
    if str(event_reference_raw.get("split_pick_source") or "").startswith("reverse_"):
        reverse_tip_attempted = True
        reverse_tip_used = True
        if reverse_trigger is None:
            reverse_trigger = (
                "forward_reference_outside_branch_middle"
                if branch_middle_gate_signal == "event_reference_outside_branch_middle"
                else "forward_reference_unstable"
            )
        position_source_reverse = str(event_reference_raw.get("position_source") or "reverse_tip_divstrip")
    elif branch_middle_gate_signal == "event_reference_outside_branch_middle":
        reverse_tip_attempted = True
        if reverse_trigger is None:
            reverse_trigger = "forward_reference_outside_branch_middle"
    if branch_middle_gate_signal is not None and not branch_middle_gate_passed:
        # Keep legacy T02 behavior unless the caller explicitly opts into
        # unit-local branch-middle enforcement via the new Step4 inputs.
        if (
            branch_middle_gate_signal != "event_reference_outside_branch_middle"
            or strict_branch_middle_enforcement
        ):
            hard_rejection_signals.append(branch_middle_gate_signal)
    position_source_final = (
        position_source_reverse
        if reverse_tip_used and position_source_reverse is not None
        else ("multibranch_event" if multibranch_context_raw["enabled"] else position_source_forward)
    )
    event_origin_point = event_reference_raw["origin_point"]
    event_origin_source = event_reference_raw["event_origin_source"]
    event_axis_unit_vector = _resolve_event_axis_unit_vector(
        axis_centerline=event_axis_centerline,
        origin_point=event_origin_point,
    ) or initial_event_axis_unit_vector
    event_recenter = _rebalance_event_origin_for_rcsd_targets(
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        target_rc_nodes=effective_target_rc_nodes,
    )
    if event_recenter[1]["applied"]:
        event_origin_point = event_recenter[0]
        event_origin_source = f"{event_origin_source}_recenter_{event_recenter[1]['direction']}"
        event_axis_unit_vector = _resolve_event_axis_unit_vector(
            axis_centerline=event_axis_centerline,
            origin_point=event_origin_point,
        ) or event_axis_unit_vector
    event_cross_half_len_m = _resolve_event_cross_half_len(
        origin_point=event_origin_point,
        axis_centerline=event_axis_centerline,
        axis_unit_vector=event_axis_unit_vector,
        event_anchor_geometry=event_anchor_geometry,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        selected_roads=selected_roads,
        selected_rcsd_roads=selected_rcsd_roads,
        patch_size_m=patch_size_m,
    )

    fallback_mode: str | None = None
    if not divstrip_context_raw["nearby"]:
        fallback_mode = "weak_evidence_no_nearby_divstrip"
    elif divstrip_context_raw["selection_mode"] == "roads_fallback":
        fallback_mode = "roads_fallback"
    elif isinstance(position_source_final, str) and "fallback" in position_source_final:
        fallback_mode = position_source_final
    evidence_primary_source = (
        "reverse_tip_retry"
        if reverse_tip_used
        else (
            "multibranch_event"
            if multibranch_context_raw["enabled"]
            else ("divstrip_direct" if divstrip_context_raw["nearby"] else "conservative_fallback")
        )
    )
    review_signals = _build_stage4_interpretation_review_signals(
        divstrip_context=divstrip_context_raw,
        multibranch_context=multibranch_context_raw,
        kind_resolution=kind_resolution_raw,
        chain_context=chain_context,
    )
    if (
        branch_middle_gate_signal is not None
        and (
            branch_middle_gate_signal != "event_reference_outside_branch_middle"
            or strict_branch_middle_enforcement
        )
    ):
        review_signals = tuple([*review_signals, branch_middle_gate_signal])
    if degraded_scope_reason:
        review_signals = tuple([*review_signals, f"degraded_scope:{degraded_scope_reason}"])
    risk_signals = _build_stage4_interpretation_risk_signals(
        review_signals=review_signals,
        reverse_tip_used=reverse_tip_used,
        fallback_mode=fallback_mode,
    )
    divstrip_context = wrap_stage4_divstrip_context(divstrip_context_raw)
    multibranch_decision = wrap_stage4_multibranch_decision(multibranch_context_raw)
    kind_resolution = wrap_stage4_kind_resolution(kind_resolution_raw)
    continuous_chain_decision = resolve_stage4_continuous_chain_decision(
        chain_context=chain_context,
        kind_resolution=kind_resolution,
        review_signal=(
            STATUS_CONTINUOUS_CHAIN_REVIEW
            if STATUS_CONTINUOUS_CHAIN_REVIEW in review_signals
            else None
        ),
    )
    reverse_tip_decision = Stage4ReverseTipDecision(
        attempted=reverse_tip_attempted,
        used=reverse_tip_used,
        trigger=reverse_trigger,
        position_source_forward=position_source_forward,
        position_source_reverse=position_source_reverse,
        position_source_final=position_source_final,
        raw={
            "reverse_side_branch_ids": [branch.branch_id for branch in reverse_side_branches],
            "selected_side_branch_ids": [branch.branch_id for branch in selected_side_branches],
        },
    )
    event_reference = Stage4EventReference(
        event_axis_branch_id=event_axis_branch_id,
        event_origin_source=event_origin_source,
        event_position_source=str(event_reference_raw["position_source"]),
        event_split_pick_source=str(event_reference_raw["split_pick_source"]),
        event_chosen_s_m=event_reference_raw["chosen_s_m"],
        event_tip_s_m=event_reference_raw["tip_s_m"],
        event_first_divstrip_hit_s_m=event_reference_raw["first_divstrip_hit_dist_m"],
        event_drivezone_split_s_m=event_reference_raw["s_drivezone_split_m"],
        divstrip_ref_source=event_reference_raw.get("divstrip_ref_source"),
        divstrip_ref_offset_m=event_reference_raw.get("divstrip_ref_offset_m"),
        event_recenter_applied=bool(event_recenter[1]["applied"]),
        event_recenter_shift_m=event_recenter[1]["shift_m"],
        event_recenter_direction=event_recenter[1]["direction"],
        raw=dict(event_reference_raw),
    )
    evidence_decision = Stage4EvidenceDecision(
        primary_source=evidence_primary_source,
        selection_mode=position_source_final or divstrip_context.selection_mode,
        fallback_used=fallback_mode is not None,
        fallback_mode=fallback_mode,
        risk_signals=tuple(
            signal
            for signal in risk_signals
            if signal in {"reverse_tip_used", "fallback_to_weak_evidence"}
        ),
    )
    legacy_step5_bridge = Stage4LegacyStep5Bridge(
        divstrip_context=divstrip_context,
        multibranch_decision=multibranch_decision,
        kind_resolution=kind_resolution,
        selected_side_branches=tuple(selected_side_branches),
        selected_branch_ids=tuple(selected_branch_ids),
        selected_event_branch_ids=tuple(str(item) for item in selected_event_branch_ids),
        selected_road_ids=tuple(selected_road_ids),
        selected_event_road_ids=tuple(sorted(str(item) for item in selected_event_road_ids)),
        selected_rcsdroad_ids=tuple(sorted(str(item) for item in selected_rcsdroad_ids)),
        selected_rcsdnode_ids=tuple(sorted(str(item) for item in selected_rcsdnode_ids)),
        rcsdroad_selection_mode=rcsdroad_selection_mode,
        rcsdnode_seed_mode=rcsdnode_seed_mode,
        primary_main_rc_node=primary_main_rc_node,
        selected_roads=tuple(selected_roads),
        selected_event_roads=tuple(selected_event_roads),
        selected_rcsd_roads=tuple(selected_rcsd_roads),
        selected_rcsd_nodes=tuple(selected_rcsd_nodes),
        effective_target_rc_nodes=tuple(effective_target_rc_nodes),
        complex_local_support_roads=tuple(complex_local_support_roads),
        seed_support_geometries=tuple(seed_support_geometries),
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        event_anchor_geometry=event_anchor_geometry,
        localized_divstrip_reference_geometry=localized_divstrip_reference_geometry,
        event_axis_branch=event_axis_branch,
        event_axis_branch_id=event_axis_branch_id,
        event_axis_centerline=event_axis_centerline,
        provisional_event_origin=provisional_event_origin,
        initial_event_axis_unit_vector=initial_event_axis_unit_vector,
        boundary_branch_a=boundary_branch_a,
        boundary_branch_b=boundary_branch_b,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        event_cross_half_len_m=event_cross_half_len_m,
        event_reference_raw=dict(event_reference_raw),
        event_origin_point=event_origin_point,
        event_origin_source=event_origin_source,
        event_axis_unit_vector=event_axis_unit_vector,
        event_recenter_applied=bool(event_recenter[1]["applied"]),
        event_recenter_shift_m=event_recenter[1]["shift_m"],
        event_recenter_direction=event_recenter[1]["direction"],
    )
    legacy_step5_readiness = _evaluate_stage4_legacy_step5_readiness(
        selected_branch_ids=selected_branch_ids,
        event_reference=event_reference_raw,
    )
    return Stage4EventInterpretationResult(
        representative_mainnodeid=normalize_id(representative_node.mainnodeid or representative_node.node_id),
        representative_node_id=representative_node.node_id,
        evidence_decision=evidence_decision,
        divstrip_context=divstrip_context,
        continuous_chain_decision=continuous_chain_decision,
        multibranch_decision=multibranch_decision,
        kind_resolution=kind_resolution,
        reverse_tip_decision=reverse_tip_decision,
        event_reference=event_reference,
        review_signals=review_signals,
        hard_rejection_signals=tuple(dict.fromkeys(hard_rejection_signals)),
        risk_signals=risk_signals,
        legacy_step5_bridge=legacy_step5_bridge,
        legacy_step5_readiness=legacy_step5_readiness,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
