from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from scia.shared.models import Lesson, Project, Source, SourceType, Task, TaskStatus
from scia.shared.mongo import (
    get_chunks_collection,
    get_projects_collection,
    is_db_in_cooldown,
    mark_db_offline,
    reset_db_cooldown,
)

logger = logging.getLogger(__name__)


def _project_to_doc(project: Project) -> dict[str, Any]:
    return {
        "_id": project.id,
        "name": project.name,
        "created_at": project.created_at.isoformat(),
        "sources": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "name": s.name,
                "path": s.path,
                "source_type": s.source_type.value,
                "published_date": s.published_date.isoformat(),
            }
            for s in project.sources
        ],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status.value,
                "due_at": t.due_at.isoformat(),
                "estimated_minutes": t.estimated_minutes,
            }
            for t in project.tasks
        ],
        "lessons": [
            {
                "id": lesson.id,
                "title": lesson.title,
                "markdown": lesson.markdown,
                "created_at": lesson.created_at.isoformat(),
                "source_ids": list(lesson.source_ids),
            }
            for lesson in project.lessons
        ],
    }


def _doc_to_project(doc: dict[str, Any]) -> Project:
    project_id = str(doc["_id"])
    sources: list[Source] = []
    for s in doc.get("sources", []):
        try:
            sources.append(
                Source(
                    id=s["id"],
                    project_id=s.get("project_id", project_id),
                    name=s["name"],
                    path=s["path"],
                    source_type=SourceType(s["source_type"]),
                    published_date=date.fromisoformat(s["published_date"]),
                )
            )
        except Exception as exc:
            logger.warning("Fuente inválida omitida en proyecto %s: %s", project_id, exc)

    tasks: list[Task] = []
    for t in doc.get("tasks", []):
        try:
            est_raw = t.get("estimated_minutes", 30)
            est_mins = (
                est_raw
                if isinstance(est_raw, int) and not isinstance(est_raw, bool) and est_raw >= 0
                else 30
            )
            tasks.append(
                Task(
                    id=t["id"],
                    title=t["title"],
                    description=t.get("description", ""),
                    status=TaskStatus(t["status"]),
                    due_at=datetime.fromisoformat(t["due_at"]),
                    estimated_minutes=est_mins,
                )
            )
        except Exception as exc:
            logger.warning("Tarea inválida omitida en proyecto %s: %s", project_id, exc)

    lessons: list[Lesson] = []
    for l in doc.get("lessons", []):
        try:
            lessons.append(
                Lesson(
                    id=l["id"],
                    title=l["title"],
                    markdown=l.get("markdown", ""),
                    created_at=datetime.fromisoformat(l["created_at"]),
                    source_ids=list(l.get("source_ids", [])),
                )
            )
        except Exception as exc:
            logger.warning("Guía inválida omitida en proyecto %s: %s", project_id, exc)

    created_raw = doc.get("created_at")
    try:
        created_at = datetime.fromisoformat(created_raw) if created_raw else datetime.now()
    except Exception:
        created_at = datetime.now()

    return Project(
        id=project_id,
        name=doc.get("name", "Mi proyecto"),
        created_at=created_at,
        sources=sources,
        tasks=tasks,
        lessons=lessons,
    )


def save_project(project: Project) -> bool:
    if is_db_in_cooldown():
        return False
    try:
        col = get_projects_collection()
        col.replace_one({"_id": project.id}, _project_to_doc(project), upsert=True)
        reset_db_cooldown()
        return True
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudo guardar el proyecto en MongoDB: %s", exc)
        return False


def load_latest_project() -> Project | None:
    if is_db_in_cooldown():
        return None
    try:
        col = get_projects_collection()
        doc = col.find_one(sort=[("created_at", -1)])
        reset_db_cooldown()
        if doc is None:
            return None
        return _doc_to_project(doc)
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudo cargar el proyecto desde MongoDB: %s", exc)
        return None


def load_all_projects() -> list[Project]:
    if is_db_in_cooldown():
        return []
    try:
        col = get_projects_collection()
        docs = list(col.find().sort("created_at", -1))
        reset_db_cooldown()
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudieron cargar los proyectos desde MongoDB: %s", exc)
        return []

    projects: list[Project] = []
    for doc in docs:
        try:
            projects.append(_doc_to_project(doc))
        except Exception as exc:
            logger.warning("Proyecto corrupto omitido (%s): %s", doc.get("_id"), exc)
    return projects


def delete_project(project_id: str) -> bool:
    if is_db_in_cooldown():
        return False
    try:
        get_projects_collection().delete_one({"_id": project_id})
        get_chunks_collection().delete_many({"project_id": project_id})
        reset_db_cooldown()
        return True
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudo eliminar el proyecto en MongoDB: %s", exc)
        return False
