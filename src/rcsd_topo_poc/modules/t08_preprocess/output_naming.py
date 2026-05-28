from __future__ import annotations

from pathlib import Path


def append_tool_suffix(path: Path, tool_number: int) -> Path:
    suffix = f"_tool{tool_number}"
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def ensure_tool_output_name(path: str | Path, *, tool_number: int, label: str) -> Path:
    output_path = Path(path).expanduser().resolve()
    suffix = f"_tool{tool_number}"
    if not output_path.stem.endswith(suffix):
        raise ValueError(f"{label} file name must end with '{suffix}' before extension: {output_path.name}")
    return output_path
