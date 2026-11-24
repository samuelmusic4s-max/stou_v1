# Slice: `features/tasks/` (Tareas — CRUD simple)

Gestor CRUD simple y básico de tareas/retos prácticos del proyecto (referencia: pág. 5 de `diseño_anterior_base.pdf`).

## Widgets Qt obligatorios en este slice
- `QTableView` + `QStandardItemModel`: listado de tareas (Título, Estado, Fecha límite).
- `QDateTimeEdit`: fecha y hora límite al crear o editar una tarea.

## Estructura visual
- Encabezado: título serif `"Tareas"` + subtítulo `"Organiza tus tareas a tu ritmo."`.
- Barra superior: `QLineEdit` buscador (filtra filas por título), `QComboBox` filtro por estado (Todos / Pendiente / En progreso / Hecha) y botón primario blanco **Agregar nueva tarea**.
- Cuerpo: `QTableView` (selección por fila completa) + panel/formulario compacto (o diálogo) con:
  - `QLineEdit` (Título)
  - `QPlainTextEdit` o `QLineEdit` (Descripción corta)
  - `QComboBox` (`TaskStatus`)
  - `QDateTimeEdit` (Fecha límite)
  - Botones: **Guardar / Crear**, **Cambiar estado** y **Eliminar**.

## Contrato
- `load_tasks(tasks: list[Task])`
- `get_tasks() -> list[Task]`
- Señal `tasks_changed = Signal(list)` para que `HomePage` pueda reflejar las tareas pendientes actualizadas.
- Mantenerlo simple: CRUD en memoria sobre `project.tasks` (la persistencia se conecta después).
