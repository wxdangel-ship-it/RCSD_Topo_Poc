import pytest

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_codes import (
    ARROW_CODE_DEFINITIONS,
    parse_arrow_code,
    parse_arrow_sequence,
)


EXPECTED_TOKENS = {
    "9": ("uninvestigated",),
    "a": ("straight",),
    "b": ("left",),
    "c": ("right",),
    "d": ("uturn",),
    "e": ("straight", "uturn"),
    "f": ("straight", "right"),
    "g": ("straight", "left"),
    "h": ("left", "straight", "right"),
    "i": ("uturn", "straight", "right"),
    "j": ("uturn", "left", "straight"),
    "k": ("left", "right"),
    "l": ("uturn", "left"),
    "m": ("uturn", "left", "right"),
    "n": ("uturn", "right"),
    "o": ("empty",),
    "p": ("left", "straight", "right", "uturn"),
    "r": ("slight_left",),
    "s": ("slight_right",),
    "t": ("straight", "slight_left"),
    "u": ("left", "slight_left"),
    "v": ("right", "slight_left"),
    "w": ("uturn", "slight_left"),
    "x": ("straight", "slight_right"),
    "y": ("left", "slight_right"),
    "z": ("right", "slight_right"),
    "0": ("uturn", "slight_right"),
    "1": ("slight_left", "slight_right"),
    "2": ("straight", "left", "slight_left"),
    "3": ("straight", "left", "slight_right"),
    "4": ("straight", "right", "slight_left"),
    "5": ("straight", "right", "slight_right"),
}


def test_parse_all_spec_arrow_codes() -> None:
    assert set(ARROW_CODE_DEFINITIONS) == set(EXPECTED_TOKENS)

    for code, tokens in EXPECTED_TOKENS.items():
        parsed = parse_arrow_code(code)

        assert parsed.raw_code == code
        assert parsed.tokens == tokens


def test_digit_zero_and_letter_o_are_distinct() -> None:
    digit_zero = parse_arrow_code("0")
    letter_o = parse_arrow_code("o")

    assert digit_zero.tokens == ("uturn", "slight_right")
    assert digit_zero.usable_for_prohibition is True
    assert letter_o.tokens == ("empty",)
    assert letter_o.usable_for_prohibition is False


def test_alphabetic_arrow_code_is_case_normalized_with_raw_code_preserved() -> None:
    parsed = parse_arrow_code("A")

    assert parsed.raw_code == "A"
    assert parsed.tokens == ("straight",)
    assert parsed.usable_for_prohibition is True


def test_parse_arrow_sequence_keeps_lane_order() -> None:
    parsed = parse_arrow_sequence("a,0,o")

    assert tuple(item.raw_code for item in parsed) == ("a", "0", "o")


def test_unknown_arrow_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown SW arrow code"):
        parse_arrow_code("q")
