from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


_SEMANTIC_PREFIXES = (
    "action:",
    "dependency_count:",
    "evidence_role:",
    "geometry_type:",
    "has_base:",
    "lineage_kind:",
    "object_kind:",
    "object_type:",
    "output_count:",
    "payload:",
    "pointer_state:",
    "property:",
    "source_count:",
    "source_kind:",
    "source_role:",
)


def count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 7:
        return "4-7"
    if value <= 15:
        return "8-15"
    if value <= 31:
        return "16-31"
    if value <= 63:
        return "32-63"
    return "64+"


@dataclass(frozen=True)
class GroupDescriptor:
    case_key: str
    domain: str
    group_id: str
    object_type: str
    option_count: int
    invariant_tokens: tuple[str, ...]
    union_tokens: tuple[str, ...]
    dependencies: tuple[str, ...] = ()


def describe_group(
    rows: Sequence[Mapping[str, Any]], *, dependencies: Iterable[str] = ()
) -> GroupDescriptor:
    if not rows:
        raise ValueError("group rows must not be empty")
    identity = {
        (str(row["case_key"]), str(row["domain"]), str(row["group_id"])) for row in rows
    }
    if len(identity) != 1:
        raise ValueError("group rows have mixed identity")
    object_types = {str(row["object_type"]) for row in rows}
    if len(object_types) != 1:
        raise ValueError("group rows have mixed object type")
    token_sets = [set(str(token) for token in row.get("feature_tokens") or []) for row in rows]
    union_tokens = set().union(*token_sets)
    invariant_tokens = set.intersection(*token_sets)
    case_key, domain, group_id = next(iter(identity))
    return GroupDescriptor(
        case_key=case_key,
        domain=domain,
        group_id=group_id,
        object_type=next(iter(object_types)),
        option_count=len(rows),
        invariant_tokens=tuple(sorted(invariant_tokens)),
        union_tokens=tuple(sorted(union_tokens)),
        dependencies=tuple(sorted(set(str(value) for value in dependencies))),
    )


def reverse_dependencies(
    descriptors: Mapping[tuple[str, str, str], GroupDescriptor],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    result: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for key, descriptor in descriptors.items():
        if descriptor.domain != "JSG":
            continue
        for dependency in descriptor.dependencies:
            dep_key = (descriptor.case_key, descriptor.domain, dependency)
            if dep_key in descriptors:
                result[dep_key].add(descriptor.group_id)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def _semantic_tokens(tokens: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(token for token in set(tokens) if token.startswith(_SEMANTIC_PREFIXES)))


def build_context_tokens(
    descriptor: GroupDescriptor,
    *,
    descriptors: Mapping[tuple[str, str, str], GroupDescriptor],
    reverse_map: Mapping[tuple[str, str, str], Sequence[str]],
    case_type_counts: Mapping[tuple[str, str], Mapping[str, int]],
    structural_tokens: Mapping[tuple[str, str, str], Sequence[str]] | None = None,
) -> tuple[str, ...]:
    structural_tokens = structural_tokens or {}
    key = (descriptor.case_key, descriptor.domain, descriptor.group_id)
    tokens = {
        f"ctx:domain={descriptor.domain}",
        f"ctx:self_type={descriptor.object_type}",
        f"ctx:self_option_count={count_bucket(descriptor.option_count)}",
        f"ctx:dependency_count={count_bucket(len(descriptor.dependencies))}",
        f"ctx:reverse_dependency_count={count_bucket(len(reverse_map.get(key, ())))}",
    }
    for token in _semantic_tokens(descriptor.invariant_tokens):
        tokens.add(f"ctx:self_invariant:{token}")
    for token in _semantic_tokens(descriptor.union_tokens):
        tokens.add(f"ctx:self_available:{token}")
    for token in structural_tokens.get(key, ()):
        tokens.add(f"ctx:self_structure:{token}")

    dependency_types: Counter[str] = Counter()
    for dependency in descriptor.dependencies:
        dep_key = (descriptor.case_key, descriptor.domain, dependency)
        neighbor = descriptors.get(dep_key)
        if neighbor is None:
            tokens.add("ctx:dependency_missing=true")
            continue
        dependency_types[neighbor.object_type] += 1
        tokens.add(
            f"ctx:dependency:{neighbor.object_type}:option_count={count_bucket(neighbor.option_count)}"
        )
        tokens.add(
            f"ctx:dependency:{neighbor.object_type}:dependency_count={count_bucket(len(neighbor.dependencies))}"
        )
        tokens.add(
            f"ctx:dependency:{neighbor.object_type}:reverse_count={count_bucket(len(reverse_map.get(dep_key, ())))}"
        )
        for token in _semantic_tokens(neighbor.invariant_tokens):
            tokens.add(f"ctx:dependency:{neighbor.object_type}:{token}")
        for token in structural_tokens.get(dep_key, ()):
            tokens.add(f"ctx:dependency:{neighbor.object_type}:structure:{token}")
    for object_type, count in dependency_types.items():
        tokens.add(f"ctx:dependency_type_count:{object_type}={count_bucket(count)}")

    reverse_types: Counter[str] = Counter()
    for dependent_id in reverse_map.get(key, ()):
        neighbor = descriptors.get((descriptor.case_key, descriptor.domain, dependent_id))
        if neighbor is None:
            continue
        reverse_types[neighbor.object_type] += 1
        neighbor_key = (descriptor.case_key, descriptor.domain, dependent_id)
        tokens.add(
            f"ctx:reverse:{neighbor.object_type}:option_count={count_bucket(neighbor.option_count)}"
        )
        tokens.add(
            f"ctx:reverse:{neighbor.object_type}:dependency_count={count_bucket(len(neighbor.dependencies))}"
        )
        for token in _semantic_tokens(neighbor.invariant_tokens):
            tokens.add(f"ctx:reverse:{neighbor.object_type}:{token}")
        for token in structural_tokens.get(neighbor_key, ()):
            tokens.add(f"ctx:reverse:{neighbor.object_type}:structure:{token}")
    for object_type, count in reverse_types.items():
        tokens.add(f"ctx:reverse_type_count:{object_type}={count_bucket(count)}")

    for object_type, count in sorted(
        case_type_counts.get((descriptor.case_key, descriptor.domain), {}).items()
    ):
        tokens.add(f"ctx:case_type_count:{object_type}={count_bucket(int(count))}")
    return tuple(sorted(tokens))


def forbidden_context_hits(
    tokens: Iterable[str], *, identifiers: Iterable[str] = ()
) -> list[str]:
    blocked_markers = (
        "candidate_id",
        "case_id",
        "case_key",
        "business_id",
        "object_id",
        "group_id",
        "oracle",
        "truth",
        "absolute_coordinate",
    )
    identity = {str(value) for value in identifiers if str(value)}
    hits: list[str] = []
    for token in tokens:
        folded = token.casefold()
        if any(marker in folded for marker in blocked_markers):
            hits.append(token)
            continue
        if any(value in token for value in identity):
            hits.append(token)
    return sorted(set(hits))


__all__ = [
    "GroupDescriptor",
    "build_context_tokens",
    "count_bucket",
    "describe_group",
    "forbidden_context_hits",
    "reverse_dependencies",
]
