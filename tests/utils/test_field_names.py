from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from rcsd_topo_poc.utils.field_names import (
    FieldNameConflictError,
    PropertyLookup,
    get_case_insensitive_property,
    normalize_field_name,
    normalize_property_keys,
    resolve_case_insensitive_field_name,
)


def test_normalize_field_name_uses_unicode_casefold() -> None:
    assert normalize_field_name("snodeId") == "snodeid"
    assert normalize_field_name("Straße") == "strasse"


def test_property_lookup_resolves_mixed_case_without_mutating_properties() -> None:
    properties = {"snodeId": "n1", "enodeID": "n2", "formWay": 4}
    original = dict(properties)

    lookup = PropertyLookup(properties)

    assert lookup.has("SNODEID") is True
    assert lookup.resolve_name("snodeid") == "snodeId"
    assert lookup.get("snodeid") == "n1"
    assert lookup.get(("missing_alias", "ENODEID")) == "n2"
    assert lookup.get("missing", default="fallback") == "fallback"
    assert properties == original


def test_property_lookup_candidate_priority_is_explicit() -> None:
    lookup = PropertyLookup({"id": "canonical", "road_id": "alias"})

    assert lookup.get(("road_id", "id")) == "alias"
    assert lookup.get(("id", "road_id")) == "canonical"


def test_property_lookup_accepts_equal_or_single_non_null_case_variants() -> None:
    equal = PropertyLookup({"ID": "r1", "id": "r1"})
    one_non_null = PropertyLookup({"SNODEID": None, "snodeId": "n1"})

    assert equal.get("id") == "r1"
    assert one_non_null.get("snodeid") == "n1"
    assert one_non_null.resolve_name("snodeid") == "snodeId"
    assert one_non_null.resolved_items() == (("snodeId", "n1"),)


def test_property_lookup_rejects_conflicting_case_variants() -> None:
    with pytest.raises(FieldNameConflictError) as exc_info:
        PropertyLookup({"snodeid": "n1", "snodeId": "n2"})

    message = str(exc_info.value)
    assert "snodeid" in message
    assert "snodeId" in message
    assert "n1" in message
    assert "n2" in message


def test_compatibility_helpers_share_property_lookup_rules() -> None:
    properties = {"MainNodeId": "100"}

    assert resolve_case_insensitive_field_name(properties, ("mainnodeid",)) == "MainNodeId"
    assert get_case_insensitive_property(properties, ("mainnodeid",)) == "100"


def test_normalize_property_keys_returns_canonical_copy_and_detects_conflict() -> None:
    properties = {"ID": "r1", "snodeId": "n1"}

    assert normalize_property_keys(properties) == {"id": "r1", "snodeid": "n1"}
    assert properties == {"ID": "r1", "snodeId": "n1"}

    with pytest.raises(FieldNameConflictError):
        normalize_property_keys({"ID": "r1", "id": "r2"})


def test_activity_modules_do_not_reimplement_case_insensitive_field_scans() -> None:
    modules_root = Path(__file__).resolve().parents[2] / "src" / "rcsd_topo_poc" / "modules"
    forbidden = (
        re.compile(r"lower_map\s*=\s*\{[^\n]*\.lower\("),
        re.compile(r"lowered\s*=\s*\{[^\n]*\.lower\("),
        re.compile(r"(?:str\(key\)|key|field_name)\.lower\(\)\s*=="),
        re.compile(r"\b(?:key|existing|field_name|column|geometry_column|candidate)\.lower\("),
        re.compile(r"\b(?:table_name|column_name|endpoint_field)\.lower\("),
        re.compile(r"str\((?:key|existing|field_name|column)\)\.lower\("),
        re.compile(r"str\([^\n]+\)\.lower\(\)\s+for\s+[^\n]+schema"),
    )
    violations: list[str] = []
    for path in modules_root.rglob("*.py"):
        if "t02_junction_anchor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{path.relative_to(modules_root)}:{pattern.pattern}")

    assert violations == []


def test_property_lookup_builds_one_index_for_repeated_field_reads() -> None:
    class CountingMapping(Mapping[str, object]):
        def __init__(self) -> None:
            self.data = {"ID": "r1", "snodeId": "n1", "enodeId": "n2", "formWay": 4}
            self.iteration_count = 0

        def __getitem__(self, key: str) -> object:
            return self.data[key]

        def __iter__(self) -> Iterator[str]:
            self.iteration_count += 1
            return iter(self.data)

        def __len__(self) -> int:
            return len(self.data)

    properties = CountingMapping()
    lookup = PropertyLookup(properties)
    iterations_after_build = properties.iteration_count

    for _ in range(100):
        assert lookup.get("id") == "r1"
        assert lookup.get("snodeid") == "n1"
        assert lookup.get("enodeid") == "n2"
        assert lookup.get("formway") == 4

    assert iterations_after_build == 1
    assert properties.iteration_count == iterations_after_build
