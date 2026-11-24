import unicodedata

from PySide6.QtCore import QDateTime, QTime, Qt, Signal
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from scia.shared.models import Task, TaskStatus
from scia.shared.ui.theme import PALETTE, apply_slice_qss

STATUS_LABELS = {
    TaskStatus.Pending: "Pendiente",
    TaskStatus.In_Progress: "En progreso",
    TaskStatus.Done: "Hecha",
}

STATUS_ORDER = [TaskStatus.Pending, TaskStatus.In_Progress, TaskStatus.Done]

STATUS_COLORS = {
    TaskStatus.Pending: PALETTE["warning"],
    TaskStatus.In_Progress: PALETTE["primary_light"],
    TaskStatus.Done: PALETTE["success"],
}


def _normalize_search(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _format_estimated_minutes(minutes: int) -> str:
    mins = max(0, int(minutes))
    hours, rem = divmod(mins, 60)
    return f"{hours:02d}:{rem:02d} h"


class TaskDialog(QDialog):
    def __init__(self, task: Task | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Editar tarea" if task else "Nueva tarea")
        self.setMinimumWidth(420)

        self.title_input = QLineEdit(task.title if task else "")
        self.title_input.setPlaceholderText("Ej: Repasar apuntes de bases de datos")

        self.desc_input = QPlainTextEdit(task.description if task else "")
        self.desc_input.setPlaceholderText("Descripción corta (opcional)...")
        self.desc_input.setMaximumHeight(90)

        self.status_input = QComboBox()
        for status in STATUS_ORDER:
            self.status_input.addItem(STATUS_LABELS[status], status)
        if task:
            idx = self.status_input.findData(task.status)
            if idx >= 0:
                self.status_input.setCurrentIndex(idx)

        self.estimated_time_input = QTimeEdit()
        self.estimated_time_input.setDisplayFormat("HH:mm")
        est_mins = max(0, min(23 * 60 + 59, task.estimated_minutes if task else 30))
        self.estimated_time_input.setTime(QTime(est_mins // 60, est_mins % 60))

        self.due_input = QDateTimeEdit()
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        if task:
            self.due_input.setDateTime(QDateTime(task.due_at))
        else:
            self.due_input.setDateTime(QDateTime.currentDateTime().addDays(1))

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Título:", self.title_input)
        form.addRow("Descripción:", self.desc_input)
        form.addRow("Estado:", self.status_input)
        form.addRow("Tiempo estimado (HH:mm):", self.estimated_time_input)
        form.addRow("Fecha límite:", self.due_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate_and_accept(self):
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Campo requerido", "Escribe un título para la tarea.")
            return
        self.accept()

    def build_task(self, existing: Task | None = None) -> Task:
        title = self.title_input.text().strip()
        description = self.desc_input.toPlainText().strip()
        status = TaskStatus(self.status_input.currentData())
        est_time = self.estimated_time_input.time()
        estimated_minutes = est_time.hour() * 60 + est_time.minute()
        due_at = self.due_input.dateTime().toPython()

        if existing is not None:
            existing.title = title
            existing.description = description
            existing.status = status
            existing.estimated_minutes = estimated_minutes
            existing.due_at = due_at
            return existing

        return Task(
            title=title,
            description=description,
            status=status,
            due_at=due_at,
            estimated_minutes=estimated_minutes,
        )


class TaskPage(QWidget):
    tasks_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._tasks: list[Task] = []
        self._visible_tasks: list[Task] = []

        self.title_text = QLabel("Tareas")
        self.title_text.setObjectName("pageTitle")
        self.title_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.subtitle_text = QLabel("Organiza tus tareas a tu ritmo.")
        self.subtitle_text.setObjectName("pageSubtitle")
        self.subtitle_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.title_layout = QVBoxLayout()
        self.title_layout.addWidget(self.title_text)
        self.title_layout.addWidget(self.subtitle_text)

        # Barra superior: buscador, filtro por estado y botón agregar
        self.search_task_text = QLineEdit()
        self.search_task_text.setPlaceholderText("Busca tu tarea...")
        self.search_task_text.setClearButtonEnabled(True)
        self.search_task_text.textChanged.connect(self._refresh_table)
        self.search_task_text.returnPressed.connect(self._on_search_submitted)

        self.filter_status = QComboBox()
        self.filter_status.addItem("Todos", None)
        for status in STATUS_ORDER:
            self.filter_status.addItem(STATUS_LABELS[status], status)
        self.filter_status.currentIndexChanged.connect(self._refresh_table)

        self.add_task = QPushButton("Agregar nueva tarea")
        self.add_task.setObjectName("primaryButton")
        self.add_task.clicked.connect(self._add_task)

        self.navigations_buttons = QHBoxLayout()
        self.navigations_buttons.addWidget(self.search_task_text, 3)
        self.navigations_buttons.addWidget(self.filter_status, 1)
        self.navigations_buttons.addWidget(self.add_task)

        # Tabla principal (QTableView + QStandardItemModel)
        self.tasks_model = QStandardItemModel(0, 5)
        self.tasks_model.setHorizontalHeaderLabels(
            ["Título", "Descripción", "Estado", "Tiempo est.", "Fecha límite"]
        )

        self.tasks_table = QTableView()
        self.tasks_table.setObjectName("tasksTable")
        self.tasks_table.setModel(self.tasks_model)
        self.tasks_table.setShowGrid(False)
        self.tasks_table.setAlternatingRowColors(True)
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.verticalHeader().setDefaultSectionSize(44)
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tasks_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tasks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.tasks_table.horizontalHeader()
        header.setMinimumSectionSize(96)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.setColumnWidth(0, 210)
        self.tasks_table.doubleClicked.connect(self._edit_selected)

        # Barra inferior de acciones sobre la tarea seleccionada
        self.edit_button = QPushButton("Editar")
        self.edit_button.clicked.connect(self._edit_selected)

        self.toggle_status_button = QPushButton("Cambiar estado")
        self.toggle_status_button.clicked.connect(self._cycle_status)

        self.delete_button = QPushButton("Eliminar")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_selected)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.addWidget(self.edit_button)
        self.actions_layout.addWidget(self.toggle_status_button)
        self.actions_layout.addStretch()
        self.actions_layout.addWidget(self.delete_button)

        self.root_layout = QVBoxLayout()
        self.root_layout.addLayout(self.title_layout)
        self.root_layout.addLayout(self.navigations_buttons)
        self.root_layout.addWidget(self.tasks_table, 1)
        self.root_layout.addLayout(self.actions_layout)
        self.root_layout.setContentsMargins(40, 30, 30, 30)
        self.root_layout.setSpacing(20)

        self.setLayout(self.root_layout)
        apply_slice_qss(self, __file__)

    def load_tasks(self, tasks: list[Task]):
        self._tasks = list(tasks)
        self._refresh_table()

    def get_tasks(self) -> list[Task]:
        return list(self._tasks)

    def _selected_task(self) -> Task | None:
        index = self.tasks_table.currentIndex()
        if not index.isValid() or index.row() >= len(self._visible_tasks):
            return None
        return self._visible_tasks[index.row()]

    def _on_search_submitted(self):
        self._refresh_table()
        if self._visible_tasks:
            self.tasks_table.selectRow(0)
            self.tasks_table.setFocus()

    def _refresh_table(self):
        selected = self._selected_task()
        selected_id = selected.id if selected is not None else None

        query = _normalize_search(self.search_task_text.text())
        status_filter = self.filter_status.currentData()

        self._visible_tasks = []
        self.tasks_model.removeRows(0, self.tasks_model.rowCount())

        restore_row: int | None = None
        for task in self._tasks:
            task_status = TaskStatus(task.status)
            if status_filter is not None and task_status != TaskStatus(status_filter):
                continue
            status_label = STATUS_LABELS[task_status]
            if (
                query
                and query not in _normalize_search(task.title)
                and query not in _normalize_search(task.description)
                and query not in _normalize_search(status_label)
            ):
                continue

            row_idx = len(self._visible_tasks)
            self._visible_tasks.append(task)
            if selected_id is not None and task.id == selected_id:
                restore_row = row_idx

            title_item = QStandardItem(task.title)
            title_font = QFont(title_item.font())
            title_font.setWeight(QFont.Weight.DemiBold)
            title_item.setFont(title_font)

            desc_item = QStandardItem(task.description)
            desc_item.setForeground(QColor(PALETTE["text_secondary"]))

            status_item = QStandardItem(status_label)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor(STATUS_COLORS.get(task_status, PALETTE["text"])))
            status_font = QFont(status_item.font())
            status_font.setWeight(QFont.Weight.DemiBold)
            status_item.setFont(status_font)

            est_item = QStandardItem(_format_estimated_minutes(task.estimated_minutes))
            est_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            due_item = QStandardItem(task.due_at.strftime("%Y-%m-%d %H:%M"))
            due_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            due_item.setForeground(QColor(PALETTE["text_secondary"]))

            row_items = [title_item, desc_item, status_item, est_item, due_item]
            self.tasks_model.appendRow(row_items)

        self.tasks_table.resizeColumnToContents(2)
        self.tasks_table.resizeColumnToContents(3)
        self.tasks_table.resizeColumnToContents(4)
        if restore_row is not None:
            self.tasks_table.selectRow(restore_row)
        elif self._visible_tasks:
            self.tasks_table.selectRow(0)

    def _notify_changed(self):
        self._refresh_table()
        self.tasks_changed.emit(self.get_tasks())

    def _add_task(self):
        dialog = TaskDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._tasks.append(dialog.build_task())
            self._notify_changed()

    def _edit_selected(self):
        task = self._selected_task()
        if task is None:
            return
        dialog = TaskDialog(task=task, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.build_task(existing=task)
            self._notify_changed()

    def _cycle_status(self):
        task = self._selected_task()
        if task is None:
            return
        current_status = TaskStatus(task.status)
        next_idx = (STATUS_ORDER.index(current_status) + 1) % len(STATUS_ORDER)
        task.status = STATUS_ORDER[next_idx]
        self._notify_changed()

    def _delete_selected(self):
        task = self._selected_task()
        if task is None:
            return
        self._tasks = [t for t in self._tasks if t.id != task.id]
        self._notify_changed()
