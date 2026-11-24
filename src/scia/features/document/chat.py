from collections.abc import Iterator
import json
import logging

import httpx

from scia.features.sources.chunks_repo import search_relevant_chunks
from scia.shared.config import ModelRole, settings
from scia.shared.llm import (
    chat,
    chat_stream,
    decide,
    estimate_tokens,
    get_role_context_budget,
    truncate_to_tokens,
)

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    "Eres un asistente de estudio integrado en SC.IA. Responde en español de forma clara "
    "y concisa usando la lección actual y los fragmentos de las fuentes del estudiante. "
    "Si algo no está en las fuentes, indícalo con honestidad."
)

DECISION_SYSTEM_PROMPT = (
    "Eres un clasificador estricto de relevancia para SC.IA. "
    "Tu única tarea es decidir si la pregunta del estudiante tiene relación con "
    "el proyecto actual (sus fuentes indexadas o la lección abierta). "
    'Responde ÚNICAMENTE un JSON válido con el formato: {"related": true|false, "reason": "motivo breve en español"}.'
)


def _parse_bool_answer(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in ("true", "si", "sí", "yes", "1"):
            return True
        if norm in ("false", "no", "0"):
            return False
    return None


def _parse_decision_chat_response(raw: str) -> tuple[bool, str]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "related" in data:
            parsed = _parse_bool_answer(data["related"])
            if parsed is not None:
                reason = str(data.get("reason", "")).strip()
                return parsed, reason
    except json.JSONDecodeError:
        pass

    lowered = text.lower()
    if lowered.startswith(("no", "false")):
        return False, ""
    return True, ""


def _fit_chunks_to_budget(chunks: list, max_tokens: int) -> str:
    if max_tokens <= 0 or not chunks:
        return ""
    selected: list[str] = []
    used = 0
    for chunk in chunks:
        block = f"[{chunk.heading or 'Fuente'}]\n{chunk.text}"
        tokens = estimate_tokens(block) + 4
        if used + tokens <= max_tokens:
            selected.append(block)
            used += tokens
        elif not selected:
            # Al menos incluir un fragmento recortado si el primero es muy largo
            selected.append(truncate_to_tokens(block, max_tokens))
            break
        else:
            break
    return "\n\n---\n\n".join(selected)


def _fit_history_to_budget(
    history: list[tuple[str, str]] | None, max_tokens: int
) -> str:
    if not history or max_tokens <= 0:
        return ""
    max_per_turn = max(60, max_tokens // 3)
    kept_reversed: list[str] = []
    used = 0
    for role, msg in reversed(history[-6:]):
        trimmed = truncate_to_tokens(msg.strip(), max_per_turn)
        line = f"{role}: {trimmed}"
        tokens = estimate_tokens(line) + 2
        if used + tokens > max_tokens:
            break
        kept_reversed.append(line)
        used += tokens
    kept_reversed.reverse()
    return "\n".join(kept_reversed)


def check_question_relevance(
    question: str,
    sources_context: str,
    current_lesson_md: str = "",
) -> tuple[bool, str]:
    decision_cfg = settings.get_role(ModelRole.Decision)
    if not decision_cfg or not decision_cfg.model:
        return True, ""

    dec_budget = get_role_context_budget(ModelRole.Decision, reserve_output_ratio=0.25)
    fixed = estimate_tokens(DECISION_SYSTEM_PROMPT) + estimate_tokens(question) + 64
    remaining = max(120, dec_budget - fixed)
    lesson_excerpt = truncate_to_tokens(current_lesson_md, int(remaining * 0.35))
    sources_excerpt = truncate_to_tokens(sources_context, int(remaining * 0.65))

    state = (
        f"Lección abierta actualmente:\n{lesson_excerpt or '(Ninguna)'}\n\n"
        f"Fragmentos de fuentes del proyecto:\n{sources_excerpt or '(Sin fuentes)'}\n\n"
        f"Pregunta del estudiante: {question}"
    )

    # 1) Intentar endpoint /systemone si el proveedor de decisión lo soporta
    try:
        answers = decide(
            state=state,
            questions={
                "is_related": {
                    "question": "¿La pregunta del estudiante tiene relación con el proyecto, sus fuentes o la lección actual?",
                    "type": "boolean",
                }
            },
        )
        ans = _parse_bool_answer(answers.get("is_related"))
        if ans is not None:
            reason = str(answers.get("reason", "")).strip()
            return ans, reason
    except (httpx.HTTPStatusError, KeyError, ValueError, TypeError) as exc:
        logger.debug(
            "Endpoint /systemone no disponible para Decision (%s), usando chat OpenAI-compatible",
            exc,
        )
    except Exception as exc:
        logger.warning("Error llamando a decide(): %s", exc)

    # 2) Fallback estándar OpenAI-compatible usando el rol ModelRole.Decision
    try:
        raw = chat(
            ModelRole.Decision,
            DECISION_SYSTEM_PROMPT,
            state,
            temperature=0.0,
            max_tokens=120,
        )
        return _parse_decision_chat_response(raw)
    except Exception as exc:
        logger.warning(
            "No se pudo evaluar relevancia con el modelo de decisión (continuando): %s",
            exc,
        )
        return True, ""


def stream_chat_reply(
    project_id: str,
    question: str,
    current_lesson_md: str = "",
    history: list[tuple[str, str]] | None = None,
) -> Iterator[str]:
    cfg = settings.get_role(ModelRole.Generator)
    if not cfg or not cfg.model:
        raise ValueError(
            "Configura primero el modelo de chat en la pestaña Configuración."
        )

    chunks = search_relevant_chunks(project_id, question, top_k=5)

    # Presupuesto dinámico por prioridad: system + pregunta > chunks > lección > historial
    total_budget = get_role_context_budget(ModelRole.Generator)
    fixed_tokens = estimate_tokens(CHAT_SYSTEM_PROMPT) + estimate_tokens(question) + 80
    remaining = max(256, total_budget - fixed_tokens)

    chunks_budget = int(remaining * 0.50)
    lesson_budget = int(remaining * 0.30)
    history_budget = max(64, remaining - chunks_budget - lesson_budget)

    sources_context = _fit_chunks_to_budget(chunks, chunks_budget)
    lesson_excerpt = truncate_to_tokens(current_lesson_md, lesson_budget)
    history_text = _fit_history_to_budget(history, history_budget)

    is_related, reason = check_question_relevance(
        question=question,
        sources_context=sources_context,
        current_lesson_md=lesson_excerpt,
    )
    if not is_related:
        detail = f" ({reason})" if reason else ""
        yield (
            f"Tu pregunta no parece estar relacionada con el material de tu proyecto actual{detail}. "
            "Por favor, enfoca tus preguntas en las fuentes o guías de este proyecto."
        )
        return

    user_prompt = (
        f"Lección abierta actualmente:\n{lesson_excerpt or '(Ninguna)'}\n\n"
        f"Fragmentos relevantes de las fuentes:\n{sources_context or '(Sin fuentes)'}\n\n"
        f"Historial reciente:\n{history_text or '(Inicio de conversación)'}\n\n"
        f"Pregunta del estudiante: {question}"
    )

    yield from chat_stream(
        ModelRole.Generator, CHAT_SYSTEM_PROMPT, user_prompt, temperature=0.3
    )
