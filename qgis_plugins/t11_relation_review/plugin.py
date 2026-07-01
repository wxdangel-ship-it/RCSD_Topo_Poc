from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_src_on_path() -> None:
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if repo_src.is_dir() and str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))


_ensure_repo_src_on_path()

from qgis.PyQt.QtCore import Qt  # type: ignore

from .dock_widget import T11RelationReviewDock


class T11RelationReviewPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock: T11RelationReviewDock | None = None

    def initGui(self):  # noqa: N802 - QGIS plugin API
        self.dock = T11RelationReviewDock(self.iface)
        self.iface.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.dock.show()

    def unload(self):
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
