# Slice: `features/sources/` (Subidos / Fuentes)

Gestión de archivos fuente locales del proyecto, extracción de texto, chunking, almacenamiento vectorial y disparo del pipeline de generación (referencia: pág. 1 de `diseño_anterior_base.pdf`).

## Archivos del slice
- **UI:** `page.py`, `styles.qss`.
- **Dominio / Datos:**
  - `ingest.py`: detección de tipo (`SourceType`) y extracción de texto (`PDF`, `MD`, `TXT`).
  - `chunking.py`: división de texto en chunks con solapamiento.
  - `chunks_repo.py`: persistencia de `Chunk` + embeddings + búsqueda vectorial en MongoDB.

## Widgets Qt obligatorios en este slice
- `QTreeView` + `QFileSystemModel` (explorador de archivos a la izquierda, filtrado por `*.pdf`, `*.md`, `*.txt`).
- `QTableWidget` + `QTableWidgetItem` (tabla de fuentes agregadas: Nombre, Tipo, Fecha).
- `QDateEdit` dentro de la columna *Fecha* de cada fila (`setCellWidget`) para la fecha de publicación de la fuente.
- `QProgressDialog` (modal y cancelable) al lanzar la indexación/generación (puede vivir aquí o en `main_window.py`).

## Estructura visual
- Encabezado: título serif `"Subidos"` + subtítulo `"Todo tu material."`.
- `QSplitter` horizontal:
  - Izquierda: `QTreeView` explorador local (doble clic o botón *Agregar* añade el archivo a la tabla).
  - Derecha:
    - Barra superior: `QLineEdit` buscador (`"Busca tu material..."`), botón *Quitar*, botón primario blanco **Agregar nuevo material** y botón **Generar lección**.
    - Cuerpo: `QTableWidget` con las fuentes cargadas (evitar duplicados por ruta).

## Contrato
- Método `get_sources(project_id: str) -> list[Source]` que construye los objetos `Source` leyendo la tabla y los `QDateEdit`.
- Método `load_sources(sources: list[Source])` para cargar desde un `Project` existente.
- Señal `generate_requested = Signal(list)` que emite la lista de `Source` hacia `main_window.py`.
