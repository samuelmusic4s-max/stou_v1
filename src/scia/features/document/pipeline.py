from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import re

import httpx

from scia.features.sources.chunks_repo import (
    _cosine_similarity,
    get_chunks_by_project,
    search_relevant_chunks,
)
from scia.shared.config import ModelRole, settings
from scia.shared.llm import (
    chat,
    chat_stream,
    decide,
    get_role_context_budget,
    truncate_to_tokens,
)
from scia.shared.models import Chunk, Lesson, Source

logger = logging.getLogger(__name__)

BRIDGE_SYSTEM_PROMPT = (
    "Eres un editor técnico de SC.IA. Tu única tarea es escribir un puente breve de "
    "cohesión (1 a 2 oraciones en español) para conectar dos fragmentos extraídos de libros. "
    "Reglas estrictas: NO repitas frases de los fragmentos, NO inventes datos técnicos nuevos, "
    "NO uses encabezados Markdown."
)

DECISION_PICK_SYSTEM_PROMPT = (
    "Eres el evaluador de calidad explicativa de SC.IA. "
    "Se te darán varios fragmentos candidatos sobre el mismo tema extraídos de distintas fuentes. "
    "Elige el índice (0, 1, 2, ...) del fragmento mejor explicado, más claro y completo. "
    'Responde ÚNICAMENTE un JSON válido: {"winner": 0}.'
)

MIN_LITERAL_OVERLAP = 15


@dataclass
class _MergedPassage:
    source_id: str
    source_name: str
    heading: str
    text: str
    positions: list[int]
    merged_count: int = 1


@dataclass
class AuditReport:
    total_passages: int
    intact_passages: int
    merged_overlaps: int
    bridges_count: int
    balanced_code_fences: bool
    sources_used: list[str]

    @property
    def ok(self) -> bool:
        return (
            self.total_passages > 0
            and self.intact_passages == self.total_passages
            and self.balanced_code_fences
        )


def extract_markdown_title(markdown: str, fallback: str) -> str:
    in_fence = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped.startswith("# "):
            candidate = stripped[2:].strip()
            if candidate:
                return candidate
    return fallback


def _normalize_ws_with_map(text: str) -> tuple[str, list[int]]:
    """Normaliza espacios múltiples a un solo espacio conservando el índice original."""
    out_chars: list[str] = []
    index_map: list[int] = []
    prev_space = False
    for idx, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out_chars.append(" ")
                index_map.append(idx)
                prev_space = True
        else:
            out_chars.append(ch)
            index_map.append(idx)
            prev_space = False
    return "".join(out_chars), index_map


def merge_overlapping_text(
    prev_text: str, next_text: str, max_overlap_chars: int = 400
) -> tuple[str, bool]:
    """Une dos textos consecutivos eliminando el prefijo duplicado por overlap."""
    a = prev_text.rstrip()
    b = next_text.lstrip()
    if not a:
        return b, False
    if not b:
        return a, False

    window = min(len(a), len(b), max(max_overlap_chars, settings.overlap * 8, 200))
    for length in range(window, MIN_LITERAL_OVERLAP - 1, -1):
        if a[-length:] == b[:length]:
            remainder = b[length:].lstrip()
            if not remainder:
                return a, True
            sep = "\n" if a.endswith((".", ":", ";", "!", "?")) else " "
            return f"{a}{sep}{remainder}", True

    tail_a = a[-window:]
    head_b = b[:window]
    norm_a, _ = _normalize_ws_with_map(tail_a)
    norm_b, map_b = _normalize_ws_with_map(head_b)
    max_norm = min(len(norm_a), len(norm_b))
    for length in range(max_norm, MIN_LITERAL_OVERLAP - 1, -1):
        if norm_a[-length:] == norm_b[:length]:
            cut_orig = map_b[length - 1] + 1
            remainder = b[cut_orig:].lstrip()
            if not remainder:
                return a, True
            sep = "\n" if a.endswith((".", ":", ";", "!", "?")) else " "
            return f"{a}{sep}{remainder}", True

    return f"{a}\n\n{b}", False


def _word_set(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def _jaccard_similarity(a: str, b: str) -> float:
    sa = _word_set(a)
    sb = _word_set(b)
    if not sa or not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union)


def _chunks_overlap_semantically(
    a: Chunk, b: Chunk, sim_threshold: float, jaccard_threshold: float
) -> bool:
    if a.source_id == b.source_id and abs(a.position - b.position) <= 1:
        return False
    if a.embedding and b.embedding and len(a.embedding) == len(b.embedding):
        if _cosine_similarity(a.embedding, b.embedding) >= sim_threshold:
            return True
    return _jaccard_similarity(a.text, b.text) >= jaccard_threshold


def group_overlapping_chunks(
    chunks: list[Chunk],
    sim_threshold: float = 0.85,
    jaccard_threshold: float = 0.55,
    max_group_size: int = 4,
) -> list[list[Chunk]]:
    """Agrupa chunks redundantes para que el modelo de decisión elija el mejor explicado."""
    groups: list[list[Chunk]] = []
    for chunk in chunks:
        placed = False
        for group in groups:
            if len(group) < max_group_size and _chunks_overlap_semantically(
                group[0], chunk, sim_threshold, jaccard_threshold
            ):
                group.append(chunk)
                placed = True
                break
        if not placed:
            groups.append([chunk])
    return groups


