# SC.IA — Reglas generales del proyecto

Guía de contexto general para cualquier agente o colaborador que trabaje en **SC.IA** (curador multi-fuente con IA en Python + PySide6).

---

## 1. Regla de colaboración
- **El código principal lo escribe Samuel**, pero el agente puede proponer soluciones, patrones, snippets de referencia, revisar código, depurar errores y echar una mano directa cuando Samuel lo pida.
- No reescribir ni borrar código ya implementado sin confirmar primero.
- Respetar los contratos de datos (`models.py`) y señales (`ui/workers.py`).

---

## 2. Arquitectura (Vertical Slicing completo)

Estructura en `src/scia/`:
- `src/scia/__init__.py`, `__main__.py`, `main_window.py`, `dev_data.py`: punto de entrada, shell principal (`QMainWindow`) y datos mock.
- `src/scia/shared/`: infraestructura transversal (`config.py`, `models.py`, `llm.py`, `mongo.py`, `projects_repo.py`, `project_xml.py`, `workers.py`) y UI compartida en `shared/ui/` (estilos base, iconos/QResource, sidebar). Ver `shared/ui/RULES.md`.
- `src/scia/features/<slice>/`: cada funcionalidad es una carpeta autocontenida con su UI (`page.py`, `styles.qss`, `RULES.md`) y su lógica/persistencia de dominio:
  - `features/home/`: bienvenida y resúmenes.
  - `features/sources/`: UI de fuentes + `ingest.py`, `chunking.py`, `chunks_repo.py`.
  - `features/document/`: UI de lección (`blocks.py`, `chat_panel.py`) + `chat.py`, `outline.py`, `pipeline.py`, `verifier.py`, `repair.py`.
  - `features/quiz/`: test con temporizador y estadísticas.
  - `features/tasks/`: CRUD de retos prácticos.
  - `features/settings/`: configuración de modelos, tipografía y base de datos.

### Reglas de aislamiento
- Las páginas (`page.py`) **nunca** llaman directamente a `shared/llm.py` ni a `shared/mongo.py`; toda operación lenta pasa por `shared/workers.py`.
- Cada feature en `features/<slice>/` carga su propio `styles.qss` local (complementando `shared/ui/styles.qss`).
- La UI debe funcionar primero con datos mock (`src/scia/dev_data.py`) y luego conectarse al pipeline real sin cambiar las páginas.

---

## 3. Línea gráfica (basada en `diseño_anterior_base.pdf`)
- **Tema oscuro editorial / tipo Notion**:
  - Fondo principal: `#191919`
  - Superficies / tarjetas / paneles: `#262626` (hover `#2f2f2f`, borde sutil `#3a3a3a`)
  - Sidebar izquierda fija (`~180–200px`): `#333333` con logo **SC.IA** arriba y botones de navegación.
  - Texto principal: `#f2f2f2` · Texto secundario: `#a0a0a0`
  - Botón primario (CTA): fondo blanco `#ffffff`, texto oscuro `#191919`, bordes redondeados (`4–6px`).
  - Botón secundario: fondo `#262626`, borde `#4a4a4a`, texto `#f2f2f2`.
- **Tipografía**:
  - Títulos de página: Serif grande y en negrita (p. ej. `Georgia` / `Liberation Serif`, `28–32px`).
  - Cuerpo e interfaz: Sans-serif limpia (`Inter` / `Segoe UI` / `Ubuntu`, `13–14px`).
  - Bloques de código: Monoespaciada (`JetBrains Mono` / `Fira Code` / `monospace`).
- **Módulo descartado**: **Calendario** no se implementa.

---

## 4. Iconos y QResource System
- Los iconos van en `src/scia/shared/ui/icons/` y se registran en `src/scia/shared/ui/resources.qrc`.
- Se compilan con:
  ```bash
  uv run pyside6-rcc src/scia/shared/ui/resources.qrc -o src/scia/shared/ui/resources_rc.py
  ```
- **Siempre** importar `from scia.shared.ui import resources_rc` (aunque no se use directamente) antes de instanciar `QIcon(":/icons/...")`.

---

## 5. Requisitos Qt obligatorios (Checklist)
| Requisito | Slice / Archivo responsable |
|---|---|
| `QMainWindow`, Menús y `QToolBar` | `src/scia/main_window.py` |
| `QResource System` (`resources.qrc`) | `src/scia/shared/ui/` |
| `QProgressBar` | `src/scia/main_window.py` (en `QStatusBar`) |
| `QProgressDialog` | `src/scia/main_window.py` / `features/sources/` (indexación cancelable) |
| `QFontComboBox` | `features/document/page.py` |
| `QFontDialog` | `src/scia/main_window.py` (*Ver → Fuente…*) y `features/settings/page.py` |
| `QDateEdit` | `features/sources/page.py` |
| `QDateTimeEdit` | `features/tasks/page.py` |
| `QTimeEdit` | `features/tasks/page.py` (tiempo estimado por tarea) |
| `QTreeWidget` + `QTreeWidgetItem` | `features/document/page.py` |
| `QTreeView` (`QFileSystemModel`) | `features/sources/page.py` |
| `QTableWidget` + `QTableWidgetItem` | `features/home/page.py` |
| `QTableView` (`QStandardItemModel`) | `features/tasks/page.py` y `features/sources/page.py` |
| Empaquetado Windows (PyInstaller `--onedir` + InstallForge) | Build de entrega (`dist/SC.IA/`) |

---

## 6. Contratos clave (UI ↔ Backend)
- **Modelos** (`src/scia/shared/models.py`): `Project`, `Source`, `TopicNode`, `BlockNode`, `BlockLinkedList`, `Question`, `QuizAttempt`, `Task`, `TaskStatus`.
- **Señales de `src/scia/shared/workers.py`**:
  - `PipelineWorker`: `progress(str)`, `progress_value(int, int)`, `block_ready(object)`, `finished(object)`, `error(str)`.
  - `ChatWorker`: `token(str)`, `finished()`, `error(str)`.
