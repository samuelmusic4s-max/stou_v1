from pathlib import Path
import re
import unicodedata

from PySide6.QtCore import QDir, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFontComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scia.features.document.chat_panel import ChatPanel
from scia.features.document.pipeline import extract_markdown_title
from scia.features.sources.ingest import allowed_extensions
from scia.shared.models import Lesson, Project, Source
from scia.shared.ui.theme import apply_slice_qss
from scia.shared.workers import ChatWorker, LessonWorker, retire_worker, stop_worker_safely


def _normalize_search(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip().strip(".")
    return cleaned or "guia"


class AddSourceChoiceDialog(QDialog):
    """Pregunta al usuario si desea añadir una fuente desde Subidos o subir un archivo por aparte."""

    def __init__(
        self,
        project_name: str,
        uploads_count: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("Añadir fuente al proyecto")
        self.setMinimumWidth(560)

        title = QLabel(f"Añadir fuente a «{project_name}»")
        title.setObjectName("sectionTitle")
        title.setWordWrap(True)

        desc = QLabel(
            "¿Deseas añadir una fuente que ya está en Subidos o subir un archivo por aparte?"
        )
        desc.setWordWrap(True)

        self.from_uploads_btn = QPushButton(f"Desde Subidos ({uploads_count})")
        if uploads_count > 0:
            self.from_uploads_btn.setObjectName("primaryButton")
        self.from_uploads_btn.setMinimumHeight(38)
        self.from_uploads_btn.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.from_uploads_btn.clicked.connect(self._choose_uploads)

        self.external_btn = QPushButton("Subir archivo por aparte")
        if uploads_count == 0:
            self.external_btn.setObjectName("primaryButton")
        else:
            self.external_btn.setObjectName("ghostButton")
        self.external_btn.setMinimumHeight(38)
        self.external_btn.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.external_btn.clicked.connect(self._choose_external)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("ghostButton")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.cancel_btn.clicked.connect(self.reject)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addWidget(self.from_uploads_btn)
        actions.addWidget(self.external_btn)
        actions.addStretch()
        actions.addWidget(self.cancel_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(actions)
        self.adjustSize()

    def _choose_uploads(self):
        self.choice = "uploads"
        self.accept()

    def _choose_external(self):
        self.choice = "external"
        self.accept()


class SelectUploadedSourcesDialog(QDialog):
    """Permite seleccionar una o varias fuentes ya cargadas en Subidos para añadirlas a un proyecto."""

    def __init__(
        self,
        uploaded_sources: list[Source],
        existing_sources: list[Source] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar fuentes desde Subidos")
        self.setMinimumSize(620, 440)
        self._uploaded_sources = list(uploaded_sources)
        self._existing_names = {s.name.lower() for s in (existing_sources or [])}
        self._source_by_id = {s.id: s for s in self._uploaded_sources}
        self._checked_ids: set[str] = set()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar en Subidos...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._refresh_list)
        self.search_input.returnPressed.connect(self._on_search_submitted)

        self.tree = QTreeWidget()
        self.tree.setObjectName("dialogTree")
        self.tree.setHeaderLabels(["Archivo", "Tipo", "Fecha", "Estado"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setMinimumSectionSize(84)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self.add_btn = QPushButton("Añadir seleccionadas")
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.setMinimumHeight(36)
        self.add_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.add_btn.clicked.connect(self._confirm)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("ghostButton")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.add_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(
            QLabel("Marca las fuentes de Subidos que deseas añadir al proyecto:")
        )
        layout.addWidget(self.search_input)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)

        self._refresh_list()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        src_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not src_id:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._checked_ids.add(src_id)
        else:
            self._checked_ids.discard(src_id)

    def _on_search_submitted(self):
        self._refresh_list()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.tree.setCurrentItem(item)
                self.tree.setFocus()
                break

    def _refresh_list(self):
        query = _normalize_search(self.search_input.text())
        self.tree.blockSignals(True)
        self.tree.clear()
        first_enabled: QTreeWidgetItem | None = None
        for source in self._uploaded_sources:
            if (
                query
                and query not in _normalize_search(source.name)
                and query not in _normalize_search(source.source_type.value)
            ):
                continue
            already_added = source.name.lower() in self._existing_names
            status_text = "Ya en el proyecto" if already_added else "Disponible"
            item = QTreeWidgetItem(
                [
                    source.name,
                    source.source_type.value.upper(),
                    source.published_date.isoformat(),
                    status_text,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, source.id)
            item.setSizeHint(0, QSize(0, 38))
            if already_added:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if source.id in self._checked_ids
                    else Qt.CheckState.Unchecked,
                )
                if first_enabled is None:
                    first_enabled = item
            self.tree.addTopLevelItem(item)
        if first_enabled is not None:
            self.tree.setCurrentItem(first_enabled)
        self.tree.blockSignals(False)

    def _checked_source_ids(self) -> list[str]:
        return [s.id for s in self._uploaded_sources if s.id in self._checked_ids]

    def _on_item_double_clicked(self, item: QTreeWidgetItem):
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        item.setCheckState(0, Qt.CheckState.Checked)
        self.accept()

    def _confirm(self):
        if not self.selected_sources():
            QMessageBox.information(
                self,
                "Sin selección",
                "Selecciona al menos una fuente disponible para añadir al proyecto.",
            )
            return
        self.accept()

    def selected_sources(self) -> list[Source]:
        ids = self._checked_source_ids()
        if not ids:
            current = self.tree.currentItem()
            if current is not None and (current.flags() & Qt.ItemFlag.ItemIsEnabled):
                src_id = current.data(0, Qt.ItemDataRole.UserRole)
                if src_id:
                    ids = [src_id]
        return [self._source_by_id[i] for i in ids if i in self._source_by_id]


class ProjectSourcesDialog(QDialog):
    add_source_requested = Signal()

    def __init__(self, sources: list[Source], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Fuentes del proyecto")
        self.setMinimumSize(540, 400)

        self.tree = QTreeWidget()
        self.tree.setObjectName("dialogTree")
        self.tree.setHeaderLabels(["Archivo", "Tipo", "Fecha"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.set_sources(sources)

        self.upload_btn = QPushButton("+ Añadir fuente")
        self.upload_btn.setObjectName("primaryButton")
        self.upload_btn.setMinimumHeight(36)
        self.upload_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.upload_btn.clicked.connect(self.add_source_requested.emit)

        self.close_btn = QPushButton("Cerrar")
        self.close_btn.setMinimumHeight(36)
        self.close_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.upload_btn)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(QLabel("Material indexado disponible para la IA:"))
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)

    def set_sources(self, sources: list[Source]):
        self.tree.clear()
        for source in sources:
            self.tree.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        source.name,
                        source.source_type.value,
                        source.published_date.isoformat(),
                    ]
                )
            )
        self.tree.resizeColumnToContents(0)


class DocumentPage(QWidget):
    lessons_changed = Signal(list)
    foreign_lesson_generated = Signal(str, object)
    document_font_changed = Signal(QFont)
    loading_changed = Signal(bool, str)
    source_upload_requested = Signal(str, str)
    sources_from_uploads_requested = Signal(str, list)
    project_selected = Signal(str)
    project_created = Signal(object)
    project_deleted = Signal(str)

    def __init__(self, project_id: str = "default", parent: QWidget | None = None):
        super().__init__(parent)
        self.project_id = project_id
        self._doc_font = QFont("Inter", 10)
        self._projects: list[Project] = []
        self._uploaded_sources: list[Source] = []
        self._sources: list[Source] = []
        self._lessons: list[Lesson] = []
        self._current_lesson: Lesson | None = None
        self._chat_history: list[tuple[str, str]] = []
        self._current_reply_parts: list[str] = []
        self._lesson_worker: LessonWorker | None = None
        self._chat_worker: ChatWorker | None = None
        self._sources_dialog: ProjectSourcesDialog | None = None

        # Dos vistas: 0 = Lista de proyectos, 1 = Proyecto abierto (Chat / Guías)
        self.view_stack = QStackedLayout(self)
        self.view_stack.addWidget(self._build_projects_list_view())
        self.view_stack.addWidget(self._build_workspace_view())
        self.view_stack.setCurrentIndex(0)
        apply_slice_qss(self, __file__)

    def _build_projects_list_view(self) -> QWidget:
        view = QWidget()

        title = QLabel("Proyectos")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Haz doble clic en un proyecto para abrir su chat y sus guías de estudio."
        )
        subtitle.setObjectName("pageSubtitle")

        self.project_search = QLineEdit()
        self.project_search.setPlaceholderText("Buscar proyecto...")
        self.project_search.setClearButtonEnabled(True)
        self.project_search.textChanged.connect(self._refresh_projects_tree)
        self.project_search.returnPressed.connect(self._on_project_search_submitted)

        self.new_project_btn = QPushButton("+ Nuevo proyecto")
        self.new_project_btn.setObjectName("primaryButton")
        self.new_project_btn.clicked.connect(self._create_project)

        self.add_source_project_btn = QPushButton("+ Añadir fuente")
        self.add_source_project_btn.setObjectName("ghostButton")
        self.add_source_project_btn.clicked.connect(self._add_source_to_selected_project)

        self.open_project_btn = QPushButton("Abrir")
        self.open_project_btn.setObjectName("ghostButton")
        self.open_project_btn.clicked.connect(self._open_selected_project)

        self.delete_project_btn = QPushButton("Eliminar")
        self.delete_project_btn.setObjectName("dangerButton")
        self.delete_project_btn.clicked.connect(self._delete_selected_project)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        top_bar.addWidget(self.project_search, 1)
        top_bar.addWidget(self.new_project_btn)
        top_bar.addWidget(self.add_source_project_btn)
        top_bar.addWidget(self.open_project_btn)
        top_bar.addWidget(self.delete_project_btn)

        self.projects_tree = QTreeWidget()
        self.projects_tree.setObjectName("projectsTree")
        self.projects_tree.setHeaderLabels(
            ["Proyecto", "Fuentes", "Guías", "Tareas", "Creado"]
        )
        self.projects_tree.setRootIsDecorated(False)
        self.projects_tree.setAlternatingRowColors(True)
        self.projects_tree.setUniformRowHeights(True)
        header = self.projects_tree.header()
        header.setMinimumSectionSize(92)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_tree.itemDoubleClicked.connect(self._on_project_double_clicked)

        layout = QVBoxLayout(view)
        layout.setContentsMargins(40, 30, 30, 30)
        layout.setSpacing(18)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(top_bar)
        layout.addWidget(self.projects_tree, 1)
        return view

    def _build_workspace_view(self) -> QWidget:
        view = QWidget()

        self.back_to_projects_btn = QPushButton("← Proyectos")
        self.back_to_projects_btn.setObjectName("ghostButton")
        self.back_to_projects_btn.clicked.connect(self.show_projects_list)

        self.title_text = QLabel("Proyecto")
        self.title_text.setObjectName("pageTitle")
        self.title_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.subtitle_text = QLabel(
            "Conversa con tus fuentes y genera guías de estudio."
        )
        self.subtitle_text.setObjectName("pageSubtitle")
        self.subtitle_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        title_row.addWidget(self.back_to_projects_btn)
        title_row.addWidget(self.title_text)
        title_row.addStretch()

        self.title_layout = QVBoxLayout()
        self.title_layout.setSpacing(6)
        self.title_layout.addLayout(title_row)
        self.title_layout.addWidget(self.subtitle_text)

        # Botones de sección + QStackedLayout
        self.chat_section_btn = QPushButton("Chat")
        self.chat_section_btn.clicked.connect(lambda: self._switch_section(0))

        self.guides_section_btn = QPushButton("Guías generadas")
        self.guides_section_btn.clicked.connect(lambda: self._switch_section(1))

        self.workspace_add_source_btn = QPushButton("+ Añadir fuente")
        self.workspace_add_source_btn.setObjectName("ghostButton")
        self.workspace_add_source_btn.clicked.connect(
            lambda: self._start_add_source_flow(self.project_id)
        )

        self.section_bar = QHBoxLayout()
        self.section_bar.setSpacing(10)
        self.section_bar.addWidget(self.chat_section_btn)
        self.section_bar.addWidget(self.guides_section_btn)
        self.section_bar.addStretch()
        self.section_bar.addWidget(self.workspace_add_source_btn)

        self.sections_stack = QStackedLayout()
        self.sections_stack.addWidget(self._build_chat_section())
        self.sections_stack.addWidget(self._build_guides_section())

        layout = QVBoxLayout(view)
        layout.addLayout(self.title_layout)
        layout.addLayout(self.section_bar)
        layout.addLayout(self.sections_stack, 1)
        layout.setContentsMargins(40, 30, 30, 30)
        layout.setSpacing(18)

        self._switch_section(0)
        return view

    def set_projects(self, projects: list[Project], current_project_id: str = ""):
        self._projects = list(projects)
        if current_project_id:
            self.project_id = current_project_id
        self._refresh_projects_tree()

    def set_uploaded_sources(self, sources: list[Source]):
        self._uploaded_sources = list(sources)

    def show_projects_list(self):
        self._refresh_projects_tree()
        self.view_stack.setCurrentIndex(0)

    def open_project(self, project: Project):
        self.title_text.setText(project.name)
        self.load_data(project.id, project.sources, project.lessons)
        self.view_stack.setCurrentIndex(1)

    def _on_project_search_submitted(self):
        self._refresh_projects_tree()
        if self.projects_tree.topLevelItemCount() > 0:
            if self.projects_tree.currentItem() is None:
                self.projects_tree.setCurrentItem(self.projects_tree.topLevelItem(0))
            self.projects_tree.setFocus()

    def _refresh_projects_tree(self):
        query = _normalize_search(self.project_search.text())
        self.projects_tree.clear()
        matched_current: QTreeWidgetItem | None = None
        for project in self._projects:
            if query and query not in _normalize_search(project.name):
                continue
            item = QTreeWidgetItem(
                [
                    project.name,
                    str(len(project.sources)),
                    str(len(project.lessons)),
                    str(len(project.tasks)),
                    project.created_at.strftime("%Y-%m-%d"),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, project.id)
            item.setSizeHint(0, QSize(0, 50))
            for col in (1, 2, 3, 4):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
            self.projects_tree.addTopLevelItem(item)
            if project.id == self.project_id:
                matched_current = item

        if matched_current is not None:
            self.projects_tree.setCurrentItem(matched_current)
        elif self.projects_tree.topLevelItemCount() > 0:
            self.projects_tree.setCurrentItem(self.projects_tree.topLevelItem(0))

    def _selected_project_id(self) -> str | None:
        item = self.projects_tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_project_double_clicked(self, item: QTreeWidgetItem):
        project_id = item.data(0, Qt.ItemDataRole.UserRole)
        if project_id:
            self.project_selected.emit(project_id)

    def _open_selected_project(self):
        project_id = self._selected_project_id()
        if not project_id:
            QMessageBox.information(
                self,
                "Selecciona un proyecto",
                "Selecciona primero un proyecto de la lista para abrirlo.",
            )
            return
        self.project_selected.emit(project_id)

    def _add_source_to_selected_project(self):
        project_id = self._selected_project_id()
        if not project_id:
            QMessageBox.information(
                self,
                "Selecciona un proyecto",
                "Selecciona primero un proyecto de la lista para añadirle una fuente.",
            )
            return
        self._start_add_source_flow(project_id)

    def _find_project(self, project_id: str) -> Project | None:
        for proj in self._projects:
            if proj.id == project_id:
                return proj
        return None

    def _pick_external_source_file(self, project_id: str):
        exts = " ".join(f"*{ext}" for ext in allowed_extensions())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Subir fuente al proyecto",
            QDir.homePath(),
            f"Documentos ({exts})",
        )
        if file_path:
            self.source_upload_requested.emit(project_id, file_path)

    def _start_add_source_flow(self, project_id: str):
        project = self._find_project(project_id)
        project_name = project.name if project is not None else self.title_text.text()
        existing_sources = project.sources if project is not None else self._sources

        choice_dialog = AddSourceChoiceDialog(
            project_name=project_name,
            uploads_count=len(self._uploaded_sources),
            parent=self,
        )
        if choice_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if choice_dialog.choice == "uploads":
            if not self._uploaded_sources:
                answer = QMessageBox.question(
                    self,
                    "Sin fuentes en Subidos",
                    "No hay fuentes disponibles en Subidos todavía.\n\n"
                    "¿Deseas subir un archivo por aparte desde tu equipo?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self._pick_external_source_file(project_id)
                return

            picker = SelectUploadedSourcesDialog(
                uploaded_sources=self._uploaded_sources,
                existing_sources=existing_sources,
                parent=self,
            )
            if picker.exec() == QDialog.DialogCode.Accepted:
                selected = picker.selected_sources()
                if selected:
                    self.sources_from_uploads_requested.emit(project_id, selected)
        elif choice_dialog.choice == "external":
            self._pick_external_source_file(project_id)

    def _create_project(self):
        name, ok = QInputDialog.getText(
            self,
            "Nuevo proyecto",
            "Nombre del proyecto:",
        )
        if ok and name.strip():
            project = Project(name=name.strip())
            self.project_created.emit(project)

    def _delete_selected_project(self):
        project_id = self._selected_project_id()
        if not project_id:
            QMessageBox.information(
                self,
                "Selecciona un proyecto",
                "Selecciona primero un proyecto de la lista para eliminarlo.",
            )
            return
        if len(self._projects) <= 1:
            QMessageBox.information(
                self,
                "Proyecto único",
                "Debe quedar al menos un proyecto activo.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Eliminar proyecto",
            "¿Seguro que deseas eliminar este proyecto?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.project_deleted.emit(project_id)

    def _switch_section(self, index: int):
        self.sections_stack.setCurrentIndex(index)
        self.chat_section_btn.setObjectName("primaryButton" if index == 0 else "")
        self.guides_section_btn.setObjectName("primaryButton" if index == 1 else "")
        for btn in (self.chat_section_btn, self.guides_section_btn):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _build_chat_section(self) -> QWidget:
        self.chat_panel = ChatPanel(self)
        self.chat_panel.message_sent.connect(self._send_chat_message)
        self.chat_panel.sources_requested.connect(self._open_sources_dialog)
        self.chat_panel.clear_requested.connect(self._chat_history.clear)
        return self.chat_panel

    def _build_guides_section(self) -> QWidget:
        section = QWidget()
        self._editing_md = False

        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText(
            "Tema o enfoque para generar guía (opcional)..."
        )
        self.topic_input.setClearButtonEnabled(True)
        self.topic_input.returnPressed.connect(self._generate_guide)

        self.font_selector = QFontComboBox()
        self.font_selector.currentFontChanged.connect(self._on_font_combo_changed)

        self.generate_guide_btn = QPushButton("Generar guía")
        self.generate_guide_btn.setObjectName("primaryButton")
        self.generate_guide_btn.clicked.connect(self._generate_guide)

        self.new_guide_btn = QPushButton("Nueva")
        self.new_guide_btn.clicked.connect(self._new_blank_guide)

        self.toggle_edit_btn = QPushButton("Editar .md")
        self.toggle_edit_btn.clicked.connect(self._toggle_edit_mode)

        self.save_guide_btn = QPushButton("Guardar")
        self.save_guide_btn.clicked.connect(self._save_current_guide)

        self.export_md_btn = QPushButton("Exportar .md")
        self.export_md_btn.clicked.connect(self._export_markdown)

        self.delete_guide_btn = QPushButton("Eliminar")
        self.delete_guide_btn.setObjectName("dangerButton")
        self.delete_guide_btn.clicked.connect(self._delete_current_guide)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        top_bar.addWidget(self.topic_input, 2)
        top_bar.addWidget(self.font_selector, 1)
        top_bar.addWidget(self.generate_guide_btn)
        top_bar.addWidget(self.new_guide_btn)
        top_bar.addWidget(self.toggle_edit_btn)
        top_bar.addWidget(self.save_guide_btn)
        top_bar.addWidget(self.export_md_btn)
        top_bar.addWidget(self.delete_guide_btn)

        self.guides_tree = QTreeWidget()
        self.guides_tree.setHeaderLabels(["Guías (.md)"])
        self.guides_tree.setMinimumWidth(220)
        self.guides_tree.itemClicked.connect(self._on_guide_clicked)

        # Visor Markdown (índice 0) y editor .md editable (índice 1)
        self.lesson_viewer = QTextEdit()
        self.lesson_viewer.setReadOnly(True)
        self.lesson_viewer.setPlaceholderText(
            "Genera una guía o haz clic en una de la lista para leerla aquí..."
        )

        self.lesson_editor = QPlainTextEdit()
        self.lesson_editor.setPlaceholderText(
            "# Título de tu guía\n\nEscribe o edita aquí en formato Markdown (.md)..."
        )

        self.doc_container = QWidget()
        self.doc_stack = QStackedLayout(self.doc_container)
        self.doc_stack.setContentsMargins(0, 0, 0, 0)
        self.doc_stack.addWidget(self.lesson_viewer)
        self.doc_stack.addWidget(self.lesson_editor)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.guides_tree)
        splitter.addWidget(self.doc_container)
        splitter.setSizes([240, 790])

        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(top_bar)
        layout.addWidget(splitter, 1)
        return section

    def load_data(
        self, project_id: str, sources: list[Source], lessons: list[Lesson]
    ):
        project_switched = self.project_id != project_id
        self.project_id = project_id
        self._sources = list(sources)
        self._lessons = list(lessons)
        self._current_lesson = None
        self.lesson_viewer.clear()
        self.lesson_editor.clear()
        if project_switched:
            if self._chat_worker is not None and self._chat_worker.isRunning():
                stop_worker_safely(self._chat_worker, timeout_ms=500)
                self._chat_worker = None
            self.chat_panel.set_busy(False)
            self._chat_history.clear()
            self._current_reply_parts.clear()
            self.chat_panel.clear_messages()
        self.chat_panel.set_sources_count(len(self._sources))
        self._refresh_guides_tree()

    def set_sources(self, sources: list[Source]):
        self._sources = list(sources)
        self.chat_panel.set_sources_count(len(self._sources))
        if self._sources_dialog is not None:
            self._sources_dialog.set_sources(self._sources)

    def get_lessons(self) -> list[Lesson]:
        return list(self._lessons)

    def _on_font_combo_changed(self, combo_font: QFont):
        merged = QFont(combo_font.family(), max(8, self._doc_font.pointSize()))
        self.set_document_font(merged)
        self.document_font_changed.emit(merged)

    def set_document_font(self, font: QFont):
        self._doc_font = QFont(font)
        self.lesson_viewer.setFont(font)
        self.lesson_editor.setFont(font)
        self.chat_panel.set_chat_font(font)
        self.font_selector.blockSignals(True)
        self.font_selector.setCurrentFont(font)
        self.font_selector.blockSignals(False)

    def show_markdown(self, markdown_text: str):
        self.lesson_viewer.setMarkdown(markdown_text)
        self.lesson_editor.setPlainText(markdown_text)

    def _new_blank_guide(self):
        self._current_lesson = None
        self.guides_tree.clearSelection()
        self.lesson_viewer.clear()
        self.lesson_editor.clear()
        if not self._editing_md:
            self._toggle_edit_mode()
        self.lesson_editor.setFocus()

    def _delete_current_guide(self):
        if self._current_lesson is None:
            return
        target_id = self._current_lesson.id
        self._lessons = [l for l in self._lessons if l.id != target_id]
        self._current_lesson = None
        self.lesson_viewer.clear()
        self.lesson_editor.clear()
        self._refresh_guides_tree()
        self.lessons_changed.emit(self.get_lessons())
        self.loading_changed.emit(False, "Guía eliminada")

    def _toggle_edit_mode(self):
        self._editing_md = not self._editing_md
        if self._editing_md:
            self.doc_stack.setCurrentIndex(1)
            self.toggle_edit_btn.setText("Vista previa")
        else:
            self.lesson_viewer.setMarkdown(self.lesson_editor.toPlainText())
            self.doc_stack.setCurrentIndex(0)
            self.toggle_edit_btn.setText("Editar .md")

    def _save_current_guide(self):
        md_text = self.lesson_editor.toPlainText()
        if not md_text.strip():
            return

        fallback = self._current_lesson.title if self._current_lesson else "Nueva guía"
        title = extract_markdown_title(md_text, fallback)

        if self._current_lesson is None:
            self._current_lesson = Lesson(title=title, markdown=md_text)
            self._lessons.append(self._current_lesson)
        else:
            self._current_lesson.title = title
            self._current_lesson.markdown = md_text

        self.lesson_viewer.setMarkdown(md_text)
        self._refresh_guides_tree()
        self.lessons_changed.emit(self.get_lessons())
        self.loading_changed.emit(False, f"Guía «{title}» guardada")

    def _export_markdown(self):
        md_text = self.lesson_editor.toPlainText()
        if not md_text.strip():
            QMessageBox.information(
                self, "Sin contenido", "No hay contenido Markdown para exportar."
            )
            return

        safe_stem = (
            _sanitize_filename(self._current_lesson.title)
            if self._current_lesson
            else "guia"
        )
        default_name = f"{safe_stem}.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar guía como Markdown",
            str(Path(QDir.homePath()) / default_name),
            "Markdown (*.md)",
        )
        if file_path:
            try:
                Path(file_path).write_text(md_text, encoding="utf-8")
                self.loading_changed.emit(False, f"Exportado en {Path(file_path).name}")
            except OSError as exc:
                QMessageBox.warning(
                    self, "Error al exportar", f"No se pudo guardar el archivo:\n{exc}"
                )

    def _open_sources_dialog(self):
        self._sources_dialog = ProjectSourcesDialog(self._sources, parent=self)
        self._sources_dialog.add_source_requested.connect(
            lambda: self._start_add_source_flow(self.project_id)
        )
        self._sources_dialog.exec()
        self._sources_dialog = None

    def _refresh_guides_tree(self):
        self.guides_tree.clear()
        for lesson in self._lessons:
            item = QTreeWidgetItem([lesson.title])
            item.setData(0, Qt.ItemDataRole.UserRole, lesson.id)
            self.guides_tree.addTopLevelItem(item)

    def _on_guide_clicked(self, item: QTreeWidgetItem):
        lesson_id = item.data(0, Qt.ItemDataRole.UserRole)
        for lesson in self._lessons:
            if lesson.id == lesson_id:
                self._current_lesson = lesson
                self.show_markdown(lesson.markdown)
                break

    def _generate_guide(self):
        if self._lesson_worker is not None and self._lesson_worker.isRunning():
            return
        topic = self.topic_input.text().strip()
        self.generate_guide_btn.setEnabled(False)
        self.loading_changed.emit(True, "Generando guía con IA...")

        self._lesson_worker = LessonWorker(
            project_id=self.project_id,
            topic=topic,
            sources=self._sources,
            parent=self,
        )
        self._lesson_worker.finished.connect(self._on_guide_generated)
        self._lesson_worker.error.connect(self._on_guide_error)
        self._lesson_worker.start()

    def _cleanup_lesson_worker(self):
        if self._lesson_worker is not None:
            worker = self._lesson_worker
            self._lesson_worker = None
            retire_worker(worker)

    def _on_guide_generated(self, lesson: Lesson):
        worker = self._lesson_worker
        origin_project_id = worker.project_id if worker is not None else self.project_id
        self._cleanup_lesson_worker()
        self.generate_guide_btn.setEnabled(True)

        if origin_project_id != self.project_id:
            self.foreign_lesson_generated.emit(origin_project_id, lesson)
            self.loading_changed.emit(
                False, f"Guía «{lesson.title}» guardada en su proyecto"
            )
            return

        self._lessons.append(lesson)
        self._refresh_guides_tree()
        self.topic_input.clear()
        if self._current_lesson is None and not self.lesson_editor.toPlainText().strip():
            self._current_lesson = lesson
            self.show_markdown(lesson.markdown)
        self.loading_changed.emit(
            False, f"Guía «{lesson.title}» lista"
        )
        self.lessons_changed.emit(self.get_lessons())

    def _on_guide_error(self, message: str):
        self._cleanup_lesson_worker()
        self.generate_guide_btn.setEnabled(True)
        self.loading_changed.emit(False, "No se pudo generar la guía")
        QMessageBox.warning(self, "Error al generar guía", message)

    def _send_chat_message(self, question: str):
        if self._chat_worker is not None and self._chat_worker.isRunning():
            return
        self._chat_history.append(("Estudiante", question))
        self._current_reply_parts = []
        self.chat_panel.set_busy(True)
        self.chat_panel.start_assistant_reply()

        editor_md = self.lesson_editor.toPlainText().strip()
        lesson_md = editor_md or (
            self._current_lesson.markdown if self._current_lesson else ""
        )
        self._chat_worker = ChatWorker(
            project_id=self.project_id,
            question=question,
            current_lesson_md=lesson_md,
            history=self._chat_history[:-1],
            parent=self,
        )
        self._chat_worker.token.connect(self._on_chat_token)
        self._chat_worker.finished.connect(self._on_chat_finished)
        self._chat_worker.error.connect(self._on_chat_error)
        self._chat_worker.start()

    def _cleanup_chat_worker(self):
        if self._chat_worker is not None:
            worker = self._chat_worker
            self._chat_worker = None
            retire_worker(worker)

    def _pop_pending_user_turn(self):
        if self._chat_history and self._chat_history[-1][0] == "Estudiante":
            self._chat_history.pop()

    def _on_chat_token(self, token: str):
        self._current_reply_parts.append(token)
        self.chat_panel.append_token(token)

    def _on_chat_finished(self):
        worker = self._chat_worker
        self._cleanup_chat_worker()
        if worker is not None and worker.had_error and not worker.was_cancelled:
            return
        if worker is not None and worker.was_cancelled:
            partial = "".join(self._current_reply_parts).strip()
            if partial:
                self._chat_history.append(("IA", partial))
            else:
                self._pop_pending_user_turn()
                self.chat_panel.set_current_reply_text("(Respuesta cancelada)")
            self.chat_panel.finish_assistant_reply()
            self.chat_panel.set_busy(False)
            return

        full_reply = "".join(self._current_reply_parts).strip()
        if full_reply:
            self._chat_history.append(("IA", full_reply))
        else:
            self._pop_pending_user_turn()
            self.chat_panel.set_current_reply_text("(Sin respuesta del modelo)")
        self.chat_panel.finish_assistant_reply()
        self.chat_panel.set_busy(False)

    def _on_chat_error(self, message: str):
        self._cleanup_chat_worker()
        self._pop_pending_user_turn()
        self.chat_panel.append_token(f"\n[Error: {message}]")
        self.chat_panel.finish_assistant_reply()
        self.chat_panel.set_busy(False)

    def shutdown_workers(self):
        stop_worker_safely(self._lesson_worker, timeout_ms=2000)
        self._lesson_worker = None
        stop_worker_safely(self._chat_worker, timeout_ms=2000)
        self._chat_worker = None
