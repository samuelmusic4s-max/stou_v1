from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scia.shared.config import ModelRole, save_settings, settings
from scia.shared.workers import DbPingWorker, retire_worker, stop_worker_safely


def _mask_api_key(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        return "No configurada"
    if len(key) <= 4:
        return "•" * len(key)
    return f"••••{key[-4:]}"


def _build_password_row(initial_text: str, placeholder: str) -> tuple[QLineEdit, QWidget]:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    line_edit = QLineEdit(initial_text)
    line_edit.setEchoMode(QLineEdit.EchoMode.Password)
    line_edit.setPlaceholderText(placeholder)

    toggle_btn = QPushButton("Mostrar")
    toggle_btn.setCheckable(True)
    toggle_btn.setFixedWidth(74)

    def _toggle(checked: bool):
        line_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        toggle_btn.setText("Ocultar" if checked else "Mostrar")

    toggle_btn.toggled.connect(_toggle)

    layout.addWidget(line_edit, 1)
    layout.addWidget(toggle_btn)
    return line_edit, container


class ApiConfigDialog(QDialog):
    _ROLE_SECTIONS = (
        (
            ModelRole.Generator,
            "Modelo de lenguaje grande (Chat / Lecciones)",
            "Ej: https://api.openai.com/v1",
            "Ej: gpt-4o-mini / gemini-2.5-flash",
        ),
        (
            ModelRole.Embeddings,
            "Modelo de Embeddings",
            "Ej: http://localhost:1234/v1",
            "Ej: text-embedding-3-small",
        ),
        (
            ModelRole.Decision,
            "Modelo de Decisión",
            "Ej: http://localhost:1234/v1",
            "Ej: gpt-4o-mini / modelo de decisión",
        ),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Configurar modelos y API Keys")
        self.setMinimumWidth(560)

        self.role_inputs: dict[ModelRole, tuple[QLineEdit, QLineEdit, QLineEdit]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        for role, section_title, url_placeholder, model_placeholder in self._ROLE_SECTIONS:
            cfg = settings.get_role(role)
            group = QGroupBox(section_title)
            form = QFormLayout(group)
            form.setSpacing(10)

            url_input = QLineEdit(cfg.base_url if cfg else "")
            url_input.setPlaceholderText(url_placeholder)

            key_input, key_row = _build_password_row(
                cfg.api_key if cfg else "", "Tu API Key..."
            )

            model_input = QLineEdit(cfg.model if cfg else "")
            model_input.setPlaceholderText(model_placeholder)

            form.addRow("Base URL:", url_input)
            form.addRow("API Key:", key_row)
            form.addRow("Modelo:", model_input)

            self.role_inputs[role] = (url_input, key_input, model_input)
            layout.addWidget(group)

        # Alias convenientes por rol
        self.base_url_input, self.api_key_input, self.generator_model_input = (
            self.role_inputs[ModelRole.Generator]
        )
        (
            self.embeddings_base_url_input,
            self.embeddings_api_key_input,
            self.embeddings_model_input,
        ) = self.role_inputs[ModelRole.Embeddings]
        (
            self.decision_base_url_input,
            self.decision_api_key_input,
            self.decision_model_input,
        ) = self.role_inputs[ModelRole.Decision]

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DbConfigDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Configurar MongoDB")
        self.setMinimumWidth(440)

        self.db_url_input = QLineEdit(settings.database_url)
        self.db_url_input.setPlaceholderText("mongodb://localhost:27017")

        self.db_name_input = QLineEdit(settings.database_name)
        self.db_name_input.setPlaceholderText("scia")

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("URI de conexión:", self.db_url_input)
        form.addRow("Nombre BD:", self.db_name_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(form)
        layout.addWidget(buttons)


class SettingsPage(QWidget):
    font_requested = Signal()
    font_reset_requested = Signal()
    settings_changed = Signal()
    db_settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._ping_worker: DbPingWorker | None = None

        self.title_text = QLabel("Configuración")
        self.title_text.setObjectName("pageTitle")
        self.title_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.subtitle_text = QLabel("Personaliza tus modelos, API keys y base de datos.")
        self.subtitle_text.setObjectName("pageSubtitle")
        self.subtitle_text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.title_layout = QVBoxLayout()
        self.title_layout.addWidget(self.title_text)
        self.title_layout.addWidget(self.subtitle_text)

        # --- Tarjeta izquierda: Resumen de Modelos IA ---
        self.ai_card = QFrame()
        self.ai_card.setObjectName("card")

        self.ai_title = QLabel("Modelos IA (Compatible OpenAI)")
        self.ai_title.setObjectName("sectionTitle")

        self.gen_model_label = QLabel()
        self.gen_model_label.setWordWrap(True)
        self.emb_model_label = QLabel()
        self.emb_model_label.setWordWrap(True)
        self.dec_model_label = QLabel()
        self.dec_model_label.setWordWrap(True)

        self.edit_ai_button = QPushButton("Configurar modelos y API Keys...")
        self.edit_ai_button.setObjectName("primaryButton")
        self.edit_ai_button.clicked.connect(self._open_api_dialog)

        self.ai_layout = QVBoxLayout(self.ai_card)
        self.ai_layout.setContentsMargins(20, 20, 20, 20)
        self.ai_layout.setSpacing(12)
        self.ai_layout.addWidget(self.ai_title)
        self.ai_layout.addWidget(self.gen_model_label)
        self.ai_layout.addWidget(self.emb_model_label)
        self.ai_layout.addWidget(self.dec_model_label)
        self.ai_layout.addStretch()
        self.ai_layout.addWidget(self.edit_ai_button)

        # --- Tarjeta derecha arriba: MongoDB ---
        self.db_card = QFrame()
        self.db_card.setObjectName("card")

        self.db_title = QLabel("Base de datos (MongoDB)")
        self.db_title.setObjectName("sectionTitle")

        self.db_url_label = QLabel()
        self.db_name_label = QLabel()
        self.db_status_label = QLabel("")
        self.db_status_label.setObjectName("pageSubtitle")

        self.edit_db_button = QPushButton("Configurar base de datos...")
        self.edit_db_button.clicked.connect(self._open_db_dialog)

        self.test_db_button = QPushButton("Probar conexión")
        self.test_db_button.clicked.connect(self._test_db)

        self.db_buttons = QHBoxLayout()
        self.db_buttons.addWidget(self.edit_db_button)
        self.db_buttons.addWidget(self.test_db_button)

        self.db_layout = QVBoxLayout(self.db_card)
        self.db_layout.setContentsMargins(20, 20, 20, 20)
        self.db_layout.setSpacing(10)
        self.db_layout.addWidget(self.db_title)
        self.db_layout.addWidget(self.db_url_label)
        self.db_layout.addWidget(self.db_name_label)
        self.db_layout.addLayout(self.db_buttons)
        self.db_layout.addWidget(self.db_status_label)
        self.db_layout.addStretch()

        # --- Tarjeta derecha abajo: Apariencia ---
        self.appearance_card = QFrame()
        self.appearance_card.setObjectName("card")

        self.appearance_title = QLabel("Apariencia y tipografía")
        self.appearance_title.setObjectName("sectionTitle")

        self.current_font_label = QLabel("Fuente actual: Inter (10 pt)")
        self.current_font_label.setObjectName("pageSubtitle")

        self.font_preview_label = QLabel("Así se verá el texto de tus lecciones.")

        self.font_button = QPushButton("Elegir y aplicar fuente...")
        self.font_button.setObjectName("primaryButton")
        self.font_button.clicked.connect(self.font_requested.emit)

        self.reset_font_button = QPushButton("Restablecer")
        self.reset_font_button.clicked.connect(self.font_reset_requested.emit)

        self.font_buttons = QHBoxLayout()
        self.font_buttons.addWidget(self.font_button)
        self.font_buttons.addWidget(self.reset_font_button)

        self.appearance_layout = QVBoxLayout(self.appearance_card)
        self.appearance_layout.setContentsMargins(20, 20, 20, 20)
        self.appearance_layout.setSpacing(10)
        self.appearance_layout.addWidget(self.appearance_title)
        self.appearance_layout.addWidget(self.current_font_label)
        self.appearance_layout.addWidget(self.font_preview_label)
        self.appearance_layout.addLayout(self.font_buttons)
        self.appearance_layout.addStretch()

        self.right_column = QVBoxLayout()
        self.right_column.setSpacing(20)
        self.right_column.addWidget(self.db_card, 2)
        self.right_column.addWidget(self.appearance_card, 1)

        self.content_layout = QHBoxLayout()
        self.content_layout.setSpacing(25)
        self.content_layout.addWidget(self.ai_card, 3)
        self.content_layout.addLayout(self.right_column, 2)

        self.root_layout = QVBoxLayout()
        self.root_layout.addLayout(self.title_layout)
        self.root_layout.addLayout(self.content_layout)
        self.root_layout.setContentsMargins(40, 30, 30, 30)
        self.root_layout.setSpacing(30)

        self.setLayout(self.root_layout)
        self._refresh_labels()

    def _refresh_labels(self):
        gen = settings.get_role(ModelRole.Generator)
        emb = settings.get_role(ModelRole.Embeddings)
        dec = settings.get_role(ModelRole.Decision)

        def _fmt_role(label: str, rc) -> str:
            model = rc.model if (rc and rc.model) else "Sin definir"
            url = rc.base_url if (rc and rc.base_url) else "—"
            key = _mask_api_key(rc.api_key if rc else "")
            return f"{label}: {model}\n  URL: {url} · Key: {key}"

        self.gen_model_label.setText(_fmt_role("LLM (Chat/Lecciones)", gen))
        self.emb_model_label.setText(_fmt_role("Embeddings", emb))
        self.dec_model_label.setText(_fmt_role("Decisión", dec))

        self.db_url_label.setText(f"URI: {settings.database_url}")
        self.db_name_label.setText(f"Base de datos: {settings.database_name}")

    def _open_api_dialog(self):
        dialog = ApiConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for role, (url_input, key_input, model_input) in dialog.role_inputs.items():
                base_url = url_input.text().strip()
                api_key = key_input.text().strip()
                model = model_input.text().strip()

                # Evitar sobrescribir la key real si alguien pegó literalmente puntos de máscara
                if api_key and set(api_key) <= {"•", "*"}:
                    existing = settings.get_role(role)
                    api_key = existing.api_key if existing else ""

                settings.update_role(
                    role,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                )

            # Mantener Repair sincronizado con Generator
            gen = settings.get_role(ModelRole.Generator)
            if gen is not None:
                settings.update_role(
                    ModelRole.Repair,
                    base_url=gen.base_url,
                    api_key=gen.api_key,
                    model=gen.model,
                )

            save_settings()
            self._refresh_labels()
            self.settings_changed.emit()

    def _open_db_dialog(self):
        dialog = DbConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            db_url = dialog.db_url_input.text().strip()
            db_name = dialog.db_name_input.text().strip()
            if db_url:
                settings.database_url = db_url
            if db_name:
                settings.database_name = db_name
            save_settings()
            self._refresh_labels()
            self.settings_changed.emit()
            self.db_settings_changed.emit()

    def _test_db(self):
        if self._ping_worker is not None and self._ping_worker.isRunning():
            return
        self.test_db_button.setEnabled(False)
        self.db_status_label.setText("Probando conexión con MongoDB...")
        worker = DbPingWorker(parent=self)
        self._ping_worker = worker
        worker.result.connect(self._on_db_ping_result)
        worker.start()

    def _on_db_ping_result(self, ok: bool):
        self.test_db_button.setEnabled(True)
        self.db_status_label.setText(
            "Conexión exitosa con MongoDB." if ok else "No se pudo conectar a MongoDB."
        )
        if self._ping_worker is not None:
            worker = self._ping_worker
            self._ping_worker = None
            retire_worker(worker)

    def shutdown_workers(self):
        worker = self._ping_worker
        self._ping_worker = None
        stop_worker_safely(worker, timeout_ms=2500)

    def set_current_font(self, font: QFont):
        self.current_font_label.setText(
            f"Fuente actual: {font.family()} ({font.pointSize()} pt)"
        )
        self.font_preview_label.setFont(font)
