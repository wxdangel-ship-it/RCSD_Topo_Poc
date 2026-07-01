from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LayerDescriptor:
    name: str
    source_path: str
    crs_authid: str
    fields: frozenset[str]


@dataclass(frozen=True)
class LayerExpectation:
    required_fields: frozenset[str]
    expected_source_path: str | None = None
    expected_crs_authid: str | None = None


@dataclass
class LayerValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


DEFAULT_LAYER_EXPECTATIONS = {
    "task_helper": LayerExpectation(frozenset({"workbook_path", "sheet_name", "excel_row", "target_id", "swsd_segment_id"})),
    "swsd_segment": LayerExpectation(frozenset({"id"})),
    "swsd_semantic_junction": LayerExpectation(frozenset({"id"})),
    "rcsdroad": LayerExpectation(frozenset({"id"})),
    "rcsdnode": LayerExpectation(frozenset({"id", "mainnodeid"})),
}


def validate_layer_bindings(
    layers: dict[str, LayerDescriptor],
    expectations: dict[str, LayerExpectation] | None = None,
) -> LayerValidationResult:
    result = LayerValidationResult()
    expected = expectations or DEFAULT_LAYER_EXPECTATIONS
    for role, rule in expected.items():
        layer = layers.get(role)
        if layer is None:
            result.errors.append(f"missing layer binding: {role}")
            continue
        missing_fields = sorted(rule.required_fields - layer.fields)
        if missing_fields:
            result.errors.append(f"{role} missing required fields: {', '.join(missing_fields)}")
        if rule.expected_source_path and _norm(layer.source_path) != _norm(rule.expected_source_path):
            result.errors.append(
                f"{role} source mismatch: bound={layer.source_path}; expected={rule.expected_source_path}"
            )
        if not layer.crs_authid:
            result.errors.append(f"{role} CRS is empty")
        elif rule.expected_crs_authid and layer.crs_authid != rule.expected_crs_authid:
            result.warnings.append(
                f"{role} CRS differs: bound={layer.crs_authid}; expected={rule.expected_crs_authid}; transform required"
            )
    _warn_cross_crs(layers.values(), result)
    return result


def _warn_cross_crs(layers: Iterable[LayerDescriptor], result: LayerValidationResult) -> None:
    crs_values = sorted({layer.crs_authid for layer in layers if layer.crs_authid})
    if len(crs_values) > 1:
        result.warnings.append(f"bound layers use multiple CRS values: {', '.join(crs_values)}; QGIS transform required")


def _norm(path: str) -> str:
    text = str(path).split("|", 1)[0]
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return text
