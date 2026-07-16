from __future__ import annotations

import pytest

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parsing import (
    ParseError,
    normalize_id,
    unique_preserve_order,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1885118", "1885118"),
        ("-1885118", "-1885118"),
        ("1885118.0", "1885118"),
        ("-1885118.000", "-1885118"),
        ("1885118.25", "1885118.25"),
        ("source_1:road-42", "source_1:road-42"),
        ('"1885118"', "1885118"),
        (1885118, "1885118"),
    ],
)
def test_normalize_id_preserves_existing_contract(value, expected):
    assert normalize_id(value) == expected


@pytest.mark.parametrize("value", [None, True, "", "NULL", "nan", "[]"])
def test_normalize_id_rejects_empty_or_boolean_values(value):
    with pytest.raises(ParseError):
        normalize_id(value)


def test_unique_preserve_order_keeps_first_occurrence_for_list_and_generator():
    expected = ["r2", "r1", "r3"]

    assert unique_preserve_order(["r2", "r1", "r2", "r3", "r1"]) == expected
    assert unique_preserve_order(value for value in ["r2", "r1", "r2", "r3", "r1"]) == expected
