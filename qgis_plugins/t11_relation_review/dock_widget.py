from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import QSize, QTimer, Qt  # type: ignore
from qgis.PyQt.QtGui import QColor  # type: ignore
from qgis.PyQt.QtWidgets import (  # type: ignore
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMapLayerProxyModel, QgsPointXY, QgsProject, QgsRectangle  # type: ignore
from qgis.gui import QgsMapLayerComboBox  # type: ignore


from .path_bootstrap import ensure_repo_src_on_path


ensure_repo_src_on_path()

from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.excel_sync import (
    check_workbook_writable,
    update_manual_fields,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.ids import (
    extract_rcsdnode_selected_ids,
    extract_rcsdroad_selected_ids,
    parse_selected_ids,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.layer_validation import (
    DEFAULT_LAYER_EXPECTATIONS,
    LayerDescriptor,
    expectations_for_bound_layers,
    validate_layer_bindings,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.task_index import (
    ReviewTask,
    load_review_tasks,
    task_status,
)


RELATION_TYPES = [
    "",
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
    "no_valid_relation",
    "uncertain",
]
RELATION_TYPE_BUTTONS = [
    ("J 1v1", "1v1_rcsd_junction", "Use RCSDNode selection and write mainnodeid/id."),
    ("J 1vN", "1vN_rcsd_junction", "Use RCSDNode selection and write mainnodeid/id."),
    ("R 1v1", "1v1_rcsd_road", "Use RCSDRoad selection and write id."),
    ("R 1vN", "1vN_rcsd_road", "Use RCSDRoad selection and write id."),
    ("No valid", "no_valid_relation", "Mark no valid relation and write selected_ids=NULL."),
    ("Uncertain", "uncertain", "Mark this task as uncertain."),
]
DEFAULT_LOCATE_SCALE = 1500
DEFAULT_FONT_SIZE = 11
TASK_STATUS_LABELS = {
    "blank": "NO DATA",
    "partial": "PARTIAL",
    "filled": "HAS DATA",
    "NULL": "NULL CONFIRMED",
    "uncertain": "UNCERTAIN",
}
TASK_STATUS_BACKGROUNDS = {
    "blank": "#fff8e1",
    "partial": "#fff3cd",
    "filled": "#e8f5e9",
    "NULL": "#f1f3f4",
    "uncertain": "#e3f2fd",
}
TASK_DATA_SYMBOLS = {
    "blank": "❌ -",
    "partial": "❌ -",
    "filled": "✅ +",
    "NULL": "✅ +",
    "uncertain": "✅ +",
}


def build_dock_style(font_size: int) -> str:
    task_item_height = max(30, font_size * 3)
    return f"""
QWidget {{
    font-size: {font_size}pt;
}}
QGroupBox {{
    font-size: {font_size}pt;
    font-weight: 600;
    margin-top: 10px;
    padding-top: 8px;
}}
QLabel, QComboBox, QLineEdit, QListWidget, QPlainTextEdit, QSpinBox {{
    font-size: {font_size}pt;
}}
QPushButton {{
    font-size: {font_size}pt;
    min-height: 26px;
    padding: 3px 7px;
}}
QPushButton:checked {{
    background-color: #dcefe4;
    border: 1px solid #2f7d57;
    font-weight: 600;
}}
QLineEdit, QComboBox, QSpinBox {{
    min-height: 26px;
}}
QListWidget::item {{
    min-height: {task_item_height}px;
    padding: 2px 3px;
}}
"""


class T11RelationReviewDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("T11 Relation Tasks")
        self.iface = iface
        self.tasks: list[ReviewTask] = []
        self.current_index = -1
        self.page_size = 50
        self.current_page = 0
        self.read_only = False
        self._loading_ui = False
        self.font_size = DEFAULT_FONT_SIZE
        self.processing_dock: T11RelationProcessingDock | None = None
        self._backed_up_workbooks: set[Path] = set()
        self._skip_next_clicked_index: int | None = None
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_current_task)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._build_ui()

    def bind_processing_dock(self, processing_dock: "T11RelationProcessingDock") -> None:
        self.processing_dock = processing_dock
        processing_dock.relation_type.currentTextChanged.connect(self._relation_type_changed)
        processing_dock.selected_ids.editingFinished.connect(self._queue_sync)
        processing_dock.comment.textChanged.connect(self._queue_sync)
        processing_dock.set_font_size(self.font_size)

    def _build_ui(self) -> None:
        self.setMinimumWidth(260)
        root = QWidget(self)
        self.root_widget = root
        root.setMinimumWidth(240)
        root.setStyleSheet(build_dock_style(self.font_size))
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        setup_header = QHBoxLayout()
        self.setup_toggle_button = QPushButton("Hide setup")
        self.setup_toggle_button.clicked.connect(self._toggle_setup)
        self.setup_summary_label = QLabel("")
        self.setup_summary_label.setWordWrap(False)
        self.setup_summary_label.setMinimumWidth(0)
        self.setup_summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 16)
        self.font_size_spin.setValue(self.font_size)
        self.font_size_spin.setToolTip("Adjust font size for both T11 Relation Tasks and T11 Relation Processing.")
        self.font_size_spin.valueChanged.connect(self._set_font_size)
        setup_header.addWidget(self.setup_toggle_button)
        setup_header.addWidget(self.setup_summary_label, stretch=1)
        setup_header.addWidget(QLabel("Font"))
        setup_header.addWidget(self.font_size_spin)
        layout.addLayout(setup_header)

        self.setup_body = QWidget(root)
        setup_layout = QVBoxLayout(self.setup_body)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(4)

        workbook_box = QGroupBox("Workbook")
        workbook_layout = QGridLayout(workbook_box)
        workbook_layout.setContentsMargins(6, 6, 6, 6)
        workbook_layout.setVerticalSpacing(4)
        self.audit_workbook_path = QLineEdit()
        self.audit_workbook_path.setMinimumWidth(80)
        self.audit_workbook_path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.audit_workbook_path.textChanged.connect(self._update_setup_summary)
        workbook_layout.addWidget(QLabel("Audit workbook"), 0, 0)
        workbook_layout.addWidget(self.audit_workbook_path, 0, 1)
        workbook_layout.addWidget(self._browse_button(self.audit_workbook_path), 0, 2)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_tasks)
        workbook_layout.addWidget(load_button, 1, 0, 1, 3)
        setup_layout.addWidget(workbook_box)

        layer_box = QGroupBox("Layer Binding")
        layer_layout = QFormLayout(layer_box)
        layer_layout.setContentsMargins(6, 6, 6, 6)
        layer_layout.setVerticalSpacing(4)
        layer_layout.setHorizontalSpacing(6)
        self.layer_combos: dict[str, QgsMapLayerComboBox] = {}
        for role, label in [
            ("task_helper", "Task/helper"),
            ("swsd_segment", "SWSD Segment"),
            ("swsd_semantic_junction", "SWSD Junction"),
            ("rcsdroad", "RCSDRoad"),
            ("rcsdnode", "RCSDNode"),
        ]:
            combo = QgsMapLayerComboBox()
            combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
            combo.setMinimumWidth(80)
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            if role == "task_helper":
                combo.setAllowEmptyLayer(True)
            combo.layerChanged.connect(self._update_setup_summary)
            self.layer_combos[role] = combo
            layer_layout.addRow(label, combo)
        validate_button = QPushButton("Validate layers")
        validate_button.clicked.connect(self._validate_layers)
        layer_layout.addRow(validate_button)
        setup_layout.addWidget(layer_box)
        layout.addWidget(self.setup_body)

        pager = QHBoxLayout()
        self.prev_page_button = QPushButton("Prev")
        self.next_page_button = QPushButton("Next")
        self.page_label = QLabel("0 / 0")
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(10, 500)
        self.page_size_spin.setValue(self.page_size)
        self.page_size_spin.valueChanged.connect(self._set_page_size)
        self.prev_page_button.clicked.connect(lambda: self._turn_page(-1))
        self.next_page_button.clicked.connect(lambda: self._turn_page(1))
        pager.addWidget(self.prev_page_button)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_page_button)
        pager.addWidget(QLabel("Page size"))
        pager.addWidget(self.page_size_spin)
        layout.addLayout(pager)

        self.task_list = QListWidget()
        self.task_list.setMinimumWidth(0)
        self.task_list.currentRowChanged.connect(self._task_row_changed)
        self.task_list.itemClicked.connect(self._task_item_clicked)
        layout.addWidget(self.task_list, stretch=1)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.setWidget(root)
        self._update_setup_summary()

    def _toggle_setup(self) -> None:
        self._set_setup_visible(not self.setup_body.isVisible())

    def _set_setup_visible(self, visible: bool) -> None:
        self.setup_body.setVisible(visible)
        self.setup_toggle_button.setText("Hide setup" if visible else "Show setup")
        self._update_setup_summary()

    def _set_font_size(self, value: int) -> None:
        self.font_size = value
        self.root_widget.setStyleSheet(build_dock_style(value))
        if self.processing_dock is not None:
            self.processing_dock.set_font_size(value)
        self._refresh_task_list()

    def _update_setup_summary(self, *_args: Any) -> None:
        workbook = Path(self.audit_workbook_path.text()).name if self.audit_workbook_path.text() else "no workbook"
        bound_layers = sum(1 for combo in self.layer_combos.values() if combo.currentLayer() is not None)
        self.setup_summary_label.setText(f"Workbook: {workbook} | Layers: {bound_layers}/{len(self.layer_combos)}")

    def _task_item_height(self) -> int:
        return max(30, self.font_size * 3)

    def _browse_button(self, target: QLineEdit) -> QPushButton:
        button = QPushButton("...")

        def browse() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Select T11 workbook", "", "Excel (*.xlsx)")
            if path:
                target.setText(path)

        button.clicked.connect(browse)
        return button

    def _load_tasks(self) -> None:
        path = Path(self.audit_workbook_path.text()).expanduser()
        writable, reason = check_workbook_writable(path)
        if not writable:
            self.read_only = True
            self._set_message(f"Workbook is not writable; editing disabled: {reason}", error=True)
            return
        self.read_only = False
        try:
            self.tasks = load_review_tasks([path])
        except Exception as exc:
            self._set_message(f"Failed to load tasks: {exc}", error=True)
            return
        self.current_page = 0
        self.current_index = 0 if self.tasks else -1
        self._refresh_task_list()
        self._show_current_task()
        self._set_setup_visible(False)
        self._set_message(f"Loaded {len(self.tasks)} unique target tasks from {path.name}.")

    def _set_page_size(self, value: int) -> None:
        self.page_size = value
        self.current_page = 0
        self._refresh_task_list()

    def _turn_page(self, delta: int) -> None:
        max_page = max((len(self.tasks) - 1) // self.page_size, 0)
        self.current_page = min(max(self.current_page + delta, 0), max_page)
        self._refresh_task_list()

    def _refresh_task_list(self) -> None:
        self.task_list.blockSignals(True)
        self.task_list.clear()
        start = self.current_page * self.page_size
        end = min(start + self.page_size, len(self.tasks))
        for index in range(start, end):
            task = self.tasks[index]
            item = QListWidgetItem(self._format_task_item_text(task))
            item.setSizeHint(QSize(0, self._task_item_height()))
            item.setToolTip(self._format_task_tooltip(task))
            item.setBackground(QColor(TASK_STATUS_BACKGROUNDS.get(task.status, "#ffffff")))
            item.setData(Qt.UserRole, index)
            self.task_list.addItem(item)
        if 0 <= self.current_index < len(self.tasks) and start <= self.current_index < end:
            self.task_list.setCurrentRow(self.current_index - start)
        self.task_list.blockSignals(False)
        max_page = max((len(self.tasks) - 1) // self.page_size + 1, 0)
        self.page_label.setText(f"{self.current_page + 1 if self.tasks else 0} / {max_page}")

    def _format_task_item_text(self, task: ReviewTask) -> str:
        data_symbol = TASK_DATA_SYMBOLS.get(task.status, "+" if self._task_has_manual_data(task) else "-")
        return f"{data_symbol} {task.target_id} | {task.swsd_segment_id}"

    def _task_has_manual_data(self, task: ReviewTask) -> bool:
        return bool(task.manual_relation_type or task.selected_ids or task.comment)

    def _format_task_tooltip(self, task: ReviewTask) -> str:
        return (
            f"target_id: {task.target_id}\n"
            f"swsd_segment_id: {task.swsd_segment_id}\n"
            f"segment_length_m: {task.segment_length_m:.3f}\n"
            f"status: {TASK_STATUS_LABELS.get(task.status, task.status)}\n"
            f"has_manual_data: {'yes' if self._task_has_manual_data(task) else 'no'}\n"
            f"manual_relation_type: {task.manual_relation_type or '(empty)'}\n"
            f"selected_ids: {task.selected_ids or '(empty)'}\n"
            f"comment: {task.comment or '(empty)'}\n"
            f"workbook: {task.workbook_path.name}\n"
            f"sheet: {task.sheet_name}; row: {task.excel_row}"
        )

    def _task_row_changed(self, row: int) -> None:
        item = self.task_list.item(row)
        if item is None:
            return
        self._skip_next_clicked_index = int(item.data(Qt.UserRole))
        QTimer.singleShot(0, self._clear_skip_next_clicked_index)
        self._activate_task_item(item)

    def _task_item_clicked(self, item: QListWidgetItem) -> None:
        index = int(item.data(Qt.UserRole))
        if self._skip_next_clicked_index == index:
            self._skip_next_clicked_index = None
            return
        self._activate_task_item(item)

    def _activate_task_item(self, item: QListWidgetItem) -> None:
        self.current_index = int(item.data(Qt.UserRole))
        self._show_locate_and_prepare_selection()

    def _clear_skip_next_clicked_index(self) -> None:
        self._skip_next_clicked_index = None

    def _show_locate_and_prepare_selection(self) -> None:
        self._show_current_task()
        self._locate_current_task()
        self._highlight_current_ids()
        self._activate_layer_for_current_relation_type()

    def _show_current_task(self) -> None:
        processing = self.processing_dock
        if processing is None:
            return
        task = self._current_task()
        self._loading_ui = True
        try:
            if task is None:
                processing.segment_label.setText("")
                processing.target_label.setText("")
                processing.length_label.setText("")
                processing.status_label.setText("")
                processing.relation_type.setCurrentText("")
                processing.selected_ids.setText("")
                processing.comment.setPlainText("")
                return
            processing.segment_label.setText(task.swsd_segment_id)
            processing.target_label.setText(task.target_id)
            processing.length_label.setText(f"{task.segment_length_m:.3f}")
            processing.status_label.setText(TASK_STATUS_LABELS.get(task.status, task.status))
            processing.set_relation_type(task.manual_relation_type)
            processing.selected_ids.setText(task.selected_ids)
            processing.comment.setPlainText(task.comment)
        finally:
            self._loading_ui = False

    def _previous_task(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self.current_page = self.current_index // self.page_size
            self._refresh_task_list()
            self._show_locate_and_prepare_selection()

    def _next_task(self) -> None:
        if self.current_index + 1 < len(self.tasks):
            self.current_index += 1
            self.current_page = self.current_index // self.page_size
            self._refresh_task_list()
            self._show_locate_and_prepare_selection()

    def _queue_sync(self) -> None:
        task = self._current_task()
        processing = self.processing_dock
        if self._loading_ui or self.read_only or task is None or processing is None:
            return
        if self._processing_manual_values(processing) == self._task_manual_values(task):
            self._sync_timer.stop()
            return
        self._sync_timer.start(400)

    def _sync_current_task(self) -> None:
        task = self._current_task()
        processing = self.processing_dock
        if task is None or processing is None or self.read_only:
            return
        values = self._processing_manual_values(processing)
        if values == self._task_manual_values(task):
            return
        try:
            backup = task.workbook_path not in self._backed_up_workbooks
            update_manual_fields(
                workbook_path=task.workbook_path,
                excel_row=task.excel_row,
                values=values,
                backup=backup,
            )
            self._backed_up_workbooks.add(task.workbook_path)
            updated_task = replace(
                task,
                manual_relation_type=values["manual_relation_type"],
                selected_ids=values["selected_ids"],
                comment=values["comment"],
                status=task_status(values),
                raw={**task.raw, **values},
            )
            self.tasks[self.current_index] = updated_task
            processing.status_label.setText(TASK_STATUS_LABELS.get(updated_task.status, updated_task.status))
            self._refresh_current_task_item()
            self._set_message(f"Synced {task.target_id} to {task.workbook_path.name}:{task.excel_row}.")
        except Exception as exc:
            self.read_only = True
            self._set_message(f"Sync failed; editing disabled: {exc}", error=True)

    def _relation_type_changed(self, relation_type: str) -> None:
        if not self._loading_ui:
            self._activate_layer_for_relation_type(relation_type)
        self._queue_sync()

    def _processing_manual_values(self, processing: "T11RelationProcessingDock") -> dict[str, str]:
        return {
            "manual_relation_type": processing.relation_type.currentText().strip(),
            "selected_ids": processing.selected_ids.text().strip(),
            "comment": processing.comment.toPlainText().strip(),
        }

    def _task_manual_values(self, task: ReviewTask) -> dict[str, str]:
        return {
            "manual_relation_type": task.manual_relation_type.strip(),
            "selected_ids": task.selected_ids.strip(),
            "comment": task.comment.strip(),
        }

    def _refresh_current_task_item(self) -> None:
        task = self._current_task()
        if task is None:
            return
        row = self.current_index - self.current_page * self.page_size
        item = self.task_list.item(row)
        if item is None:
            return
        item.setText(self._format_task_item_text(task))
        item.setToolTip(self._format_task_tooltip(task))
        item.setBackground(QColor(TASK_STATUS_BACKGROUNDS.get(task.status, "#ffffff")))

    def _reload_after_sync(self, target_id: str) -> None:
        paths = sorted({task.workbook_path for task in self.tasks})
        self.tasks = load_review_tasks(paths)
        for index, task in enumerate(self.tasks):
            if task.target_id == target_id:
                self.current_index = index
                self.current_page = index // self.page_size
                break
        self._refresh_task_list()
        self._show_current_task()

    def _clear_current_fields(self) -> None:
        processing = self.processing_dock
        if processing is None:
            return
        processing.set_relation_type("")
        processing.selected_ids.setText("")
        processing.comment.setPlainText("")
        self._queue_sync()

    def _mark_null(self) -> None:
        self._apply_relation_type_button("no_valid_relation")

    def _mark_uncertain(self) -> None:
        self._apply_relation_type_button("uncertain")

    def _apply_relation_type_button(self, relation_type: str) -> None:
        processing = self.processing_dock
        if processing is None:
            return
        processing.set_relation_type(relation_type)
        if relation_type == "no_valid_relation":
            processing.selected_ids.setText("NULL")
        elif relation_type == "uncertain":
            processing.selected_ids.setText("")
        self._activate_layer_for_relation_type(relation_type)
        self._queue_sync()

    def _fill_from_selection(self) -> None:
        processing = self.processing_dock
        if processing is None:
            return
        relation_type = processing.relation_type.currentText()
        if relation_type in {"1v1_rcsd_junction", "1vN_rcsd_junction"}:
            layer = self._layer("rcsdnode")
            ids = extract_rcsdnode_selected_ids(layer.selectedFeatures() if layer is not None else [])
        elif relation_type in {"1v1_rcsd_road", "1vN_rcsd_road"}:
            layer = self._layer("rcsdroad")
            ids = extract_rcsdroad_selected_ids(layer.selectedFeatures() if layer is not None else [])
        else:
            self._set_message("Select a junction or road relation type before using QGIS selection.", error=True)
            return
        processing.selected_ids.setText(ids)
        self._queue_sync()

    def _locate_current_task(self) -> None:
        task = self._current_task()
        if task is None:
            return
        layer = self._layer("swsd_semantic_junction")
        features = self._matching_features(layer, {"id", "mainnodeid"}, task.target_id)
        if not features:
            layer = self._layer("swsd_segment")
            features = self._matching_features(layer, {"id", "swsd_segment_id"}, task.swsd_segment_id)
        self._select_and_zoom(layer, features, keep_active=True)

    def _highlight_current_ids(self) -> None:
        task = self._current_task()
        processing = self.processing_dock
        if task is None or processing is None:
            return
        ids = set(parse_selected_ids(processing.selected_ids.text() or task.selected_ids))
        relation_type = processing.relation_type.currentText() or task.manual_relation_type
        if not ids:
            self._activate_layer_for_relation_type(relation_type)
            return
        if relation_type in {"1v1_rcsd_junction", "1vN_rcsd_junction"}:
            layer = self._layer("rcsdnode")
            features = self._matching_features(layer, {"id", "mainnodeid"}, ids)
        elif relation_type in {"1v1_rcsd_road", "1vN_rcsd_road"}:
            layer = self._layer("rcsdroad")
            features = self._matching_features(layer, {"id"}, ids)
        else:
            return
        self._select_and_zoom(layer, features, zoom=False, keep_active=True)

    def _activate_layer_for_current_relation_type(self) -> None:
        processing = self.processing_dock
        task = self._current_task()
        if processing is None or task is None:
            return
        self._activate_layer_for_relation_type(processing.relation_type.currentText() or task.manual_relation_type)

    def _activate_layer_for_relation_type(self, relation_type: str) -> None:
        role = self._relation_layer_role(relation_type)
        if role is None:
            return
        layer = self._layer(role)
        if layer is not None:
            self.iface.setActiveLayer(layer)

    def _relation_layer_role(self, relation_type: str) -> str | None:
        if relation_type in {"1v1_rcsd_junction", "1vN_rcsd_junction"}:
            return "rcsdnode"
        if relation_type in {"1v1_rcsd_road", "1vN_rcsd_road"}:
            return "rcsdroad"
        return None

    def _matching_features(self, layer: Any, fields: set[str], values: str | set[str]) -> list[Any]:
        if layer is None:
            return []
        wanted = {values} if isinstance(values, str) else set(values)
        matches = []
        available = {field.name() for field in layer.fields()}
        checked_fields = fields & available
        for feature in layer.getFeatures():
            for field in checked_fields:
                try:
                    if str(feature[field]).strip() in wanted:
                        matches.append(feature)
                        break
                except Exception:
                    continue
        return matches

    def _select_and_zoom(
        self,
        layer: Any,
        features: list[Any],
        zoom: bool = True,
        keep_active: bool = False,
    ) -> None:
        if layer is None or not features:
            return
        feature_ids = [feature.id() for feature in features]
        current_layer = self.iface.activeLayer()
        layer.selectByIds(feature_ids)
        if zoom:
            extent = QgsRectangle()
            extent.setMinimal()
            centers = []
            for feature in features:
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    box = geom.boundingBox()
                    centers.append(box.center())
                    if not box.isEmpty():
                        extent.combineExtentWith(box)
            center = extent.center() if not extent.isEmpty() else self._average_center(centers)
            if center is not None:
                canvas = self.iface.mapCanvas()
                if not extent.isEmpty():
                    canvas.setExtent(extent)
                if hasattr(canvas, "setCenter"):
                    canvas.setCenter(center)
                if hasattr(canvas, "zoomScale"):
                    canvas.zoomScale(DEFAULT_LOCATE_SCALE)
                canvas.refresh()
        if keep_active:
            self.iface.setActiveLayer(layer)
        elif current_layer is not None:
            self.iface.setActiveLayer(current_layer)

    def _average_center(self, centers: list[Any]) -> QgsPointXY | None:
        if not centers:
            return None
        return QgsPointXY(
            sum(point.x() for point in centers) / len(centers),
            sum(point.y() for point in centers) / len(centers),
        )

    def _validate_layers(self) -> None:
        layers: dict[str, LayerDescriptor] = {}
        for role, combo in self.layer_combos.items():
            layer = combo.currentLayer()
            if layer is None:
                continue
            layers[role] = LayerDescriptor(
                name=layer.name(),
                source_path=layer.dataProvider().dataSourceUri(),
                crs_authid=layer.crs().authid(),
                fields=frozenset(field.name() for field in layer.fields()),
            )
        result = validate_layer_bindings(layers, expectations_for_bound_layers(layers, DEFAULT_LAYER_EXPECTATIONS))
        text = []
        if result.errors:
            text.append("Errors:\n" + "\n".join(result.errors))
        if result.warnings:
            text.append("Warnings:\n" + "\n".join(result.warnings))
        if not text:
            text.append("Layer bindings passed.")
        QMessageBox.information(self, "T11 layer validation", "\n\n".join(text))

    def _layer(self, role: str):
        combo = self.layer_combos.get(role)
        return combo.currentLayer() if combo is not None else None

    def _current_task(self) -> ReviewTask | None:
        if 0 <= self.current_index < len(self.tasks):
            return self.tasks[self.current_index]
        return None

    def _set_message(self, text: str, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet("color: #b00020;" if error else "")


class T11RelationProcessingDock(QDockWidget):
    def __init__(self, iface, task_dock: T11RelationReviewDock):
        super().__init__("T11 Relation Processing")
        self.iface = iface
        self.task_dock = task_dock
        self.font_size = getattr(task_dock, "font_size", DEFAULT_FONT_SIZE)
        self.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.root_widget = root
        root.setStyleSheet(build_dock_style(self.font_size))
        layout = QGridLayout(root)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        self.segment_label = QLabel("")
        self.target_label = QLabel("")
        self.length_label = QLabel("")
        self.status_label = QLabel("")
        for value_label in [self.segment_label, self.target_label, self.length_label, self.status_label]:
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setStyleSheet("font-weight: 600;")
        self.relation_type = QComboBox()
        self.relation_type.addItems(RELATION_TYPES)
        self.relation_type.setToolTip("Manual relation type written to manual_relation_type. The quick buttons below set the same field.")
        self.relation_type.currentTextChanged.connect(self._sync_relation_type_buttons)
        self.relation_type_buttons: dict[str, QPushButton] = {}
        relation_button_row = QHBoxLayout()
        relation_button_row.setSpacing(4)
        for label, value, tooltip in RELATION_TYPE_BUTTONS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, relation_type=value: self.task_dock._apply_relation_type_button(relation_type))
            self.relation_type_buttons[value] = button
            relation_button_row.addWidget(button)
        relation_button_row.addStretch(1)
        self.selected_ids = QLineEdit()
        self.selected_ids.setPlaceholderText("RCSDNode mainnodeid/id or RCSDRoad id; use | for multiple IDs")
        self.selected_ids.setToolTip("IDs that will be written to selected_ids. Use | between multiple IDs.")
        self.comment = QPlainTextEdit()
        self.comment.setMaximumBlockCount(8)
        self.comment.setPlaceholderText("Manual note")
        self.comment.setToolTip("Free-form manual comment written to comment.")
        self.comment.setFixedHeight(self._comment_height())

        layout.addWidget(QLabel("Target"), 0, 0)
        layout.addWidget(self.target_label, 0, 1)
        layout.addWidget(QLabel("Segment"), 0, 2)
        layout.addWidget(self.segment_label, 0, 3)
        layout.addWidget(QLabel("Length"), 0, 4)
        layout.addWidget(self.length_label, 0, 5)
        layout.addWidget(QLabel("State"), 0, 6)
        layout.addWidget(self.status_label, 0, 7)

        layout.addWidget(QLabel("Relation type"), 1, 0)
        layout.addWidget(self.relation_type, 1, 1, 1, 2)
        layout.addWidget(QLabel("Selected IDs"), 1, 3)
        layout.addWidget(self.selected_ids, 1, 4, 1, 2)
        layout.addWidget(QLabel("Comment"), 1, 6)
        layout.addWidget(self.comment, 1, 7, 2, 2)
        layout.addWidget(QLabel("Quick type"), 2, 0)
        layout.addLayout(relation_button_row, 2, 1, 1, 5)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        button_groups = [
            [
                ("Prev", self.task_dock._previous_task, "Move to the previous audit task."),
                ("Next", self.task_dock._next_task, "Move to the next audit task."),
            ],
            [
                ("Locate", self.task_dock._locate_current_task, "Zoom to and select the current SWSD junction or Segment."),
                ("Show IDs", self.task_dock._highlight_current_ids, "Highlight RCSDNode/RCSDRoad features already listed in Selected IDs."),
            ],
            [
                ("Use Selection", self.task_dock._fill_from_selection, "Read the current RCSDNode or RCSDRoad map selection into Selected IDs."),
                ("Clear", self.task_dock._clear_current_fields, "Clear relation type, selected IDs, and comment for this task."),
            ],
        ]
        for group_index, button_group in enumerate(button_groups):
            if group_index:
                actions.addSpacing(14)
            for text, callback, tooltip in button_group:
                button = QPushButton(text)
                button.setToolTip(tooltip)
                button.clicked.connect(callback)
                actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions, 3, 0, 1, 7)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setColumnStretch(4, 2)
        layout.setColumnStretch(7, 3)
        self.setWidget(root)
        self._sync_relation_type_buttons(self.relation_type.currentText())

    def set_font_size(self, value: int) -> None:
        self.font_size = value
        self.root_widget.setStyleSheet(build_dock_style(value))
        self.comment.setFixedHeight(self._comment_height())

    def _comment_height(self) -> int:
        return max(44, self.font_size * 5)

    def set_relation_type(self, relation_type: str) -> None:
        self.relation_type.setCurrentText(relation_type)
        self._sync_relation_type_buttons(relation_type)

    def _sync_relation_type_buttons(self, relation_type: str) -> None:
        for value, button in self.relation_type_buttons.items():
            button.setChecked(value == relation_type)
