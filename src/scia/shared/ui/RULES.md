# Slice: `shared/ui/` (Contexto visual global)

Responsable del aspecto visual base, recursos embebidos y barra lateral de navegación compartida por toda la aplicación.

## Archivos
- `styles.qss`: estilos globales aplicados a `QApplication` (paleta oscura `#191919` / `#262626` / `#333333`, inputs, scrollbars, botones primarios y secundarios, `QMenuBar`, `QToolBar`, `QStatusBar`, tablas y árboles).
- `theme.py`: utilidades para cargar `styles.qss` global y combinar/aplicar el `styles.qss` específico de cada slice (`load_qss(path)`), además de constantes de fuentes/colores.
- `sidebar.py`: widget `Sidebar(QWidget)` con ancho fijo (`~190px`), título/logo `"SC.IA"` arriba y lista de botones navegables en un `QButtonGroup` (exclusivo, `checkable=True`):
  1. Inicio (`home`)
  2. Tareas (`tasks`)
  3. Lección (`document`)
  4. Test y Estadísticas (`quiz`)
  5. Subidos (`sources`)
  6. Configuración (`settings`) *(abajo del todo)*
  - Emite señal `page_selected = Signal(str)` (o `int`).
- `resources.qrc` + `icons/`: iconos compilados con `pyside6-rcc` a `resources_rc.py`.

## Reglas
- No meter lógica de negocio aquí; solo UI reutilizable y estilos.
- Usar `setObjectName(...)` en contenedores clave (`#sidebar`, `#sidebarBrand`, `#primaryButton`, `#pageTitle`, `#pageSubtitle`) para que los selectores QSS sean limpios y consistentes.
