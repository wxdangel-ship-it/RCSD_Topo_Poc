from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


CONNECTIVITY_TERMINAL_TOLERANCE_M = 1.0


@dataclass
class BusinessConnectivityCache:
    """Per-case cache for repeated terminal-partition audits.

    Step6 evaluates the same terminals and output surface against several
    source surfaces.  Keeping object references in every cache entry makes
    identity-based keys safe for the lifetime of one case while avoiding WKB
    serialization and repeated terminal buffers.
    """

    _component_entries: dict[int, tuple[BaseGeometry | None, list[BaseGeometry]]] = field(
        default_factory=dict
    )
    _probe_entries: dict[
        tuple[float, tuple[tuple[str, int], ...]],
        tuple[tuple[BaseGeometry, ...], dict[str, BaseGeometry]],
    ] = field(default_factory=dict)
    _membership_entries: dict[
        tuple[int, float, tuple[tuple[str, int], ...]],
        tuple[BaseGeometry | None, tuple[BaseGeometry, ...], dict[str, tuple[int, ...]]],
    ] = field(default_factory=dict)

    @staticmethod
    def _terminal_signature(
        ordered_terminal_ids: list[str],
        terminals: dict[str, BaseGeometry],
    ) -> tuple[tuple[str, int], ...]:
        return tuple(
            (terminal_id, id(terminals[terminal_id]))
            for terminal_id in ordered_terminal_ids
        )

    @staticmethod
    def _same_terminal_objects(
        left: tuple[BaseGeometry, ...],
        right: tuple[BaseGeometry, ...],
    ) -> bool:
        return len(left) == len(right) and all(
            left_item is right_item
            for left_item, right_item in zip(left, right)
        )

    def components(self, geometry: BaseGeometry | None) -> list[BaseGeometry]:
        key = id(geometry)
        entry = self._component_entries.get(key)
        if entry is not None and entry[0] is geometry:
            return entry[1]
        components = _polygon_components(geometry)
        self._component_entries[key] = (geometry, components)
        return components

    def probes(
        self,
        *,
        ordered_terminal_ids: list[str],
        terminals: dict[str, BaseGeometry],
        tolerance_m: float,
    ) -> dict[str, BaseGeometry]:
        signature = self._terminal_signature(ordered_terminal_ids, terminals)
        key = (tolerance_m, signature)
        terminal_objects = tuple(terminals[item] for item in ordered_terminal_ids)
        entry = self._probe_entries.get(key)
        if entry is not None and self._same_terminal_objects(entry[0], terminal_objects):
            return entry[1]
        probes = {
            terminal_id: (
                terminals[terminal_id].buffer(tolerance_m)
                if tolerance_m > 0
                else terminals[terminal_id]
            )
            for terminal_id in ordered_terminal_ids
        }
        self._probe_entries[key] = (terminal_objects, probes)
        return probes

    def membership(
        self,
        *,
        surface: BaseGeometry | None,
        ordered_terminal_ids: list[str],
        terminals: dict[str, BaseGeometry],
        probes: dict[str, BaseGeometry],
        tolerance_m: float,
    ) -> tuple[list[BaseGeometry], dict[str, tuple[int, ...]]]:
        signature = self._terminal_signature(ordered_terminal_ids, terminals)
        key = (id(surface), tolerance_m, signature)
        terminal_objects = tuple(terminals[item] for item in ordered_terminal_ids)
        entry = self._membership_entries.get(key)
        if (
            entry is not None
            and entry[0] is surface
            and self._same_terminal_objects(entry[1], terminal_objects)
        ):
            return self.components(surface), entry[2]
        components = self.components(surface)
        membership = {
            terminal_id: _terminal_component_ids(
                components,
                probes[terminal_id],
            )
            for terminal_id in ordered_terminal_ids
        }
        self._membership_entries[key] = (surface, terminal_objects, membership)
        return components, membership


def _polygon_components(geometry: BaseGeometry | None) -> list[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        return [
            part
            for item in geometry.geoms
            for part in _polygon_components(item)
        ]
    return []


def _terminal_component_ids(
    components: list[BaseGeometry],
    probe: BaseGeometry,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, component in enumerate(components)
        if component.intersects(probe)
    )


def build_business_connectivity_audit(
    *,
    source_surface: BaseGeometry | None,
    output_surface: BaseGeometry | None,
    terminals: dict[str, BaseGeometry],
    tolerance_m: float = CONNECTIVITY_TERMINAL_TOLERANCE_M,
    cache: BusinessConnectivityCache | None = None,
) -> dict[str, Any]:
    ordered_terminal_ids = sorted(terminals)
    effective_cache = cache or BusinessConnectivityCache()
    probes = effective_cache.probes(
        ordered_terminal_ids=ordered_terminal_ids,
        terminals=terminals,
        tolerance_m=tolerance_m,
    )
    source_components, source_membership = effective_cache.membership(
        surface=source_surface,
        ordered_terminal_ids=ordered_terminal_ids,
        terminals=terminals,
        probes=probes,
        tolerance_m=tolerance_m,
    )
    output_components, output_membership = effective_cache.membership(
        surface=output_surface,
        ordered_terminal_ids=ordered_terminal_ids,
        terminals=terminals,
        probes=probes,
        tolerance_m=tolerance_m,
    )
    source_missing = [
        terminal_id for terminal_id in ordered_terminal_ids if not source_membership[terminal_id]
    ]
    output_missing = [
        terminal_id for terminal_id in ordered_terminal_ids if not output_membership[terminal_id]
    ]
    mismatch_rows: list[dict[str, Any]] = []
    comparable_pair_count = 0
    for left_id, right_id in combinations(ordered_terminal_ids, 2):
        left_source = set(source_membership[left_id])
        right_source = set(source_membership[right_id])
        left_output = set(output_membership[left_id])
        right_output = set(output_membership[right_id])
        if not left_source or not right_source or not left_output or not right_output:
            continue
        comparable_pair_count += 1
        source_connected = bool(left_source & right_source)
        output_connected = bool(left_output & right_output)
        if source_connected == output_connected:
            continue
        mismatch_rows.append(
            {
                "left_terminal_id": left_id,
                "right_terminal_id": right_id,
                "source_connected": source_connected,
                "output_connected": output_connected,
                "mismatch_type": (
                    "source_connected_output_split"
                    if source_connected
                    else "source_split_output_connected"
                ),
            }
        )
    comparable = bool(ordered_terminal_ids) and not source_missing
    equivalent = comparable and not output_missing and not mismatch_rows
    return {
        "mode": "business_terminal_connectivity_partition",
        "tolerance_m": tolerance_m,
        "terminal_count": len(ordered_terminal_ids),
        "terminal_ids": ordered_terminal_ids,
        "source_component_count": len(source_components),
        "output_component_count": len(output_components),
        "source_terminal_component_ids": {
            key: list(value) for key, value in source_membership.items()
        },
        "output_terminal_component_ids": {
            key: list(value) for key, value in output_membership.items()
        },
        "source_missing_terminal_ids": source_missing,
        "output_missing_terminal_ids": output_missing,
        "comparable_pair_count": comparable_pair_count,
        "mismatch_count": len(mismatch_rows),
        "mismatches": mismatch_rows,
        "comparable": comparable,
        "equivalent": equivalent,
        "silent_fix": False,
        "source_geometry_modified": False,
    }
