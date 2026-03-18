from __future__ import annotations

from dataclasses import dataclass


MAX_LINES = 120
MAX_BYTES = 8 * 1024


@dataclass(frozen=True)
class SizeCheck:
    lines: int
    bytes_utf8: int


def measure_text(text: str) -> SizeCheck:
    return SizeCheck(lines=len(text.splitlines()), bytes_utf8=len(text.encode("utf-8")))


def within_limits(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> bool:
    size = measure_text(text)
    return (size.lines <= max_lines) and (size.bytes_utf8 <= max_bytes)


def apply_size_limit(
    text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES
) -> tuple[str, bool, str]:
    """Enforce <=max_lines OR <=max_bytes on the returned text."""

    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    if lines and lines[-1].strip() == "=== END ===":
        lines.pop()
    if lines and lines[-1].lstrip().startswith("Truncated:"):
        lines.pop()
    if lines and lines[-1].strip() == "=== END ===":
        lines.pop()

    base_lines = lines

    def _join(ls: list[str]) -> str:
        return "\n".join(ls) + "\n"

    not_truncated = base_lines + ["Truncated: false (reason=na)", "=== END ==="]
    out = _join(not_truncated)
    if within_limits(out, max_lines=max_lines, max_bytes=max_bytes):
        return out, False, "na"

    reason = "size_limit"
    footer = [f"Truncated: true (reason={reason})", "=== END ==="]
    keep = base_lines[: max(0, max_lines - len(footer))]
    out = _join(keep + footer)

    while keep and not within_limits(out, max_lines=max_lines, max_bytes=max_bytes):
        keep = keep[:-1]
        out = _join(keep + footer)

    if not within_limits(out, max_lines=max_lines, max_bytes=max_bytes):
        out = _join(footer)

    return out, True, reason