def _parse_winner_index(raw: object, count: int) -> int | None:
    if isinstance(raw, int) and 0 <= raw < count:
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("winner"), int):
                idx = data["winner"]
                if 0 <= idx < count:
                    return idx
        except json.JSONDecodeError:
            pass
        match = re.search(r"\b(\d+)\b", text)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < count:
                return idx
    return None


def select_best_chunk(candidates: list[Chunk], topic: str) -> Chunk:
    """Usa ModelRole.Decision para elegir el fragmento mejor explicado entre candidatos."""
    if len(candidates) <= 1:
        return candidates[0]

    dec_cfg = settings.get_role(ModelRole.Decision)
    if dec_cfg and dec_cfg.model:
        budget = get_role_context_budget(ModelRole.Decision, reserve_output_ratio=0.25)
        per_candidate_tokens = max(80, (budget - 200) // len(candidates))
        formatted = "\n\n".join(
            f"[Candidato {idx} — {c.heading or 'Fuente'}]\n"
            f"{truncate_to_tokens(c.text, per_candidate_tokens)}"
            for idx, c in enumerate(candidates)
        )
        state = f"Tema: {topic}\n\n{formatted}"

        try:
            answers = decide(
                state=state,
                questions={
                    "winner": {
                        "question": (
                            f"¿Qué índice de candidato (0 a {len(candidates) - 1}) "
                            "explica mejor y con mayor claridad el tema?"
                        ),
                        "type": "integer",
                        "choices": {
                            str(idx): f"Candidato {idx} ({c.heading or 'Fuente'}) explica mejor el tema."
                            for idx, c in enumerate(candidates)
                        },
                    }
                },
            )
            winner_idx = _parse_winner_index(answers.get("winner"), len(candidates))
            if winner_idx is not None:
                return candidates[winner_idx]
        except (httpx.HTTPStatusError, KeyError, ValueError, TypeError) as exc:
            logger.debug("decide() no disponible para selección (%s), usando chat", exc)
        except Exception as exc:
            logger.warning("Error en decide() seleccionando candidato: %s", exc)

        try:
            raw = chat(
                ModelRole.Decision,
                DECISION_PICK_SYSTEM_PROMPT,
                state,
                temperature=0.0,
                max_tokens=40,
            )
            winner_idx = _parse_winner_index(raw, len(candidates))
            if winner_idx is not None:
                return candidates[winner_idx]
        except Exception as exc:
            logger.warning(
                "Fallo en modelo de decisión al elegir fragmento (usando heurística): %s",
                exc,
            )

    topic_words = _word_set(topic)
    return max(
        candidates,
        key=lambda c: (
            sum(1 for w in topic_words if w in c.text.lower()),
            len(c.text),
        ),
    )


def _merge_consecutive_winners(
    winners: list[Chunk], source_names: dict[str, str]
) -> tuple[list[_MergedPassage], int]:
    """Fusiona fragmentos consecutivos de la misma fuente limpiando el overlap literal."""
    passages: list[_MergedPassage] = []
    merged_overlaps = 0

    for chunk in winners:
        src_name = source_names.get(chunk.source_id, chunk.heading or "Fuente")
        if (
            passages
            and passages[-1].source_id == chunk.source_id
            and passages[-1].positions[-1] + 1 == chunk.position
        ):
            merged_text, had_overlap = merge_overlapping_text(
                passages[-1].text, chunk.text
            )
            passages[-1].text = merged_text
            passages[-1].positions.append(chunk.position)
            passages[-1].merged_count += 1
            if had_overlap:
                merged_overlaps += 1
        else:
            passages.append(
                _MergedPassage(
                    source_id=chunk.source_id,
                    source_name=src_name,
                    heading=chunk.heading or src_name,
                    text=chunk.text.strip(),
                    positions=[chunk.position],
                )
            )
    return passages, merged_overlaps


def _generate_bridge(
    prev_text: str,
    next_text: str,
    topic: str,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """Genera un puente corto (1-2 frases) usando solo bordes de los fragmentos."""
    if should_cancel is not None and should_cancel():
        raise InterruptedError("Generación cancelada")

    tail = prev_text[-350:].strip()
    head = next_text[:350].strip()
    prompt = (
        f"Tema de la guía: {topic}\n\n"
        f"Final del fragmento anterior:\n{tail}\n\n"
        f"Inicio del fragmento siguiente:\n{head}\n\n"
        "Escribe 1 o 2 oraciones breves de transición para dar continuidad."
    )
    try:
        if should_cancel is not None:
            parts: list[str] = []
            for piece in chat_stream(
                ModelRole.Generator,
                BRIDGE_SYSTEM_PROMPT,
                prompt,
                temperature=0.2,
                max_tokens=110,
            ):
                if should_cancel():
                    raise InterruptedError("Generación cancelada")
                parts.append(piece)
            bridge = "".join(parts).strip()
        else:
            bridge = chat(
                ModelRole.Generator,
                BRIDGE_SYSTEM_PROMPT,
                prompt,
                temperature=0.2,
                max_tokens=110,
            ).strip()
        return bridge.lstrip("#").strip()
    except InterruptedError:
        raise
    except Exception as exc:
        logger.warning("No se pudo generar puente de cohesión (se omite): %s", exc)
        return ""


def audit_lesson_markdown(
    markdown: str,
    passages: list[_MergedPassage],
    merged_overlaps: int,
    bridges_count: int,
) -> tuple[str, AuditReport]:
    """Auditoría determinista en milisegundos: verifica integridad verbatim y balance de código."""
    fence_count = len(re.findall(r"^\s*```", markdown, flags=re.MULTILINE))
    fixed_md = markdown
    balanced = fence_count % 2 == 0
    if not balanced:
        fixed_md = f"{markdown.rstrip()}\n```\n"
        balanced = True

    intact = sum(1 for p in passages if p.text in fixed_md)
    sources_used = list(dict.fromkeys(p.source_name for p in passages))

    report = AuditReport(
        total_passages=len(passages),
        intact_passages=intact,
        merged_overlaps=merged_overlaps,
        bridges_count=bridges_count,
        balanced_code_fences=balanced,
        sources_used=sources_used,
    )
    return fixed_md, report


def generate_lesson_markdown(
    project_id: str,
    topic: str,
    sources: list[Source],
    should_cancel: Callable[[], bool] | None = None,
) -> Lesson:
    cfg = settings.get_role(ModelRole.Generator)
    if not cfg or not cfg.model:
        raise ValueError(
            "Configura primero el modelo de chat/lecciones en la pestaña Configuración."
        )

    lesson_topic = topic.strip() or "Guía curada del material"

    if should_cancel is not None and should_cancel():
        raise InterruptedError("Generación cancelada")

    if topic.strip():
        chunks = search_relevant_chunks(project_id, topic, top_k=12)
    else:
        chunks = get_chunks_by_project(project_id)[:12]

    if not chunks:
        raise ValueError(
            "No hay fuentes indexadas en este proyecto. Añade al menos un PDF, MD o TXT con «+ Añadir fuente»."
        )

    source_names = {s.id: s.name for s in sources}

    # 1) Guardarail de overlap semántico: agrupar chunks redundantes
    groups = group_overlapping_chunks(chunks)

    if should_cancel is not None and should_cancel():
        raise InterruptedError("Generación cancelada")

    # 2) Modelo de decisión elige el mejor explicado por grupo (en paralelo)
    max_workers = max(1, settings.max_concurrency)
    if len(groups) > 1 and any(len(g) > 1 for g in groups):
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            winners = list(
                pool.map(lambda g: select_best_chunk(g, lesson_topic), groups)
            )
    else:
        winners = [select_best_chunk(g, lesson_topic) for g in groups]

    if should_cancel is not None and should_cancel():
        raise InterruptedError("Generación cancelada")

    # 3) Guardarail de overlap literal: fusionar consecutivos de la misma fuente
    passages, merged_overlaps = _merge_consecutive_winners(winners, source_names)

    # 4) Generar puentes cortos de cohesión entre pasajes (en paralelo, mínimo contexto)
    bridge_pairs = [
        (passages[i].text, passages[i + 1].text) for i in range(len(passages) - 1)
    ]
    bridges: list[str] = []
    if bridge_pairs:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            bridges = list(
                pool.map(
                    lambda pair: _generate_bridge(
                        pair[0], pair[1], lesson_topic, should_cancel=should_cancel
                    ),
                    bridge_pairs,
                )
            )

    if should_cancel is not None and should_cancel():
        raise InterruptedError("Generación cancelada")

    # 5) Ensamblar Markdown manteniendo intactos los textos de las fuentes
    lines: list[str] = [f"# {lesson_topic}", ""]
    active_bridges = 0
    for idx, passage in enumerate(passages):
        lines.append(f"## {idx + 1}. {passage.heading}")
        lines.append(f"> *Fuente: {passage.source_name}*")
        lines.append("")
        lines.append(passage.text)
        lines.append("")
        if idx < len(bridges) and bridges[idx]:
            lines.append(f"*{bridges[idx]}*")
            lines.append("")
            active_bridges += 1

    raw_markdown = "\n".join(lines).strip()

    # 6) Auditoría determinista rápida
    final_markdown, report = audit_lesson_markdown(
        raw_markdown, passages, merged_overlaps, active_bridges
    )
    audit_footer = (
        f"\n\n---\n"
        f"*Auditoría SC.IA: {report.intact_passages}/{report.total_passages} fragmentos íntegros "
        f"de {len(report.sources_used)} fuente(s) · "
        f"{report.merged_overlaps} overlap(s) limpiado(s) · "
        f"{report.bridges_count} puente(s) de cohesión.*"
    )
    final_markdown = f"{final_markdown}{audit_footer}"

    title = extract_markdown_title(final_markdown, lesson_topic)

    return Lesson(
        title=title,
        markdown=final_markdown,
        source_ids=[s.id for s in sources],
    )
