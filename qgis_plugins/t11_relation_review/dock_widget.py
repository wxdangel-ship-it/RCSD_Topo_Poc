from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import QTimer, Qt  # type: ignore
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMapLayerProxyModel, QgsProject, QgsRectangle  # type: ignore
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
    validate_layer_bindings,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.task_index import ReviewTask, load_review_tasks


RELATION_TYPES = [
    "",
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
    "no_valid_relation",
    "uncertain",
]


class T11RelationReviewDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("T11 Relation Review")
        self.iface = iface
        self.tasks: list[ReviewTask] = []
        self.current_index = -1
        self.page_size = 50
        self.current_page = 0
        self.read_only = False
        self._loading_ui = False
        self._backed_up_workbooks: set[Path] = set()
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_current_task)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setStyleSheet(
            """
            QWidget {
                font-size: 13pt;
            }
            QGroupBox {
                font-size: 13pt;
                font-weight: 600;
                margin-top: 12px;
                padding-top: 10px;
            }
            QLabel, QComboBox, QLineEdit, QListWidget, QPlainTextEdit, QSpinBox {
                font-size: 13pt;
            }
            QPushButton {
                font-size: 13pt;
                min-height: 30px;
                padding: 4px 8px;
            }
            QLineEdit, QComboBox, QSpinBox {
                min-height: 30px;
            }
            QListWidget::item {
                min-height: 28px;
            }
            """
        )
        layout = QVBoxLayout(root)

        workbook_box = QGroupBox("Workbooks")
        workbook_layout = QGridLayout(workbook_box)
        self.all_evidence_path = QLineEdit()
        self.no_evidence_path = QLineEdit()
        workbook_layout.addWidget(QLabel("All evidence gaps"), 0, 0)
        workbook_layout.addWidget(self.all_evidence_path, 0, 1)
        workbook_layout.addWidget(self._browse_button(self.all_evidence_path), 0, 2)
        workbook_layout.addWidget(QLabel("No evidence gaps"), 1, 0)
        workbook_layout.addWidget(self.no_evidence_path, 1, 1)
        workbook_layout.addWidget(self._browse_button(self.no_evidence_path), 1, 2)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_tasks)
        workbook_layout.addWidget(load_button, 2, 0, 1, 3)
        layout.addWidget(workbook_box)

        layer_box = QGroupBox("Layer Binding")
        layer_layout = QFormLayout(layer_box)
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
            self.layer_combos[role] = combo
            layer_layout.addRow(label, combo)
        validate_button = QPushButton("Validate layers")
        validate_button.clicked.connect(self._validate_layers)
        layer_layout.addRow(validate_button)
        layout.addWidget(layer_box)

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
        self.task_list.currentRowChanged.connect(self._task_row_changed)
        layout.addWidget(self.task_list, stretch=1)

        detail_box = QGroupBox("Current Task")
        detail_layout = QFormLayout(detail_box)
        self.segment_label = QLabel("")
        self.target_label = QLabel("")
        self.length_label = QLabel("")
        self.status_label = QLabel("")
        self.relation_type = QComboBox()
        self.relation_type.addItems(RELATION_TYPES)
        self.selected_ids = QLineEdit()
        self.comment = QPlainTextEdit()
        self.comment.setMaximumBlockCount(8)
        detail_layout.addRow("swsd_segment_id", self.segment_label)
        detail_layout.addRow("target_id", self.target_label)
        detail_layout.addRow("Segment length", self.length_label)
        detail_layout.addRow("Status", self.status_label)
        detail_layout.addRow("manual_relation_type", self.relation_type)
        detail_layout.addRow("selected_ids", self.selected_ids)
        detail_layout.addRow("comment", self.comment)
        layout.addWidget(detail_box)

        actions = QGridLayout()
        buttons = [
            ("Prev task", self._previous_task),
            ("Next task", self._next_task),
            ("Locate", self._locate_current_task),
            ("Highlight IDs", self._highlight_current_ids),
            ("Use selection", self._fill_from_selection),
            ("Clear", self._clear_current_fields),
            ("Mark NULL", self._mark_null),
            ("Uncertain", self._mark_uncertain),
        ]
        for index, (text, callback) in enumerate(buttons):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.setWidget(root)

        self.relation_type.currentTextChanged.connect(self._queue_sync)
        self.selected_ids.editingFinished.connect(self._queue_sync)
        self.comment.textChanged.connect(self._queue_sync)

    def _browse_button(self, target: QLineEdit) -> QPushButton:
        button = QPushButton("...")

        def browse() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Select T11 workbook", "", "Excel (*.xlsx)")
            if path:
                target.setText(path)

        button.clicked.connect(browse)
        return button

    def _load_tasks(self) -> None:
        paths = {
            "all_evidence_relation_gaps": Path(self.all_evidence_path.text()).expanduser(),
            "no_evidence_relation_gaps": Path(self.no_evidence_path.text()).expanduser(),
        }
        for path in paths.values():
            writable, reason = check_workbook_writable(path)
            if not writable:
                self.read_only = True
                self._set_message(f"Workbook is not writable; editing disabled: {reason}", error=True)
                return
        self.read_only = False
        try:
            self.tasks = load_review_tasks(paths)
        except Exception as exc:
            self._set_message(f"Failed to load tasks: {exc}", error=True)
            return
        self.current_page = 0
        self.current_index = 0 if self.tasks else -1
        self._refresh_task_list()
        self._show_current_task()
        self._set_message(f"Loaded {len(self.tasks)} unique target tasks.")

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
            item = QListWidgetItem(
                f"[{task.status}] {task.target_id} | {task.swsd_segment_id} | {task.segment_length_m:.1f}m"
            )
            item.setData(Qt.UserRole, index)
            self.task_list.addItem(item)
        if 0 <= self.current_index < len(self.tasks) and start <= self.current_index < end:
            self.task_list.setCurrentRow(self.current_index - start)
        self.task_list.blockSignals(False)
        max_page = max((len(self.tasks) - 1) // self.page_size + 1, 0)
        self.page_label.setText(f"{self.current_page + 1 if self.tasks else 0} / {max_page}")

    def _task_row_changed(self, row: int) -> None:
        item = self.task_list.item(row)
        if item is None:
            return
        self.current_index = int(item.data(Qt.UserRole))
        self._show_current_task()
        self._locate_current_task()
        self._highlight_current_ids()

    def _show_current_task(self) -> None:
        task = self._current_task()
        self._loading_ui = True
        try:
            if task is None:
                self.segment_label.setText("")
                self.target_label.setText("")
                self.length_label.setText("")
                self.status_label.setText("")
                self.relation_type.setCurrentText("")
                self.selected_ids.setText("")
                self.comment.setPlainText("")
                return
            self.segment_label.setText(task.swsd_segment_id)
            self.target_label.setText(task.target_id)
            self.length_label.setText(f"{task.segment_length_m:.3f}")
            self.status_label.setText(task.status)
            self.relation_type.setCurrentText(task.manual_relation_type)
            self.selected_ids.setText(task.selected_ids)
            self.comment.setPlainText(task.comment)
        finally:
            self._loading_ui = False

    def _previous_task(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self.current_page = self.current_index // self.page_size
            self._refresh_task_list()
            self._show_current_task()

    def _next_task(self) -> None:
        if self.current_index + 1 < len(self.tasks):
            self.current_index += 1
            self.current_page = self.current_index // self.page_size
            self._refresh_task_list()
            self._show_current_task()

    def _queue_sync(self) -> None:
        if self._loading_ui or self.read_only or self._current_task() is None:
            return
        self._sync_timer.start(400)

    def _sync_current_task(self) -> None:
        task = self._current_task()
        if task is None or self.read_only:
            return
        try:
            backup = task.workbook_path not in self._backed_up_workbooks
            update_manual_fields(
                workbook_path=task.workbook_path,
                excel_row=task.excel_row,
                values={
                    "manual_relation_type": self.relation_type.currentText(),
                    "selected_ids": self.selected_ids.text(),
                    "comment": self.comment.toPlainText(),
                },
                backup=backup,
            )
            self._backed_up_workbooks.add(task.workbook_path)
            self._reload_after_sync(task.target_id)
            self._set_message(f"Synced {task.target_id} to {task.workbook_path.name}:{task.excel_row}.")
        except Exception as exc:
            self.read_only = True
            self._set_message(f"Sync failed; editing disabled: {exc}", error=True)

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
        self.relation_type.setCurrentText("")
        self.selected_ids.setText("")
        self.comment.setPlainText("")
        self._queue_sync()

    def _mark_null(self) -> None:
        self.relation_type.setCurrentText("no_valid_relation")
        self.selected_ids.setText("NULL")
        self._queue_sync()

    def _mark_uncertain(self) -> None:
        self.relation_type.setCurrentText("uncertain")
        self.selected_ids.setText("")
        self._queue_sync()

    def _fill_from_selection(self) -> None:
        relation_type = self.relation_type.currentText()
        if relation_type in {"1v1_rcsd_junction", "1vN_rcsd_junction"}:
            layer = self._layer("rcsdnode")
            ids = extract_rcsdnode_selected_ids(layer.selectedFeatures() if layer is not None else [])
        elif relation_type in {"1v1_rcsd_road", "1vN_rcsd_road"}:
            layer = self._layer("rcsdroad")
            ids = extract_rcsdroad_selected_ids(layer.selectedFeatures() if layer is not None else [])
        else:
            self._set_message("Select a junction or road relation type before using QGIS selection.", error=True)
            return
        self.selected_ids.setText(ids)
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
        self._select_and_zoom(layer, features)

    def _highlight_current_ids(self) -> None:
        task = self._current_task()
        if task is None:
            return
        ids = set(parse_selected_ids(self.selected_ids.text() or task.selected_ids))
        if not ids:
            return
        relation_type = self.relation_type.currentText() or task.manual_relation_type
        if relation_type in {"1v1_rcsd_junction", "1vN_rcsd_junction"}:
            layer = self._layer("rcsdnode")
            features = self._matching_features(layer, {"id", "mainnodeid"}, ids)
        elif relation_type in {"1v1_rcsd_road", "1vN_rcsd_road"}:
            layer = self._layer("rcsdroad")
            features = self._matching_features(layer, {"id"}, ids)
        else:
            return
        self._select_and_zoom(layer, features, zoom=False)

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

    def _select_and_zoom(self, layer: Any, features: list[Any], zoom: bool = True) -> None:
        if layer is None or not features:
            return
        feature_ids = [feature.id() for feature in features]
        current_layer = self.iface.activeLayer()
        layer.selectByIds(feature_ids)
        if zoom:
            extent = QgsRectangle()
            extent.setMinimal()
            for feature in features:
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    extent.combineExtentWith(geom.boundingBox())
            if not extent.isEmpty():
                self.iface.mapCanvas().setExtent(extent)
                self.iface.mapCanvas().refresh()
        if current_layer is not None:
            self.iface.setActiveLayer(current_layer)

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
        result = validate_layer_bindings(layers, DEFAULT_LAYER_EXPECTATIONS)
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
