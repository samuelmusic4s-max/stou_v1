from __future__ import annotations

import logging
import math
import threading

from scia.shared.config import ModelRole, settings
from scia.shared.llm import embed_one
from scia.shared.models import Chunk
from scia.shared.mongo import (
    get_chunks_collection,
    is_db_in_cooldown,
    mark_db_offline,
    reset_db_cooldown,
)

logger = logging.getLogger(__name__)

# Respaldo en memoria si MongoDB no está disponible
_memory_chunks: list[Chunk] = []
_chunks_lock = threading.RLock()


def _chunk_to_doc(chunk: Chunk) -> dict:
    return {
        "_id": chunk.id,
        "project_id": chunk.project_id,
        "source_id": chunk.source_id,
        "text": chunk.text,
        "position": chunk.position,
        "heading": chunk.heading,
        "embedding": chunk.embedding,
    }


def _doc_to_chunk(doc: dict) -> Chunk:
    return Chunk(
        id=doc["_id"],
        project_id=doc["project_id"],
        source_id=doc["source_id"],
        text=doc["text"],
        position=doc.get("position", 0),
        heading=doc.get("heading", ""),
        embedding=doc.get("embedding", []),
    )


def save_chunks(chunks: list[Chunk]) -> None:
    if not chunks:
        return

    # Guardar también en memoria para respuesta inmediata
    source_ids = {c.source_id for c in chunks}
    with _chunks_lock:
        _memory_chunks[:] = [c for c in _memory_chunks if c.source_id not in source_ids]
        _memory_chunks.extend(chunks)

    if is_db_in_cooldown():
        return

    try:
        col = get_chunks_collection()
        col.delete_many({"source_id": {"$in": list(source_ids)}})
        col.insert_many([_chunk_to_doc(c) for c in chunks])
        reset_db_cooldown()
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudieron guardar los chunks en MongoDB (usando respaldo en memoria): %s", exc)


def delete_chunks_by_source(source_id: str) -> None:
    with _chunks_lock:
        _memory_chunks[:] = [c for c in _memory_chunks if c.source_id != source_id]
    if is_db_in_cooldown():
        return
    try:
        get_chunks_collection().delete_many({"source_id": source_id})
        reset_db_cooldown()
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudieron eliminar los chunks en MongoDB: %s", exc)


def delete_chunks_by_project(project_id: str) -> None:
    with _chunks_lock:
        _memory_chunks[:] = [c for c in _memory_chunks if c.project_id != project_id]
    if is_db_in_cooldown():
        return
    try:
        get_chunks_collection().delete_many({"project_id": project_id})
        reset_db_cooldown()
    except Exception as exc:
        mark_db_offline()
        logger.warning("No se pudieron eliminar los chunks del proyecto en MongoDB: %s", exc)


def get_chunks_by_source(source_id: str) -> list[Chunk]:
    with _chunks_lock:
        mem_chunks = [c for c in _memory_chunks if c.source_id == source_id]

    if is_db_in_cooldown():
        return sorted(mem_chunks, key=lambda c: c.position)

    try:
        docs = list(
            get_chunks_collection()
            .find({"source_id": source_id})
            .sort([("position", 1)])
        )
        reset_db_cooldown()
        if docs:
            return [_doc_to_chunk(d) for d in docs]
    except Exception as exc:
        mark_db_offline()
        logger.debug("No se pudieron leer chunks de la fuente desde MongoDB (usando memoria): %s", exc)

    return sorted(mem_chunks, key=lambda c: c.position)


def clone_chunks_for_project(
    source_id: str, target_project_id: str, new_source_id: str
) -> list[Chunk]:
    original = get_chunks_by_source(source_id)
    if not original:
        return []

    cloned = [
        Chunk(
            project_id=target_project_id,
            source_id=new_source_id,
            text=c.text,
            position=c.position,
            heading=c.heading,
            embedding=list(c.embedding),
        )
        for c in original
    ]
    save_chunks(cloned)
    return cloned


def get_chunks_by_project(project_id: str) -> list[Chunk]:
    with _chunks_lock:
        mem_chunks = [c for c in _memory_chunks if c.project_id == project_id]

    if is_db_in_cooldown():
        return mem_chunks

    try:
        docs = list(
            get_chunks_collection()
            .find({"project_id": project_id})
            .sort([("source_id", 1), ("position", 1)])
        )
        reset_db_cooldown()
        if docs:
            db_chunks = [_doc_to_chunk(d) for d in docs]
            db_source_ids = {c.source_id for c in db_chunks}
            extra_mem = [c for c in mem_chunks if c.source_id not in db_source_ids]
            return db_chunks + extra_mem
    except Exception as exc:
        mark_db_offline()
        logger.debug("No se pudieron leer chunks desde MongoDB (usando memoria): %s", exc)

    return mem_chunks


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_relevant_chunks(project_id: str, query: str, top_k: int = 6) -> list[Chunk]:
    chunks = get_chunks_by_project(project_id)
    if not chunks:
        return []

    # 1) Si hay embeddings guardados y modelo de embeddings configurado, usar similitud coseno
    emb_cfg = settings.get_role(ModelRole.Embeddings)
    if emb_cfg and emb_cfg.model and any(c.embedding for c in chunks):
        try:
            q_vec = embed_one(query)
            scored = [(_cosine_similarity(q_vec, c.embedding), c) for c in chunks]
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [c for _, c in scored[:top_k]]
        except Exception as exc:
            logger.warning("Fallo al buscar con embeddings, usando fallback por palabras clave: %s", exc)

    # 2) Fallback simple por coincidencia de palabras clave
    words = [w for w in query.lower().split() if len(w) > 2]
    if not words:
        return chunks[:top_k]

    scored_kw = [
        (sum(1 for w in words if w in c.text.lower()), c)
        for c in chunks
    ]
    scored_kw.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored_kw[:top_k]]
