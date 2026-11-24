# Slice: `features/document/` (Lección tipo Notion + Chat con fuentes)

Vista central de SC.IA: lectura cómoda del documento curado por bloques (un archivo estructurado tipo tablero de Notion), **chat lateral colapsable** para preguntarle al LLM sobre las fuentes y el **pipeline de curado/verificación/reparación**.

## Widgets Qt obligatorios en este slice
- `QTreeWidget` + `QTreeWidgetItem`: índice navegable del temario (`TopicNode` recursivo).
- `QFontComboBox`: en la barra superior del documento para cambiar la tipografía de lectura en vivo.

## Archivos del slice
- **UI:**
  - `page.py`: `QSplitter` horizontal de 3 zonas:
    1. **Izquierda**: `QTreeWidget` con el índice del temario. Al hacer clic en un nodo, hace scroll al bloque correspondiente (`ensureWidgetVisible`) usando un dict `topic_id -> QWidget`.
    2. **Centro**: barra superior con `QFontComboBox` + botón toggle **"Chat con fuentes"**; debajo, un `QScrollArea` con `QVBoxLayout` de lectura cómoda donde se apilan los bloques.
    3. **Derecha (oculta por defecto)**: `ChatPanel`. El botón toggle hace `chat_panel.setVisible(not chat_panel.isVisible())`.
  - `blocks.py`: widgets por tipo de bloque (`TitleBlock`, `TextBlock`, `CodeBlock`), pie con fuentes citadas y fábrica `make_block_widget(block: BlockNode, source_names: dict[str, str]) -> QWidget`.
  - `chat_panel.py`: panel lateral colapsable con historial en streaming, `QLineEdit` + botón *Enviar*, señal `message_sent = Signal(str)` y métodos `append_user_message`, `start_assistant_message`, `append_assistant_token`, `finish_assistant_message`.
  - `styles.qss`: estilos específicos de lectura, bloques y burbujas del chat.
- **Dominio / IA:**
  - `outline.py`: extracción y fusión de temarios por fuente en un árbol `TopicNode`.
  - `pipeline.py`: orquestación paralela (RAG → decisión → redacción → verificación → reparación).
  - `verifier.py`: verificación determinista y con modelo rápido.
  - `repair.py`: inserción de contenido faltante en `BlockLinkedList` (máx. 2 rondas).
  - `chat.py`: servicio RAG para responder preguntas del `ChatPanel` usando las fuentes del proyecto.

## Contrato de `DocumentPage`
- `load_project(project: Project)`: limpia, llena el `QTreeWidget` y renderiza todos los bloques.
- `clear_document()` / `set_outline(root: TopicNode)` / `add_block(block: BlockNode)`: soporta carga progresiva desde `PipelineWorker`.
- `set_document_font(font: QFont)`: aplica la fuente elegida (tanto desde `QFontComboBox` como desde `QFontDialog`).
- `toggle_chat()`: muestra/oculta `ChatPanel`.
