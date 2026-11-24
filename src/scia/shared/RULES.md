# Slice: `shared/` (Infraestructura transversal)

Módulos transversales compartidos por todos los slices en `features/`. Ningún feature debe duplicar lógica de conexión, modelos globales o clientes de IA.

## Archivos
- `config.py`: `ModelRole`, `RoleConfig`, `Settings` y singleton `settings` cargado desde `.env`.
- `models.py`: contratos de datos compartidos (`Project`, `Source`, `Chunk`, `TopicNode`, `BlockNode`, `BlockLinkedList`, `Question`, `QuizAttempt`, `Task`, `TaskStatus`).
- `llm.py`: cliente agnóstico OpenAI-compatible por rol (`embed`, `chat`, `chat_stream`, `decide`).
- `mongo.py`: conexión MongoDB (`get_client`, `get_db`, `get_*_collection`, `ping_db`).
- `projects_repo.py`: guardar/cargar `Project` completo en MongoDB.
- `project_xml.py`: exportar/importar `Project` en XML (respaldo y plan B de demo).
- `workers.py`: hilos `QThread` (`PipelineWorker`, `ChatWorker`) para ejecutar operaciones lentas sin congelar la UI.
- `ui/`: componentes visuales globales, tema, estilos base, sidebar e iconos (`QResource`). Ver `shared/ui/RULES.md`.

## Reglas
- `shared/` **nunca** importa código de `features/` (excepto `workers.py` al orquestar servicios de dominio cuando se conecte el backend).
- No meter vistas ni lógica específica de una sola pantalla aquí.
