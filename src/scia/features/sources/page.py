from pathlib import Path
import unicodedata

from PySide6.QtCore import QDate, QDir, QFileInfo, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFileDialog,
    QFileIconProvider,
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from scia.features.sources.chunks_repo import delete_chunks_by_source
from scia.features.sources.ingest import (
    allowed_extensions,
    detect_source_type,
    remove_source_file,
)
from scia.features.sources.sources_repo import UNASSIGNED_PROJECT_ID
from scia.shared.models import Source, SourceType
from scia.shared.ui import resources_rc  # noqa: F401
from scia.shared.ui.theme import PALETTE, apply_slice_qss
from scia.shared.workers import IngestWorker, retire_worker, stop_worker_safely


def _normalize_search(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _format_size(path: Path) -> str:
    if not path.is_file():
        return "—"
    size = path.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


_ICON_RESOURCES = {
    ".pdf": ":/icons/file_pdf",
    ".md": ":/icons/file_md",
    ".txt": ":/icons/file_txt",
}
_GENERIC_ICON_RESOURCE = ":/icons/file_generic"


def get_file_icon(suffix: str) -> QIcon:
    return QIcon(_ICON_RESOURCES.get(suffix.lower(), _GENERIC_ICON_RESOURCE))


class SourceFileIconProvider(QFileIconProvider):
    def __init__(self):
        super().__init__()
        self._cache: dict[str, QIcon] = {
            ext: QIcon(res) for ext, res in _ICON_RESOURCES.items()
        }
        self._generic = QIcon(_GENERIC_ICON_RESOURCE)

    def icon(self, arg):
        if isinstance(arg, QFileInfo) and arg.isFile():
            ext = f".{arg.suffix().lower()}" if arg.suffix() else ""
            return self._cache.get(ext, self._generic)
        return super().icon(arg)


class SourcePage(QWidget):
    sources_changed = Signal(list)
    foreign_source_ingested = Signal(str, object)

    def __init__(
        self, project_id: str = UNASSIGNED_PROJECT_ID, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.project_id = project_id
        self._sources: list[Source] = []
        self._visible_sources: list[Source] = []
        self._ingest_worker: IngestWorker | None = None
        self._progress_dialog: QProgressDialog | None = None

        self.title = QLabel("Subidos")
        self.title.setObjectName("pageTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.subtitle = QLabel(
            "Todo tu material disponible para añadir a tus proyectos."
        )
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.title_layout = QVBoxLayout()
        self.title_layout.addWidget(self.title)
        self.title_layout.addWidget(self.subtitle)

        self.title_layout_container = QHBoxLayout()
        self.title_layout_container.addLayout(self.title_layout)
        self.title_layout_container.addStretch()

        self._icon_provider = SourceFileIconProvider()
        self._type_icons = {
            SourceType.Pdf: get_file_icon(".pdf"),
            SourceType.Md: get_file_icon(".md"),
            SourceType.Txt: get_file_icon(".txt"),
        }
        self._generic_icon = get_file_icon("")

        name_filters = [f"*{ext}" for ext in allowed_extensions()]
        self.files_model = QFileSystemModel(self)
        self.files_model.setIconProvider(self._icon_provider)
        self.files_model.setRootPath(QDir.homePath())
        self.files_model.setNameFilters(name_filters)
        self.files_model.setNameFilterDisables(False)

        self.files_navigator = QTreeView()
        self.files_navigator.setObjectName("sourcesTree")
        self.files_navigator.setModel(self.files_model)
        self.files_navigator.setRootIndex(self.files_model.index(QDir.homePath()))
        self.files_navigator.setIconSize(QSize(20, 20))
        self.files_navigator.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.files_navigator.hideColumn(col)
        self.files_navigator.setMaximumWidth(300)
        self.files_navigator.doubleClicked.connect(self._on_tree_double_clicked)

        self.search_source = QLineEdit()
        self.search_source.setPlaceholderText("Busca tu material...")
        self.search_source.setClearButtonEnabled(True)
        self.search_source.textChanged.connect(self._refresh_table)
        self.search_source.returnPressed.connect(self._on_search_submitted)

        self.filters_button = QDateEdit(QDate.currentDate())
        self.filters_button.setCalendarPopup(True)
        self.filters_button.setToolTip("Fecha de publicación para el nuevo material")

        self.add_source = QPushButton("Agregar nuevo material")
        self.add_source.setObjectName("primaryButton")
        self.add_source.clicked.connect(self._add_source_clicked)

        self.delete_source = QPushButton("Eliminar")
        self.delete_source.setObjectName("dangerButton")
        self.delete_source.clicked.connect(self._delete_selected)

        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.addWidget(self.search_source, 2)
        self.buttons_layout.addWidget(self.filters_button)
        self.buttons_layout.addWidget(self.add_source)
        self.buttons_layout.addWidget(self.delete_source)
        self.buttons_layout.setSpacing(14)

        self.sources_model = QStandardItemModel(0, 5)
        self.sources_model.setHorizontalHeaderLabels(
            ["Nombre", "Tipo", "Tamaño", "Estado", "Fecha"]
        )

        self.sources_table = QTableView()
        self.sources_table.setObjectName("sourcesTable")
        self.sources_table.setModel(self.sources_model)
        self.sources_table.setIconSize(QSize(22, 22))
        self.sources_table.setShowGrid(False)
        self.sources_table.setAlternatingRowColors(True)
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.verticalHeader().setDefaultSectionSize(38)
        self.sources_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.sources_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.sources_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.sources_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.sources_table.doubleClicked.connect(self._on_table_double_clicked)

        self.right_section_layout = QVBoxLayout()
        self.right_section_layout.setSpacing(16)
        self.right_section_layout.addLayout(self.buttons_layout)
        self.right_section_layout.addWidget(self.sources_table, 1)

        self.hero_layout = QHBoxLayout()
        self.hero_layout.setSpacing(20)
        self.hero_layout.addWidget(self.files_navigator, 1)
        self.hero_layout.addLayout(self.right_section_layout, 3)

        self.root_layout = QVBoxLayout()
        self.root_layout.addLayout(self.title_layout_container)
        self.root_layout.addLayout(self.hero_layout, 1)
        self.root_layout.setContentsMargins(40, 30, 30, 30)
        self.root_layout.setSpacing(25)

        self.setLayout(self.root_layout)
        apply_slice_qss(self, __file__)

    def load_sources(self, project_id: str, sources: list[Source]):
        self.project_id = project_id
        self._sources = list(sources)
        self._refresh_table()

    def get_sources(self) -> list[Source]:
        return list(self._sources)

    def _on_tree_double_clicked(self, index):
        path = self.files_model.filePath(index)
        if Path(path).is_file():
            self.ingest_file(path)

    def _on_table_double_clicked(self, index):
        if index.isValid() and index.row() < len(self._visible_sources):
            source = self._visible_sources[index.row()]
            self.ingest_file(source.path)

    def _on_search_submitted(self):
        self._refresh_table()
        if self._visible_sources:
            self.sources_table.selectRow(0)
            self.sources_table.setFocus()

    def _refresh_table(self):
        query = _normalize_search(self.search_source.text())
        self._visible_sources = []
        self.sources_model.removeRows(0, self.sources_model.rowCount())

        for source in self._sources:
            if (
                query
                and query not in _normalize_search(source.name)
                and query not in _normalize_search(source.source_type.value)
                and query not in source.published_date.isoformat()
            ):
                continue
            self._visible_sources.append(source)
            file_path = Path(source.path)
            exists = file_path.is_file()

            icon = self._type_icons.get(source.source_type, self._generic_icon)
            name_item = QStandardItem(icon, source.name)
            name_item.setToolTip(source.path)

            type_item = QStandardItem(source.source_type.value.upper())
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            size_item = QStandardItem(_format_size(file_path))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            status_item = QStandardItem("Indexado" if exists else "No encontrado")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(
                QColor(PALETTE["success"] if exists else PALETTE["danger"])
            )

            date_item = QStandardItem(source.published_date.isoformat())
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.sources_model.appendRow(
                [name_item, type_item, size_item, status_item, date_item]
            )

        if self._visible_sources:
            self.sources_table.selectRow(0)

    def _add_source_clicked(self):
        # Si hay un archivo seleccionado en el árbol lo usa; si no, abre diálogo de archivos
        selected_path = ""
        tree_idx = self.files_navigator.currentIndex()
        if tree_idx.isValid():
            candidate = self.files_model.filePath(tree_idx)
            if Path(candidate).is_file():
                selected_path = candidate

        if not selected_path:
            exts = " ".join(f"*{ext}" for ext in allowed_extensions())
            selected_path, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar material",
                QDir.homePath(),
                f"Documentos ({exts})",
            )

        if not selected_path:
            return

        self.ingest_file(selected_path)

    def ingest_file(self, file_path: str, target_project_id: str | None = None):
        dialog_parent = self.window() if self.window() is not None else self
        effective_project_id = (
            self.project_id if target_project_id is None else target_project_id
        )
        if self._ingest_worker is not None and self._ingest_worker.isRunning():
            QMessageBox.information(
                dialog_parent,
                "Indexación en curso",
                "Espera a que termine la indexación actual antes de subir otro archivo.",
            )
            return

        path = Path(file_path)
        if not path.is_file():
            QMessageBox.warning(
                dialog_parent, "Archivo no encontrado", f"No existe el archivo: {path}"
            )
            return

        try:
            detect_source_type(path)
        except ValueError as exc:
            QMessageBox.warning(dialog_parent, "Formato no soportado", str(exc))
            return

        answer = QMessageBox.question(
            dialog_parent,
            "Subir archivo",
            f"Se realizará una copia local de «{path.name}» y se extraerá su texto "
            "para usarlo en el chat y las guías.\n\n¿Deseas continuar?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return

        progress = QProgressDialog(
            f"Copiando {path.name} y extrayendo texto...", "Cancelar", 0, 0, dialog_parent
        )
        progress.setWindowTitle("Procesando archivo")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        self._progress_dialog = progress

        worker = IngestWorker(
            project_id=effective_project_id,
            file_path=path,
            published_date=self.filters_button.date().toPython(),
            parent=self,
        )
        self._ingest_worker = worker
        progress.canceled.connect(worker.requestInterruption)
        worker.step_changed.connect(self._on_ingest_step)
        worker.finished.connect(self._on_ingest_finished)
        worker.cancelled.connect(self._on_ingest_cancelled)
        worker.error.connect(self._on_ingest_error)
        worker.start()

    def _close_ingest_progress(self):
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None
        if self._ingest_worker is not None:
            worker = self._ingest_worker
            self._ingest_worker = None
            retire_worker(worker)

    def _on_ingest_step(self, step: int, message: str):
        if self._progress_dialog is not None:
            self._progress_dialog.setLabelText(message)

    def _on_ingest_finished(self, source: Source):
        self._close_ingest_progress()
        # Si el usuario cambió de proyecto mientras se indexaba, enrutar al proyecto original
        if source.project_id != self.project_id:
            self.foreign_source_ingested.emit(source.project_id, source)
            return

        # Si ya existía una fuente con la misma ruta, la reemplazamos para no duplicarla
        existing_idx = next(
            (i for i, s in enumerate(self._sources) if s.path == source.path),
            None,
        )
        if existing_idx is not None:
            delete_chunks_by_source(self._sources[existing_idx].id)
            self._sources[existing_idx] = source
        else:
            self._sources.append(source)
        self._refresh_table()
        self.sources_changed.emit(self.get_sources())

    def _on_ingest_cancelled(self):
        self._close_ingest_progress()

    def _on_ingest_error(self, message: str):
        self._close_ingest_progress()
        dialog_parent = self.window() if self.window() is not None else self
        QMessageBox.warning(dialog_parent, "Error al indexar", message)

    def shutdown_workers(self):
        worker = self._ingest_worker
        self._ingest_worker = None
        stop_worker_safely(worker, timeout_ms=2000)
        self._close_ingest_progress()
        self.files_navigator.setModel(None)
        self._default_icon_provider = QFileIconProvider()
        self.files_model.setIconProvider(self._default_icon_provider)

    def _delete_selected(self):
        idx = self.sources_table.currentIndex()
        if not idx.isValid() or idx.row() >= len(self._visible_sources):
            QMessageBox.information(
                self,
                "Selecciona un material",
                "Selecciona primero un archivo de la tabla para eliminarlo.",
            )
            return
        source = self._visible_sources[idx.row()]
        delete_chunks_by_source(source.id)
        remove_source_file(source.path, source.project_id)
        self._sources = [s for s in self._sources if s.id != source.id]
        self._refresh_table()
        self.sources_changed.emit(self.get_sources())
