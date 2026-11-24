# Slice: `features/settings/` (Configuración)

Personalización de la aplicación y configuración de modelos/base de datos (referencia: pág. 4 de `diseño_anterior_base.pdf`).

## Widgets Qt obligatorios en este slice
- `QFontDialog`: botón **Elegir fuente del documento…** que abre `QFontDialog.getFont(...)` y emite la fuente seleccionada hacia `main_window.py` → `DocumentPage.set_document_font(font)`.

## Estructura visual
- Encabezado: título serif `"Configuración"` + subtítulo `"Personaliza la aplicación."`.
- Layout en 2 columnas (como en pág. 4 del PDF):
  - Izquierda (grande): formulario de roles de IA (`Embeddings`, `Decision`, `Generator`, `Repair`) leyendo/actualizando `settings` de `src/scia/shared/config.py` (`base_url`, `api_key`, `model`) + botón **Guardar cambios**.
  - Derecha (2 tarjetas apiladas):
    - Arriba: **Tipografía de lectura** (muestra fuente actual + botón que abre `QFontDialog`).
    - Abajo: **Base de datos** (`DATABASE_URL` + botón *Probar conexión* que llama `ping_db()` de `src/scia/shared/mongo.py`).

## Contrato
- Señal `font_changed = Signal(object)` (emite `QFont`).
- No persistir secretos en el repositorio; los cambios en runtime actualizan `settings` en memoria (y opcionalmente `.env` si se desea más adelante).
