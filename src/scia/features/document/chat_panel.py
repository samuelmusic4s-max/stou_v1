from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class PromptInput(QPlainTextEdit):
    submitted = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("promptInput")
        self.setPlaceholderText(
            "Pregúntale algo a la IA sobre tus fuentes... (Enter para enviar, Shift+Enter para salto de línea)"
        )
        self.setFixedHeight(76)

    def keyPressEvent(self, event: QKeyEvent):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    message_sent = Signal(str)
    sources_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_ai_label: QLabel | None = None
        self._current_ai_text: str = ""
        self._message_font: QFont | None = None
        self._message_labels: list[QLabel] = []

        # Área de conversación con scroll (estilo ChatGPT / Gemini)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background: transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(16, 16, 16, 16)
        self.messages_layout.setSpacing(16)

        # Estado vacío inicial centrado
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(8)
        empty_title = QLabel("¿En qué te ayudo hoy?")
        empty_title.setObjectName("chatEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_sub = QLabel(
            "Sube tus fuentes en el botón «Fuentes» y haz preguntas directamente aquí."
        )
        empty_sub.setObjectName("pageSubtitle")
        empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_sub)

        self.messages_layout.addWidget(self.empty_state, 1)
        self.messages_layout.addStretch()

        self.scroll_area.setWidget(self.messages_container)

        # Caja de prompt amplia abajo (estilo ChatGPT / Gemini)
        self.prompt_box = QFrame()
        self.prompt_box.setObjectName("promptBox")

        self.prompt_input = PromptInput()
        self.prompt_input.submitted.connect(self._send)

        self.sources_button = QPushButton("Fuentes (0)")
        self.sources_button.clicked.connect(self.sources_requested.emit)

        self.clear_button = QPushButton("Limpiar chat")
        self.clear_button.setObjectName("ghostButton")
        self.clear_button.clicked.connect(self._on_clear_clicked)

        self.send_button = QPushButton("Enviar")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self._send)

        prompt_actions = QHBoxLayout()
        prompt_actions.addWidget(self.sources_button)
        prompt_actions.addWidget(self.clear_button)
        prompt_actions.addStretch()
        prompt_actions.addWidget(self.send_button)

        prompt_layout = QVBoxLayout(self.prompt_box)
        prompt_layout.setContentsMargins(14, 10, 14, 10)
        prompt_layout.setSpacing(8)
        prompt_layout.addWidget(self.prompt_input)
        prompt_layout.addLayout(prompt_actions)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(14)
        self.root_layout.addWidget(self.scroll_area, 1)
        self.root_layout.addWidget(self.prompt_box)

    def set_sources_count(self, count: int):
        self.sources_button.setText(f"Fuentes ({count})")

    def set_chat_font(self, font: QFont):
        self._message_font = font
        for label in self._message_labels:
            label.setFont(font)

    def _send(self):
        text = self.prompt_input.toPlainText().strip()
        if not text:
            return
        self.prompt_input.clear()
        self._add_user_bubble(text)
        self.message_sent.emit(text)

    def _hide_empty_state(self):
        if self.empty_state.isVisible():
            self.empty_state.setVisible(False)

    def _scroll_to_bottom(self):
        QTimer.singleShot(
            10,
            lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ),
        )

    def _add_user_bubble(self, text: str):
        self._hide_empty_state()

        bubble = QFrame()
        bubble.setObjectName("userBubble")
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setMaximumWidth(640)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet("background: transparent;")
        if self._message_font is not None:
            label.setFont(self._message_font)
        self._message_labels.append(label)

        box = QVBoxLayout(bubble)
        box.setContentsMargins(14, 10, 14, 10)
        box.addWidget(label)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(bubble)

        # Insertar justo antes del stretch final
        self.messages_layout.insertLayout(self.messages_layout.count() - 1, row)
        self._scroll_to_bottom()

    def start_assistant_reply(self):
        self._hide_empty_state()
        self._current_ai_text = ""

        bubble = QFrame()
        bubble.setObjectName("aiBubble")

        header = QLabel("SC.IA")
        header.setObjectName("pageSubtitle")

        label = QLabel("...")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.MarkdownText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet("background: transparent;")
        if self._message_font is not None:
            label.setFont(self._message_font)
        self._message_labels.append(label)

        box = QVBoxLayout(bubble)
        box.setContentsMargins(6, 4, 6, 4)
        box.setSpacing(6)
        box.addWidget(header)
        box.addWidget(label)

        self._current_ai_label = label
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def append_token(self, token: str):
        if self._current_ai_label is None:
            self.start_assistant_reply()
        self._current_ai_text += token
        self._current_ai_label.setText(self._current_ai_text)
        self._scroll_to_bottom()

    def finish_assistant_reply(self):
        self._current_ai_label = None
        self._scroll_to_bottom()

    def set_current_reply_text(self, text: str):
        if self._current_ai_label is not None:
            self._current_ai_text = text
            self._current_ai_label.setText(text)
            self._scroll_to_bottom()

    def _on_clear_clicked(self):
        self.clear_messages()
        self.clear_requested.emit()

    def _clear_layout_item(self, item):
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            return
        sub_layout = item.layout()
        if sub_layout is not None:
            while sub_layout.count():
                child = sub_layout.takeAt(0)
                self._clear_layout_item(child)
            sub_layout.deleteLater()

    def clear_messages(self):
        self._current_ai_label = None
        self._current_ai_text = ""
        self._message_labels.clear()
        # Conservar índice 0 (empty_state) y el último ítem (stretch)
        while self.messages_layout.count() > 2:
            item = self.messages_layout.takeAt(1)
            self._clear_layout_item(item)
        self.empty_state.setVisible(True)

    def set_busy(self, busy: bool):
        self.send_button.setEnabled(not busy)
        self.prompt_input.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
