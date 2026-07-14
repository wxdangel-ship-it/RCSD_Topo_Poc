from __future__ import annotations

from typing import Any

__all__ = [
    "ManualRelationTransformArtifacts",
    "ManualRelationTransformError",
    "transform_manual_relations",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .manual_relations import (
            ManualRelationTransformArtifacts,
            ManualRelationTransformError,
            transform_manual_relations,
        )

        return {
            "ManualRelationTransformArtifacts": ManualRelationTransformArtifacts,
            "ManualRelationTransformError": ManualRelationTransformError,
            "transform_manual_relations": transform_manual_relations,
        }[name]
    raise AttributeError(name)
