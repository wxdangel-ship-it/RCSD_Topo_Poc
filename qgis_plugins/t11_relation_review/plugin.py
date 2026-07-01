from __future__ import annotations

from .path_bootstrap import ensure_repo_src_on_path


ensure_repo_src_on_path()

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
