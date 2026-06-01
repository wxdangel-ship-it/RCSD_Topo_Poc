from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedArrowCode:
    raw_code: str
    label_zh: str
    tokens: tuple[str, ...]

    @property
    def usable_for_prohibition(self) -> bool:
        return "uninvestigated" not in self.tokens and "empty" not in self.tokens


ARROW_CODE_DEFINITIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "9": ("未调查", ("uninvestigated",)),
    "a": ("直", ("straight",)),
    "b": ("左", ("left",)),
    "c": ("右", ("right",)),
    "d": ("调", ("uturn",)),
    "e": ("直调", ("straight", "uturn")),
    "f": ("直右", ("straight", "right")),
    "g": ("直左", ("straight", "left")),
    "h": ("左直右", ("left", "straight", "right")),
    "i": ("调直右", ("uturn", "straight", "right")),
    "j": ("调左直", ("uturn", "left", "straight")),
    "k": ("左右", ("left", "right")),
    "l": ("调左", ("uturn", "left")),
    "m": ("调左右", ("uturn", "left", "right")),
    "n": ("调右", ("uturn", "right")),
    "o": ("空", ("empty",)),
    "p": ("左直右调", ("left", "straight", "right", "uturn")),
    "r": ("斜左", ("slight_left",)),
    "s": ("斜右", ("slight_right",)),
    "t": ("直斜左", ("straight", "slight_left")),
    "u": ("左斜左", ("left", "slight_left")),
    "v": ("右斜左", ("right", "slight_left")),
    "w": ("调斜左", ("uturn", "slight_left")),
    "x": ("直斜右", ("straight", "slight_right")),
    "y": ("左斜右", ("left", "slight_right")),
    "z": ("右斜右", ("right", "slight_right")),
    "0": ("调斜右", ("uturn", "slight_right")),
    "1": ("斜左斜右", ("slight_left", "slight_right")),
    "2": ("直左斜左", ("straight", "left", "slight_left")),
    "3": ("直左斜右", ("straight", "left", "slight_right")),
    "4": ("直右斜左", ("straight", "right", "slight_left")),
    "5": ("直右斜右", ("straight", "right", "slight_right")),
}


def parse_arrow_code(code: str) -> ParsedArrowCode:
    raw_code = str(code).strip()
    lookup_code = raw_code.lower()
    if lookup_code not in ARROW_CODE_DEFINITIONS:
        raise ValueError(f"Unknown SW arrow code: {code!r}")
    label_zh, tokens = ARROW_CODE_DEFINITIONS[lookup_code]
    return ParsedArrowCode(raw_code=raw_code, label_zh=label_zh, tokens=tokens)


def parse_arrow_sequence(codes: str | tuple[str, ...] | list[str]) -> tuple[ParsedArrowCode, ...]:
    if isinstance(codes, str):
        raw_codes = tuple(item.strip() for item in codes.split(",") if item.strip())
    else:
        raw_codes = tuple(str(item).strip() for item in codes if str(item).strip())
    return tuple(parse_arrow_code(code) for code in raw_codes)


def arrow_tokens_support_movement(tokens: tuple[str, ...], movement_type: str) -> bool:
    normalized = movement_type.strip().lower()
    return normalized in tokens
