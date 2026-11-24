from datetime import datetime
from random import choice

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scia.shared.ui.theme import PALETTE, apply_slice_qss, make_icon


class HomePage(QWidget):
    new_task_requested = Signal()
    new_lesson_requested = Signal()
    open_sources_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # Saludo según la hora del día
        hour = datetime.now().hour
        if hour < 12:
            greeting = "Buenos días"
        elif hour < 19:
            greeting = "Buenas tardes"
        else:
            greeting = "Buenas noches"

        self.title_text = QLabel(greeting)
        self.title_text.setObjectName("pageTitle")

        # Cita del día en una tarjeta con línea vertical de acento
        quotes = [
            ('"Quien tiene un porqué para vivir puede soportar casi cualquier cómo."', "Friedrich Nietzsche"),
            ('"La disciplina tarde o temprano vencerá a la inteligencia."', "Yokoi Kenji"),
            ('"El aprendizaje nunca agota la mente."', "Leonardo da Vinci"),
            ('"Somos lo que hacemos repetidamente. La excelencia, entonces, no es un acto, sino un hábito."', "Will Durant"),
            ('"El único modo de hacer un gran trabajo es amar lo que haces."', "Steve Jobs"),
            ('"No he fracasado. He encontrado diez mil formas que no funcionan."', "Thomas A. Edison"),
            ('"La simplicidad es la máxima sofisticación."', "Leonardo da Vinci"),
            ('"Primero resuelve el problema. Luego, escribe el código."', "John Johnson"),
            ('"El conocimiento habla, pero la sabiduría escucha."', "Jimi Hendrix"),
            ('"La mente que se abre a una nueva idea jamás volverá a su tamaño original."', "Albert Einstein"),
            ('"Un viaje de mil millas comienza con un solo paso."', "Lao-Tse"),
            ('"Hazlo funcionar, hazlo bien, hazlo rápido."', "Kent Beck"),
            ('"La constancia es la virtud por la cual todas las demás virtudes dan fruto."', "Arturo Graf"),
            ('"Dime y lo olvido, enséñame y lo recuerdo, involúcrame y lo aprendo."', "Benjamin Franklin"),
            ('"No cuentes los días, haz que los días cuenten."', "Muhammad Ali"),
            ('"La educación es el arma más poderosa que puedes usar para cambiar el mundo."', "Nelson Mandela"),
            ('"Cualquier tonto puede escribir código que una computadora entienda. Los buenos programadores escriben código que los humanos entienden."', "Martin Fowler"),
            ('"Lo que sabemos es una gota de agua; lo que ignoramos es el océano."', "Isaac Newton"),
            ('"El éxito es la suma de pequeños esfuerzos repetidos día tras día."', "Robert Collier"),
            ('"La duda es el origen de la sabiduría."', "René Descartes"),
        ]
        quote_text, quote_author = choice(quotes)

        self.quote_card = QFrame()
        self.quote_card.setObjectName("quoteCard")

        self.subtitle_text = QLabel(quote_text)
        self.subtitle_text.setObjectName("quoteText")
        self.subtitle_text.setWordWrap(True)

        self.author = QLabel(f"— {quote_author}")
        self.author.setObjectName("quoteAuthor")

        quote_layout = QVBoxLayout(self.quote_card)
        quote_layout.setContentsMargins(16, 12, 16, 12)
        quote_layout.setSpacing(4)
        quote_layout.addWidget(self.subtitle_text)
        quote_layout.addWidget(self.author)

        # Aviso visible cuando no hay modelo de IA configurado
        self.ai_warning_banner = QFrame()
        self.ai_warning_banner.setObjectName("warningBanner")

        self.ai_warning_text = QLabel(
            "Modelo de IA sin configurar. Agrega tu API Key y modelo para usar el chat y generar guías."
        )
        self.ai_warning_text.setWordWrap(True)

        self.go_settings_btn = QPushButton("Ir a Configuración")
        self.go_settings_btn.setObjectName("warningButton")
        self.go_settings_btn.clicked.connect(self.open_settings_requested.emit)

        warning_layout = QHBoxLayout(self.ai_warning_banner)
        warning_layout.setContentsMargins(16, 12, 16, 12)
        warning_layout.setSpacing(16)
        warning_layout.addWidget(self.ai_warning_text, 1)
        warning_layout.addWidget(self.go_settings_btn)

        # Tarjetas de resumen arriba (Fuentes, Guías, Tareas pendientes)
        self.sources_stat_value, sources_card = self._build_stat_card("Fuentes subidas", "0")
        self.lessons_stat_value, lessons_card = self._build_stat_card("Guías generadas", "0")
        self.tasks_stat_value, tasks_card = self._build_stat_card("Tareas pendientes", "0")

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        stats_row.addWidget(sources_card, 1)
        stats_row.addWidget(lessons_card, 1)
        stats_row.addWidget(tasks_card, 1)

        # Guía rápida de 3 pasos (se oculta cuando ya hay guías generadas)
        self.onboarding_card = QFrame()
        self.onboarding_card.setObjectName("onboardingCard")

        onboarding_label = QLabel(
            "Empieza rápido:   1. Sube tus fuentes   →   2. Abre Proyectos   →   3. Genera tu primera guía"
        )
        onboarding_label.setObjectName("pageSubtitle")
        onboarding_label.setWordWrap(True)

        self.upload_quick_btn = QPushButton("Subir fuentes")
        self.upload_quick_btn.setObjectName("ghostButton")
        self.upload_quick_btn.clicked.connect(self.open_sources_requested.emit)

        onboarding_layout = QHBoxLayout(self.onboarding_card)
        onboarding_layout.setContentsMargins(16, 12, 16, 12)
        onboarding_layout.setSpacing(14)
        onboarding_layout.addWidget(onboarding_label, 1)
        onboarding_layout.addWidget(self.upload_quick_btn)

        # --- Columna izquierda: Tareas pendientes ---
        self.tasks_title = QLabel("TAREAS PENDIENTES")
        self.tasks_title.setObjectName("sectionTitle")

        self.new_task_button = QPushButton("+ Nueva tarea")
        self.new_task_button.setObjectName("primaryButton")
        self.new_task_button.clicked.connect(self.new_task_requested.emit)

        tasks_header = QHBoxLayout()
        tasks_header.addWidget(self.tasks_title)
        tasks_header.addStretch()
        tasks_header.addWidget(self.new_task_button)

        self.tasks_empty_card = self._build_empty_card(
            icon_path=":/icons/tasks",
            message="No tienes tareas pendientes todavía.",
            button_text="+ Crear mi primera tarea",
            primary=True,
            on_click=self.new_task_requested.emit,
        )

        self.tasks_list = QTableWidget(0, 3)
        self.tasks_list.setObjectName("homeTasksTable")
        self.tasks_list.setHorizontalHeaderLabels(["Tarea", "Estado", "Fecha límite"])
        self.tasks_list.setShowGrid(False)
        self.tasks_list.setAlternatingRowColors(True)
        self.tasks_list.verticalHeader().setVisible(False)
        self.tasks_list.verticalHeader().setDefaultSectionSize(42)
        self.tasks_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tasks_list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tasks_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        tasks_header_view = self.tasks_list.horizontalHeader()
        tasks_header_view.setMinimumSectionSize(96)
        tasks_header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tasks_header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tasks_header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_list.setMinimumHeight(220)
        self.tasks_list.setVisible(False)

        tasks_col = QVBoxLayout()
        tasks_col.setSpacing(12)
        tasks_col.addLayout(tasks_header)
        tasks_col.addWidget(self.tasks_empty_card)
        tasks_col.addWidget(self.tasks_list, 1)
        tasks_col.addStretch()

        # --- Columna derecha: Proyectos y guías ---
        self.lesson_title = QLabel("PROYECTOS Y GUÍAS")
        self.lesson_title.setObjectName("sectionTitle")

        self.new_lesson_button = QPushButton("Abrir Proyectos")
        self.new_lesson_button.setObjectName("ghostButton")
        self.new_lesson_button.clicked.connect(self.new_lesson_requested.emit)

        lessons_header = QHBoxLayout()
        lessons_header.addWidget(self.lesson_title)
        lessons_header.addStretch()
        lessons_header.addWidget(self.new_lesson_button)

        self.lessons_empty_card = self._build_empty_card(
            icon_path=":/icons/document",
            message="Aún no tienes guías generadas en tus proyectos.",
            button_text="Ir a Proyectos",
            primary=False,
            on_click=self.new_lesson_requested.emit,
        )

        self.lessons_model = QStandardItemModel()
        self.lessons = QListView()
        self.lessons.setObjectName("homeLessonsList")
        self.lessons.setAlternatingRowColors(True)
        self.lessons.setModel(self.lessons_model)
        self.lessons.setMinimumHeight(220)
        self.lessons.setVisible(False)

        lessons_col = QVBoxLayout()
        lessons_col.setSpacing(12)
        lessons_col.addLayout(lessons_header)
        lessons_col.addWidget(self.lessons_empty_card)
        lessons_col.addWidget(self.lessons, 1)
        lessons_col.addStretch()

        # Cuadrícula de dos columnas para aprovechar bien el ancho
        columns_row = QHBoxLayout()
        columns_row.setSpacing(28)
        columns_row.addLayout(tasks_col, 1)
        columns_row.addLayout(lessons_col, 1)

        # Contenedor con ancho máximo para que no se estire en pantallas muy anchas
        content = QWidget()
        content.setMaximumWidth(1140)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 28, 36, 28)
        content_layout.setSpacing(22)
        content_layout.addWidget(self.title_text)
        content_layout.addWidget(self.quote_card)
        content_layout.addWidget(self.ai_warning_banner)
        content_layout.addLayout(stats_row)
        content_layout.addWidget(self.onboarding_card)
        content_layout.addLayout(columns_row, 1)

        # Centrar el contenedor dentro de un QScrollArea
        wrapper = QWidget()
        wrapper.setObjectName("centralContainer")
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addStretch()
        wrapper_layout.addWidget(content, 1)
        wrapper_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrapper)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
        apply_slice_qss(self, __file__)

    def _build_stat_card(self, label_text: str, initial_value: str) -> tuple[QLabel, QFrame]:
        card = QFrame()
        card.setObjectName("statCard")

        value_label = QLabel(initial_value)
        value_label.setObjectName("statValue")

        title_label = QLabel(label_text)
        title_label.setObjectName("statLabel")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        layout.addWidget(value_label)
        layout.addWidget(title_label)
        return value_label, card

    def _build_empty_card(
        self,
        icon_path: str,
        message: str,
        button_text: str,
        primary: bool,
        on_click,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("emptyStateCard")
        card.setMinimumHeight(145)
        card.setMaximumHeight(175)

        icon_label = QLabel()
        icon_label.setPixmap(make_icon(icon_path, color="#7b96bf").pixmap(26, 26))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        msg_label = QLabel(message)
        msg_label.setObjectName("pageSubtitle")
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)

        action_btn = QPushButton(button_text)
        action_btn.setObjectName("primaryButton" if primary else "ghostButton")
        action_btn.clicked.connect(on_click)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(action_btn)
        btn_row.addStretch()

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addStretch()
        layout.addWidget(icon_label)
        layout.addWidget(msg_label)
        layout.addLayout(btn_row)
        layout.addStretch()
        return card

    def set_summary(
        self, sources_count: int, lessons_count: int, pending_count: int, has_model: bool
    ):
        self.sources_stat_value.setText(str(sources_count))
        self.lessons_stat_value.setText(str(lessons_count))
        self.tasks_stat_value.setText(str(pending_count))
        self.ai_warning_banner.setVisible(not has_model)
        self.onboarding_card.setVisible(lessons_count == 0)

    def set_tasks(self, tasks: list):
        self.tasks_list.setRowCount(0)
        has_tasks = len(tasks) > 0
        self.tasks_empty_card.setVisible(not has_tasks)
        self.tasks_list.setVisible(has_tasks)

        status_labels = {
            "Pending": "Pendiente",
            "In_Progress": "En progreso",
            "Done": "Hecha",
        }
        status_colors = {
            "Pending": PALETTE["warning"],
            "In_Progress": PALETTE["primary_light"],
            "Done": PALETTE["success"],
        }
        for row, task in enumerate(tasks):
            self.tasks_list.insertRow(row)
            raw_status = str(task.status)
            status_text = status_labels.get(raw_status, raw_status)

            title_item = QTableWidgetItem(task.title)
            title_font = QFont(title_item.font())
            title_font.setWeight(QFont.Weight.DemiBold)
            title_item.setFont(title_font)

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(
                QColor(status_colors.get(raw_status, PALETTE["text"]))
            )
            status_font = QFont(status_item.font())
            status_font.setWeight(QFont.Weight.DemiBold)
            status_item.setFont(status_font)

            due_item = QTableWidgetItem(task.due_at.strftime("%Y-%m-%d %H:%M"))
            due_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            due_item.setForeground(QColor(PALETTE["text_secondary"]))

            self.tasks_list.setItem(row, 0, title_item)
            self.tasks_list.setItem(row, 1, status_item)
            self.tasks_list.setItem(row, 2, due_item)

    def set_lessons(self, lessons: list):
        self.lessons_model.clear()
        has_lessons = len(lessons) > 0
        self.lessons_empty_card.setVisible(not has_lessons)
        self.lessons.setVisible(has_lessons)

        for lesson in lessons:
            item = QStandardItem(lesson.title)
            item.setEditable(False)
            item.setSizeHint(QSize(0, 40))
            self.lessons_model.appendRow(item)
