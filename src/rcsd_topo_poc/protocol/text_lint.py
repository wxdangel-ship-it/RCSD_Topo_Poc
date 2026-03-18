from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.utils.size_guard import MAX_BYTES, MAX_LINES, measure_text


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""

    def __str__(self) -> str:
        return self.code if not self.detail else f"{self.code}:{self.detail}"


def lint_text(text: str) -> tuple[bool, list[str]]:
    """Check whether text is pasteable.

    This is a pasteability guard (size/shape), not a sensitive-content filter.
    """

    violations: list[Violation] = []

    size = measure_text(text)
    if size.lines > MAX_LINES:
        violations.append(Violation("SIZE_LINES", f"lines={size.lines} max={MAX_LINES}"))
    if size.bytes_utf8 > MAX_BYTES:
        violations.append(Violation("SIZE_BYTES", f"bytes={size.bytes_utf8} max={MAX_BYTES}"))

    for idx, line in enumerate(text.splitlines(), start=1):
        if len(line) > 2000:
            violations.append(Violation("LONG_LINE", f"line={idx} len={len(line)}"))

    hard = [x for x in violations if x.code.startswith("SIZE_")]
    ok = len(hard) == 0
    return ok, [str(x) for x in violations]
