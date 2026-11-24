from __future__ import annotations

import logging
from datetime import date
from typing import Any

from scia.shared.models import Source, SourceType
from scia.shared.mongo import (
    get_sources_collection,
    is_db_in_cooldown,
    mark_db_offline,
    reset_db_cooldown,
)

logger = logging.getLogger(__name__)

UNASSIGNED_PROJECT_ID = ""


def _source_to_doc(source: Source) -> dict[str, Any]:
    return {
        "_id": source.id,
        "project_id": UNASSIGNED_PROJECT_ID,
        "name": source.name,
        "path": source.path,
        "source_type": source.source_type.value,
        "published_date": source.published_date.isoformat(),
    }


def _doc_to_source(doc: dict[str, Any]) -> Source:
    return Source(
        id=str(doc["_id"]),
        project_id=UNASSIGNED_PROJECT_ID,
        name=doc["name"],
        path=doc["path"],
        source_type=SourceType(doc["source_type"]),
        published_date=date.fromisoformat(doc["published_date"]),
    )


def save_uploaded_source(source: Source) -> bool:
    if is_db_in_cooldown():
        return False
    try:
        col = get_sources_collection()
        col.replace_one({"_id": source.id}, _source_to_doc(source), upsert=True)
        reset_db_cooldown()
        return True
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudo guardar la fuente en Subidos (MongoDB): %s", exc)
        return False


def delete_uploaded_source(source_id: str) -> bool:
    if is_db_in_cooldown():
        return False
    try:
        get_sources_collection().delete_one({"_id": source_id})
        reset_db_cooldown()
        return True
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudo eliminar la fuente de Subidos (MongoDB): %s", exc)
        return False


def load_uploaded_sources() -> list[Source]:
    if is_db_in_cooldown():
        return []
    try:
        col = get_sources_collection()
        docs = list(col.find())
        reset_db_cooldown()
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudieron cargar las fuentes de Subidos desde MongoDB: %s", exc)
        return []

    sources: list[Source] = []
    for doc in docs:
        try:
            sources.append(_doc_to_source(doc))
        except Exception as exc:
            logger.warning("Fuente inválida omitida en Subidos (%s): %s", doc.get("_id"), exc)
    return sources
