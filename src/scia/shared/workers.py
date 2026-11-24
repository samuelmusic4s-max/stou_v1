from datetime import date
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from scia.features.document.chat import stream_chat_reply
from scia.features.document.pipeline import generate_lesson_markdown
from scia.features.sources.chunking import split_text_into_chunks
from scia.features.sources.chunks_repo import save_chunks
from scia.features.sources.ingest import (
    copy_source_file,
    detect_source_type,
    extract_text,
    get_uploads_dir,
    remove_source_file,
)
from scia.shared.config import ModelRole, settings
from scia.shared.llm import embed
from scia.shared.models import Source
from scia.shared.mongo import ping_db

logger = logging.getLogger(__name__)

# Referencias temporales a hilos cuyo bloqueo de red/IO aún no termina al cerrar una vista,
# evitando el abort nativo "QThread: Destroyed while thread is still running".
_orphaned_workers: list[QThread] = []


def retire_worker(worker: QThread | None, timeout_ms: int = 1000) -> None:
    if worker is None:
        return
    if worker.isRunning() and not worker.wait(timeout_ms):
        worker.blockSignals(True)
        worker.setParent(None)
        _orphaned_workers.append(worker)
        return
    worker.deleteLater()


def stop_worker_safely(worker: QThread | None, timeout_ms: int = 2000) -> None:
    if worker is None:
        return
    worker.blockSignals(True)
    if worker.isRunning():
        worker.requestInterruption()
        if not worker.wait(timeout_ms):
            worker.setParent(None)
            _orphaned_workers.append(worker)
            return
    worker.deleteLater()


class IngestWorker(QThread):
    step_changed = Signal(int, str)
    finished = Signal(object)
    cancelled = Signal()
    error = Signal(str)

    def __init__(
        self,
        project_id: str,
        file_path: str | Path,
        published_date: date,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.project_id = project_id
        self.file_path = Path(file_path)
        self.published_date = published_date

    def run(self):
        copied_path: Path | None = None
        preexisting_copy = False
        try:
            source_type = detect_source_type(self.file_path)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return

            self.step_changed.emit(
                0, f"Extrayendo texto de {self.file_path.name}..."
            )
            text = extract_text(self.file_path)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return

            if not text.strip():
                raise ValueError(
                    f"No se encontró texto legible en «{self.file_path.name}» "
                    "(el archivo está vacío o es un PDF escaneado sin texto)."
                )

            self.step_changed.emit(
                1, f"Creando copia local de {self.file_path.name}..."
            )
            dest_candidate = (
                get_uploads_dir(self.project_id) / self.file_path.name
            ).resolve()
            preexisting_copy = dest_candidate.is_file()
            copied_path = copy_source_file(self.file_path, self.project_id)
            if self.isInterruptionRequested():
                if not preexisting_copy or copied_path != dest_candidate:
                    remove_source_file(copied_path, self.project_id)
                self.cancelled.emit()
                return

            self.step_changed.emit(2, "Dividiendo contenido en fragmentos...")

            source = Source(
                project_id=self.project_id,
                name=copied_path.name,
                path=str(copied_path),
                source_type=source_type,
                published_date=self.published_date,
            )

            chunks = split_text_into_chunks(
                text=text,
                project_id=self.project_id,
                source_id=source.id,
                heading=copied_path.stem,
            )
            if not chunks:
                if not preexisting_copy or copied_path != dest_candidate:
                    remove_source_file(copied_path, self.project_id)
                raise ValueError(
                    f"No se pudieron extraer fragmentos útiles de «{self.file_path.name}»."
                )

            if self.isInterruptionRequested():
                if not preexisting_copy or copied_path != dest_candidate:
                    remove_source_file(copied_path, self.project_id)
                self.cancelled.emit()
                return
            self.step_changed.emit(3, "Guardando copia y fragmentos...")

            emb_cfg = settings.get_role(ModelRole.Embeddings)
            if chunks and emb_cfg and emb_cfg.model:
                try:
                    vectors = embed(
                        [c.text for c in chunks],
                        should_cancel=self.isInterruptionRequested,
                    )
                    for chunk, vec in zip(chunks, vectors):
                        chunk.embedding = vec
                except Exception as exc:
                    logger.warning(
                        "No se pudieron generar embeddings para %s (se guardan chunks sin vector): %s",
                        self.file_path.name,
                        exc,
                    )

            if self.isInterruptionRequested():
                if not preexisting_copy or copied_path != dest_candidate:
                    remove_source_file(copied_path, self.project_id)
                self.cancelled.emit()
                return

            save_chunks(chunks)
            self.step_changed.emit(3, "Indexación completada")
            self.finished.emit(source)
        except Exception as exc:
            if copied_path is not None and not preexisting_copy:
                remove_source_file(copied_path, self.project_id)
            if not self.isInterruptionRequested():
                self.error.emit(str(exc))


class DbPingWorker(QThread):
    result = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    def run(self):
        self.result.emit(ping_db())


class LessonWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        project_id: str,
        topic: str,
        sources: list[Source],
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.project_id = project_id
        self.topic = topic
        self.sources = list(sources)

    def run(self):
        try:
            lesson = generate_lesson_markdown(
                project_id=self.project_id,
                topic=self.topic,
                sources=self.sources,
                should_cancel=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.finished.emit(lesson)
        except InterruptedError:
            return
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.error.emit(str(exc))


class ChatWorker(QThread):
    token = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        project_id: str,
        question: str,
        current_lesson_md: str = "",
        history: list[tuple[str, str]] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.project_id = project_id
        self.question = question
        self.current_lesson_md = current_lesson_md
        self.history = list(history or [])
        self.had_error: bool = False
        self.was_cancelled: bool = False

    def run(self):
        try:
            for piece in stream_chat_reply(
                project_id=self.project_id,
                question=self.question,
                current_lesson_md=self.current_lesson_md,
                history=self.history,
            ):
                if self.isInterruptionRequested():
                    self.was_cancelled = True
                    return
                self.token.emit(piece)
        except Exception as exc:
            self.had_error = True
            if self.isInterruptionRequested():
                self.was_cancelled = True
            else:
                self.error.emit(str(exc))
