from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_MISSING = object()


class FieldNameConflictError(ValueError):
    """Raised when case-equivalent external fields carry conflicting values."""

    def __init__(
        self,
        logical_name: str,
        matches: Iterable[tuple[str, Any]],
    ) -> None:
        self.logical_name = logical_name
        self.matches = tuple(matches)
        detail = ", ".join(f"{name}={value!r}" for name, value in self.matches)
        super().__init__(f"case-insensitive property conflict for {logical_name!r}: {detail}")


def normalize_field_name(name: object) -> str:
    """Return the stable logical representation of an external field name."""

    return str(name).casefold()


def _candidate_names(candidates: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(candidates, str):
        return (candidates,)
    return tuple(str(candidate) for candidate in candidates)


def _values_equal(first: Any, second: Any) -> bool:
    try:
        result = first == second
        return bool(result)
    except (TypeError, ValueError):
        return False


class PropertyLookup:
    """Case-insensitive lookup over one external record without mutating it."""

    def __init__(self, properties: Mapping[object, Any]) -> None:
        self.properties = properties
        resolved: dict[str, tuple[str, Any]] = {}
        duplicate_matches: dict[str, list[tuple[str, Any]]] = {}
        for raw_name, value in properties.items():
            original_name = str(raw_name)
            logical_name = normalize_field_name(original_name)
            selected = resolved.get(logical_name, _MISSING)
            if selected is _MISSING:
                resolved[logical_name] = (original_name, value)
                continue

            selected_name, selected_value = selected
            matches = duplicate_matches.setdefault(logical_name, [(selected_name, selected_value)])
            matches.append((original_name, value))
            if selected_value is not None and value is not None and not _values_equal(selected_value, value):
                raise FieldNameConflictError(logical_name, matches)
            if selected_value is None and value is not None:
                resolved[logical_name] = (original_name, value)
            elif original_name == logical_name and (value is not None or selected_value is None):
                resolved[logical_name] = (original_name, value)
        self._resolved = resolved

    def has(self, candidates: str | Iterable[str]) -> bool:
        return any(normalize_field_name(candidate) in self._resolved for candidate in _candidate_names(candidates))

    def resolve_name(self, candidates: str | Iterable[str]) -> str | None:
        for candidate in _candidate_names(candidates):
            resolved = self._resolved.get(normalize_field_name(candidate))
            if resolved is not None:
                return resolved[0]
        return None

    def get(
        self,
        candidates: str | Iterable[str],
        default: Any = None,
    ) -> Any:
        for candidate in _candidate_names(candidates):
            resolved = self._resolved.get(normalize_field_name(candidate))
            if resolved is not None:
                return resolved[1]
        return default

    def require(self, candidates: str | Iterable[str], *, label: str | None = None) -> Any:
        value = self.get(candidates, _MISSING)
        if value is _MISSING:
            candidate_names = _candidate_names(candidates)
            subject = label or "/".join(candidate_names)
            raise KeyError(f"required external field not found: {subject}")
        return value

    def normalized_items(self) -> tuple[tuple[str, Any], ...]:
        return tuple((logical_name, resolved[1]) for logical_name, resolved in self._resolved.items())

    def resolved_items(self) -> tuple[tuple[str, Any], ...]:
        """Return one selected original field name and value per logical field."""

        return tuple(self._resolved.values())


def resolve_case_insensitive_field_name(
    properties: Mapping[object, Any],
    candidates: str | Iterable[str],
) -> str | None:
    return PropertyLookup(properties).resolve_name(candidates)


def get_case_insensitive_property(
    properties: Mapping[object, Any],
    candidates: str | Iterable[str],
    *,
    preferred: str | None = None,
    default: Any = None,
) -> Any:
    lookup = PropertyLookup(properties)
    if preferred is not None and preferred in properties:
        return properties[preferred]
    if preferred is None:
        return lookup.get(candidates, default)
    return lookup.get((preferred, *_candidate_names(candidates)), default)


def normalize_property_keys(properties: Mapping[object, Any]) -> dict[str, Any]:
    """Return a canonical-key copy for modules whose internal contract is lowercase."""

    return dict(PropertyLookup(properties).normalized_items())


__all__ = [
    "FieldNameConflictError",
    "PropertyLookup",
    "get_case_insensitive_property",
    "normalize_field_name",
    "normalize_property_keys",
    "resolve_case_insensitive_field_name",
]
