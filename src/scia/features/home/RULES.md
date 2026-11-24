# Slice: `features/home/` (Inicio)

Pantalla de bienvenida y resumen rápido (referencia: pág. 6 de `diseño_anterior_base.pdf`).

## Objetivo
Dar un punto de entrada tranquilo al abrir SC.IA: saludo, estado rápido de tareas pendientes, resumen del último test y acceso directo a la lección o a subir fuentes.

## Estructura visual
- Encabezado: título serif `"Buenos días"` + frase breve debajo.
- Fila superior (2 columnas):
  - Izquierda: tarjeta **Tareas pendientes** (lista corta de las próximas tareas `Pending` / `In_Progress`).
  - Derecha: tarjeta **Estadísticas de uso** (último puntaje de quiz, total de fuentes cargadas).
- Fila inferior (ancho completo):
  - Tarjeta **Toma / Arma una lección** con botones de acceso rápido que emiten señales para navegar a `document` o `sources`.

## Contrato
- Método `load_project(project: Project)` para refrescar los resúmenes.
- Señales: `navigate_requested = Signal(str)` (ej. `"document"`, `"sources"`, `"tasks"`).
- No requiere widgets complejos; mantenerlo ligero y limpio.
