from __future__ import annotations


def classFactory(iface):  # noqa: N802 - QGIS plugin API
    from .plugin import T11RelationReviewPlugin

    return T11RelationReviewPlugin(iface)
