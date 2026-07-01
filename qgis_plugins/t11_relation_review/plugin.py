from __future__ import annotations

from .path_bootstrap import ensure_repo_src_on_path


ensure_repo_src_on_path()

from qgis.PyQt.QtCore import Qt  # type: ignore

from .dock_widget import T11RelationProcessingDock, T11RelationReviewDock


class T11RelationReviewPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.task_dock: T11RelationReviewDock | None = None
        self.processing_dock: T11RelationProcessingDock | None = None

    def initGui(self):  # noqa: N802 - QGIS plugin API
        self.task_dock = T11RelationReviewDock(self.iface)
        self.processing_dock = T11RelationProcessingDock(self.iface, self.task_dock)
        self.task_dock.bind_processing_dock(self.processing_dock)
        self.iface.addDockWidget(Qt.LeftDockWidgetArea, self.task_dock)
        self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.processing_dock)
        self.task_dock.show()
        self.processing_dock.show()

    def unload(self):
        if self.processing_dock is not None:
            self.iface.removeDockWidget(self.processing_dock)
            self.processing_dock.deleteLater()
            self.processing_dock = None
        if self.task_dock is not None:
            self.iface.removeDockWidget(self.task_dock)
            self.task_dock.deleteLater()
            self.task_dock = None
