from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QFontDialog,
    QLabel,
    QMainWindow,
    QProgressBar,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from scia.features.document.page import DocumentPage
from scia.features.home.page import HomePage
from scia.features.settings.page import SettingsPage
from scia.features.sources.chunks_repo import (
    clone_chunks_for_project,
    delete_chunks_by_project,
    delete_chunks_by_source,
)
from scia.features.sources.ingest import copy_source_file, remove_project_uploads
from scia.features.sources.page import SourcePage
from scia.features.sources.sources_repo import (
    UNASSIGNED_PROJECT_ID,
    delete_uploaded_source,
    load_uploaded_sources,
    save_uploaded_source,
)
from scia.features.tasks.page import TaskPage
from scia.shared.config import ModelRole, settings
from scia.shared.models import Lesson, Project, Source, TaskStatus
from scia.shared.projects_repo import (
    delete_project,
    load_all_projects,
    load_latest_project,
    save_project,
)
from scia.shared.ui.sidebar import Sidebar


PAGE_NAMES = {
    "home": "Inicio",
    "tasks": "Tareas",
    "document": "Proyectos",
    "sources": "Subidos",
    "settings": "Configuración",
}


class SciaGui(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("SC.IA — Curador de fuentes con IA")
        self.setMinimumSize(1024, 680)
        self._doc_font = QFont("Inter", 10)
        self._is_ephemeral_default = False

        # Cargar proyectos desde MongoDB o crear uno nuevo
        latest = load_latest_project()
        all_projects = load_all_projects() if latest is not None else []
        if all_projects:
            self.projects: list[Project] = all_projects
        elif latest is not None:
            self.projects = [latest]
        else:
            self.projects = [Project(name="Proyecto principal")]
            self._is_ephemeral_default = True
        self.project = self.projects[0]
        self.uploaded_sources: list[Source] = load_uploaded_sources()

        self._build_menu()
        self._build_statusbar()

        # Barra lateral izquierda
        self.sidebar = Sidebar(self)
        self.sidebar.page_selected.connect(self.navigate_to)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.sidebar)

        # Páginas principales
        self.home_page = HomePage(self)
        self.home_page.new_task_requested.connect(lambda: self.navigate_to("tasks"))
        self.home_page.new_lesson_requested.connect(
            lambda: self.navigate_to("document")
        )
        self.home_page.open_sources_requested.connect(
            lambda: self.navigate_to("sources")
        )
        self.home_page.open_settings_requested.connect(
            lambda: self.navigate_to("settings")
        )

        self.tasks_page = TaskPage(self)
        self.tasks_page.tasks_changed.connect(self._on_tasks_changed)

        self.sources_page = SourcePage(UNASSIGNED_PROJECT_ID, self)
        self.sources_page.sources_changed.connect(self._on_uploaded_sources_changed)
        self.sources_page.foreign_source_ingested.connect(self._on_foreign_source_ingested)

        self.document_page = DocumentPage(self.project.id, self)
        self.document_page.lessons_changed.connect(self._on_lessons_changed)
        self.document_page.foreign_lesson_generated.connect(self._on_foreign_lesson_generated)
        self.document_page.document_font_changed.connect(self._on_document_font_combo_changed)
        self.document_page.loading_changed.connect(self.set_loading)
        self.document_page.source_upload_requested.connect(
            self._on_project_external_source_requested
        )
        self.document_page.sources_from_uploads_requested.connect(
            self._on_project_sources_from_uploads_requested
        )
        self.document_page.project_selected.connect(self._on_project_selected)
        self.document_page.project_created.connect(self._on_project_created)
        self.document_page.project_deleted.connect(self._on_project_deleted)

        self.settings_page = SettingsPage(self)
        self.settings_page.font_requested.connect(self._choose_font)
        self.settings_page.font_reset_requested.connect(self._reset_font)
        self.settings_page.settings_changed.connect(self._update_status)
        self.settings_page.db_settings_changed.connect(self._on_db_settings_changed)
        self.settings_page.set_current_font(self._doc_font)

        self.pages: dict[str, QWidget] = {
            "home": self.home_page,
            "tasks": self.tasks_page,
            "document": self.document_page,
            "sources": self.sources_page,
            "settings": self.settings_page,
        }

        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)

        # Cargar datos iniciales en todas las vistas
        self._sync_views()
        self.navigate_to("home")

    def _build_menu(self):
        self.menuBar().setNativeMenuBar(False)
        file_menu = self.menuBar().addMenu("Archivo")
        file_menu.addAction("Salir", self.close)

        view_menu = self.menuBar().addMenu("Ver")
        act_font = QAction("Fuente del documento...", self)
        act_font.triggered.connect(self._choose_font)
        view_menu.addAction(act_font)

    def _build_statusbar(self):
        self.page_label = QLabel(self)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setVisible(False)

        self.info_label = QLabel(self)
        self.model_label = QLabel(self)

        status_bar = QStatusBar(self)
        status_bar.addWidget(self.page_label)
        status_bar.addPermanentWidget(self.progress_bar)
        status_bar.addPermanentWidget(self.info_label)
        status_bar.addPermanentWidget(self.model_label)
        self.setStatusBar(status_bar)

    def _update_status(self):
        pending = sum(1 for t in self.project.tasks if t.status != TaskStatus.Done)
        sources = len(self.project.sources)
        lessons = len(self.project.lessons)
        self.info_label.setText(
            f"{sources} fuentes · {lessons} lecciones · {pending} pendientes"
        )

        gen = settings.get_role(ModelRole.Generator)
        has_model = bool(gen and gen.model)
        model_name = gen.model if has_model else "Sin modelo"
        self.model_label.setText(f"IA: {model_name}")
        self.model_label.setObjectName(
            "statusSuccess" if has_model else "statusWarning"
        )
        self.model_label.style().unpolish(self.model_label)
        self.model_label.style().polish(self.model_label)
        self.home_page.set_summary(
            len(self.uploaded_sources), lessons, pending, has_model
        )

    def _sync_views(self):
        self.tasks_page.load_tasks(self.project.tasks)
        self.sources_page.load_sources(UNASSIGNED_PROJECT_ID, self.uploaded_sources)
        self.document_page.set_uploaded_sources(self.uploaded_sources)
        self.document_page.set_projects(self.projects, self.project.id)
        self.document_page.load_data(
            self.project.id, self.project.sources, self.project.lessons
        )
        pending = [t for t in self.project.tasks if t.status != TaskStatus.Done]
        self.home_page.set_tasks(pending)
        self.home_page.set_lessons(self.project.lessons)
        self._update_status()

    def navigate_to(self, key: str):
        if key in self.pages:
            if key == "document":
                self.document_page.set_projects(self.projects, self.project.id)
                self.document_page.show_projects_list()
            self.stack.setCurrentWidget(self.pages[key])
            self.sidebar.set_active_page(key)
            self.page_label.setText(PAGE_NAMES.get(key, key))
            self._update_status()

    def _on_project_selected(self, project_id: str):
        for project in self.projects:
            if project.id == project_id:
                self.project = project
                self._sync_views()
                self.document_page.open_project(project)
                self.statusBar().showMessage(f"Proyecto abierto: {project.name}", 3000)
                break

    def _on_project_created(self, project: Project):
        self._is_ephemeral_default = False
        self.projects.insert(0, project)
        self.project = project
        save_project(project)
        self._sync_views()
        self.document_page.open_project(project)
        self.statusBar().showMessage(f"Proyecto creado: {project.name}", 3000)

    def _on_project_deleted(self, project_id: str):
        self.projects = [p for p in self.projects if p.id != project_id]
        delete_chunks_by_project(project_id)
        remove_project_uploads(project_id)
        delete_project(project_id)
        if not self.projects:
            self.projects = [Project(name="Proyecto principal")]
        if self.project.id == project_id:
            self.project = self.projects[0]
        self._sync_views()
        self.document_page.show_projects_list()
        self.statusBar().showMessage("Proyecto eliminado", 3000)

    def _on_db_settings_changed(self):
        loaded = load_all_projects()
        loaded_uploads = load_uploaded_sources()
        if loaded_uploads:
            loaded_upload_ids = {s.id for s in loaded_uploads}
            local_uploads = [
                s for s in self.uploaded_sources if s.id not in loaded_upload_ids
            ]
            self.uploaded_sources = local_uploads + loaded_uploads
        if not loaded:
            if loaded_uploads:
                self._sync_views()
            return
        loaded_ids = {p.id for p in loaded}
        # Conservar proyectos locales con cambios reales si aún no existen en la nueva BD
        local_dirty = [
            p
            for p in self.projects
            if p.id not in loaded_ids
            and not (
                self._is_ephemeral_default
                and len(self.projects) == 1
                and not p.tasks
                and not p.sources
                and not p.lessons
            )
        ]
        self.projects = local_dirty + loaded
        self._is_ephemeral_default = False
        if not any(p.id == self.project.id for p in self.projects):
            self.project = self.projects[0]
        self._sync_views()
        self.statusBar().showMessage("Proyectos sincronizados desde MongoDB", 3000)

    def _on_project_external_source_requested(self, project_id: str, file_path: str):
        self.sources_page.ingest_file(file_path, target_project_id=project_id)

    def _on_project_sources_from_uploads_requested(
        self, project_id: str, selected_sources: list[Source]
    ):
        target_project = next((p for p in self.projects if p.id == project_id), None)
        if target_project is None:
            return

        added_count = 0
        fallback_ingest_paths: list[str] = []

        for src in selected_sources:
            src_path = Path(src.path)
            copied_path: Path | None = None
            if src_path.is_file():
                try:
                    copied_path = copy_source_file(src_path, project_id)
                except OSError:
                    copied_path = None

            new_source = Source(
                project_id=project_id,
                name=src.name,
                path=str(copied_path) if copied_path is not None else src.path,
                source_type=src.source_type,
                published_date=src.published_date,
            )
            cloned = clone_chunks_for_project(src.id, project_id, new_source.id)
            if not cloned:
                if src_path.is_file():
                    fallback_ingest_paths.append(str(src_path))
                continue

            existing_idx = next(
                (
                    i
                    for i, s in enumerate(target_project.sources)
                    if s.path == new_source.path or s.name.lower() == new_source.name.lower()
                ),
                None,
            )
            if existing_idx is not None:
                delete_chunks_by_source(target_project.sources[existing_idx].id)
                target_project.sources[existing_idx] = new_source
            else:
                target_project.sources.append(new_source)
            added_count += 1

        if added_count > 0:
            self._is_ephemeral_default = False
            saved = save_project(target_project)
            self.document_page.set_projects(self.projects, self.project.id)
            if target_project.id == self.project.id:
                self.document_page.set_sources(target_project.sources)
            self._update_status()
            suffix = "" if saved else " (sin conexión a MongoDB)"
            self.statusBar().showMessage(
                f"{added_count} fuente(s) añadida(s) a «{target_project.name}» desde Subidos{suffix}",
                3500,
            )

        if fallback_ingest_paths:
            self.sources_page.ingest_file(
                fallback_ingest_paths[0], target_project_id=project_id
            )

    def _on_foreign_source_ingested(self, project_id: str, source: Source):
        for proj in self.projects:
            if proj.id == project_id:
                existing_idx = next(
                    (i for i, s in enumerate(proj.sources) if s.path == source.path),
                    None,
                )
                if existing_idx is not None:
                    delete_chunks_by_source(proj.sources[existing_idx].id)
                    proj.sources[existing_idx] = source
                else:
                    proj.sources.append(source)
                self._is_ephemeral_default = False
                saved = save_project(proj)
                self.document_page.set_projects(self.projects, self.project.id)
                if proj.id == self.project.id:
                    self.document_page.set_sources(proj.sources)
                self._update_status()
                suffix = "" if saved else " (sin conexión a MongoDB)"
                self.statusBar().showMessage(
                    f"Fuente «{source.name}» añadida a «{proj.name}»{suffix}", 3500
                )
                break

    def _on_foreign_lesson_generated(self, project_id: str, lesson: Lesson):
        for proj in self.projects:
            if proj.id == project_id:
                proj.lessons.append(lesson)
                save_project(proj)
                self.document_page.set_projects(self.projects, self.project.id)
                break

    def set_loading(self, active: bool, message: str = ""):
        self.progress_bar.setVisible(active)
        if active:
            self.progress_bar.setRange(0, 0)
            self.statusBar().showMessage(message or "Trabajando...")
        else:
            self.progress_bar.setRange(0, 1)
            self.statusBar().showMessage(message or "Listo", 4000)

    def _on_document_font_combo_changed(self, font: QFont):
        self._doc_font = QFont(font)
        self.settings_page.set_current_font(font)
        self.statusBar().showMessage(
            f"Fuente aplicada: {font.family()} ({font.pointSize()} pt)", 4000
        )

    def apply_document_font(self, font: QFont):
        self._doc_font = QFont(font)
        self.document_page.set_document_font(font)
        self.settings_page.set_current_font(font)
        self.statusBar().showMessage(
            f"Fuente aplicada: {font.family()} ({font.pointSize()} pt)", 4000
        )

    def _choose_font(self):
        ok, font = QFontDialog.getFont(self._doc_font, self, "Elegir fuente")
        if ok:
            self.apply_document_font(font)

    def _reset_font(self):
        self.apply_document_font(QFont("Inter", 10))

    def _on_tasks_changed(self, tasks: list):
        self._is_ephemeral_default = False
        self.project.tasks = tasks
        pending = [t for t in tasks if t.status != TaskStatus.Done]
        self.home_page.set_tasks(pending)
        saved = save_project(self.project)
        self._update_status()
        msg = "Tareas guardadas" if saved else "Tareas actualizadas (sin conexión a MongoDB)"
        self.statusBar().showMessage(msg, 3000)

    def _on_uploaded_sources_changed(self, sources: list):
        prev_ids = {s.id for s in self.uploaded_sources}
        new_ids = {s.id for s in sources}

        saved_all = True
        for removed_id in prev_ids - new_ids:
            if not delete_uploaded_source(removed_id):
                saved_all = False
        for src in sources:
            if src.id not in prev_ids:
                if not save_uploaded_source(src):
                    saved_all = False

        self.uploaded_sources = list(sources)
        self.document_page.set_uploaded_sources(self.uploaded_sources)
        self._update_status()
        msg = (
            "Material guardado en Subidos"
            if saved_all
            else "Material actualizado en Subidos (sin conexión a MongoDB)"
        )
        self.statusBar().showMessage(msg, 3000)

    def _on_lessons_changed(self, lessons: list):
        self._is_ephemeral_default = False
        self.project.lessons = lessons
        self.home_page.set_lessons(lessons)
        saved = save_project(self.project)
        self._update_status()
        msg = "Lecciones guardadas" if saved else "Lecciones actualizadas (sin conexión a MongoDB)"
        self.statusBar().showMessage(msg, 3000)

    def closeEvent(self, event):
        self.sources_page.shutdown_workers()
        self.document_page.shutdown_workers()
        self.settings_page.shutdown_workers()
        super().closeEvent(event)
