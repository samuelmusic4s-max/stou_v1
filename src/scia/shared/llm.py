from collections.abc import Callable, Iterator
import logging
import math
from typing import Any

import httpx
from openai import OpenAI

from scia.shared.config import ModelRole, settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LOCAL_API_KEY = "lm-studio"
EMBED_BATCH_SIZE = 64
EMBED_MAX_BATCH_CHARS = 16000
CHARS_PER_TOKEN = 3.5

_CONTEXT_ERROR_MARKERS = (
    "context length",
    "maximum context",
    "context_length_exceeded",
    "too many tokens",
    "exceeds the context",
    "prompt is too long",
    "input length",
)

_CHAT_UNSUPPORTED_MARKERS = (
    "does not support chat",
    "not a chat model",
    "chat completions not supported",
    "use /v1/completions",
)

_MODEL_FORMAT_ERROR_MARKERS = (
    "unexpected model name format",
    "invalid model name",
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= max_chars:
        return text
    if max_chars <= 16:
        return text[:max_chars]
    cut = text[: max_chars - 1]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars * 0.7:
        cut = cut[:last_nl]
    else:
        last_sp = cut.rfind(" ")
        if last_sp > max_chars * 0.7:
            cut = cut[:last_sp]
    return cut.rstrip() + "…"


def get_role_context_budget(
    role: ModelRole, reserve_output_ratio: float = 0.25
) -> int:
    cfg = settings.get_role(role)
    total = cfg.max_context_tokens if cfg else 4096
    reserve_ratio = min(0.5, max(0.1, reserve_output_ratio))
    return max(256, int(total * (1.0 - reserve_ratio)))


def _is_context_length_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONTEXT_ERROR_MARKERS)


def _is_chat_unsupported_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _CHAT_UNSUPPORTED_MARKERS)


def _is_model_format_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _MODEL_FORMAT_ERROR_MARKERS)


_GEMINI_EMBEDDING_ALIASES: dict[str, str] = {
    "gemini embedding 1": "gemini-embedding-001",
    "gemini-embedding-1": "gemini-embedding-001",
    "gemini embedding 001": "gemini-embedding-001",
    "text embedding 4": "text-embedding-004",
    "text embedding 004": "text-embedding-004",
}

_GEMINI_DECISION_ALIASES: dict[str, str] = {
    "gemini decision 1": "gemini-decision-1",
    "models/gemini-decision-1": "gemini-decision-1",
}


def _normalize_gemini_decision_model(model: str) -> str:
    clean = model.strip()
    alias = _GEMINI_DECISION_ALIASES.get(clean.lower())
    if alias:
        return alias
    if clean.startswith("models/"):
        return clean.removeprefix("models/")
    return clean.lower().replace(" ", "-") if " " in clean else clean


def _is_gemini_decision_config(base_url: str, model: str) -> bool:
    return (
        "generativelanguage.googleapis.com" in base_url.lower()
        and "decision" in model.lower()
    )


def _embedding_model_candidates(model: str, base_url: str) -> list[str]:
    clean = model.strip()
    if not clean:
        return [clean]
    is_gemini_openai = (
        "generativelanguage.googleapis.com" in base_url.lower()
        and "openai" in base_url.lower()
    )
    raw_candidates: list[str] = []
    if is_gemini_openai:
        alias = _GEMINI_EMBEDDING_ALIASES.get(clean.lower())
        if alias:
            raw_candidates.append(alias)
        if clean.startswith("models/"):
            raw_candidates.append(clean.removeprefix("models/"))
        elif "/" in clean:
            raw_candidates.append(clean.split("/")[-1])
        if " " in clean:
            # Evitar nombres con espacios en la API de Gemini
            slug = clean.lower().replace(" ", "-")
            raw_candidates.append(_GEMINI_EMBEDDING_ALIASES.get(slug, slug))
    raw_candidates.append(clean)
    if clean.startswith("models/"):
        raw_candidates.append(clean.removeprefix("models/"))
    elif "/" in clean:
        raw_candidates.append(clean.split("/")[-1])
    elif " " not in clean:
        raw_candidates.append(f"models/{clean}")

    return list(dict.fromkeys(c for c in raw_candidates if c))


def get_llm_client(role: ModelRole) -> tuple[OpenAI, str]:
    cfg = settings.get_role(role)
    if cfg is None:
        raise ValueError(f"Rol no configurado: {role}")
    base_url = cfg.base_url.strip() or DEFAULT_BASE_URL
    api_key = cfg.api_key.strip() or DEFAULT_LOCAL_API_KEY
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=60.0,
        max_retries=1,
    )
    return client, cfg.model.strip()


def embed(
    texts: list[str],
    should_cancel: Callable[[], bool] | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    client, model = get_llm_client(ModelRole.Embeddings)
    emb_budget_chars = max(
        500,
        int(
            get_role_context_budget(ModelRole.Embeddings, reserve_output_ratio=0.1)
            * CHARS_PER_TOKEN
        ),
    )

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_chars = 0
    for raw in texts:
        item = raw[:emb_budget_chars] if len(raw) > emb_budget_chars else raw
        if current_batch and (
            len(current_batch) >= EMBED_BATCH_SIZE
            or current_chars + len(item) > EMBED_MAX_BATCH_CHARS
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += len(item)
    if current_batch:
        batches.append(current_batch)

    vectors: list[list[float]] = []
    emb_cfg = settings.get_role(ModelRole.Embeddings)
    base_url = emb_cfg.base_url if emb_cfg else ""
    candidates = _embedding_model_candidates(model, base_url)
    active_model = candidates[0]

    for batch in batches:
        if should_cancel is not None and should_cancel():
            break
        response = None
        last_exc: Exception | None = None
        tried_models = [active_model] + [c for c in candidates if c != active_model]
        for candidate_model in tried_models:
            try:
                response = client.embeddings.create(model=candidate_model, input=batch)
                active_model = candidate_model
                break
            except Exception as exc:
                last_exc = exc
                if _is_model_format_error(exc):
                    logger.debug(
                        "Formato de modelo de embeddings rechazado (%s), probando alternativa...",
                        candidate_model,
                    )
                    continue
                raise
        if response is None and last_exc is not None:
            raise last_exc
        ordered = sorted(
            enumerate(response.data),
            key=lambda pair: (
                pair[1].index
                if isinstance(getattr(pair[1], "index", None), int)
                else pair[0]
            ),
        )
        vectors.extend(item.embedding for _, item in ordered)
    return vectors


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def chat_stream(
    role: ModelRole,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> Iterator[str]:
    client, model = get_llm_client(role)
    budget = get_role_context_budget(role)
    sys_tokens = estimate_tokens(system_prompt)
    available_user_tokens = max(128, budget - sys_tokens - 32)
    current_user_prompt = truncate_to_tokens(user_prompt, available_user_tokens)

    max_retries = 2
    for attempt in range(max_retries + 1):
        yielded_any = False
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_user_prompt},
                ],
                "stream": True,
            }
            if max_tokens is not None and max_tokens > 0:
                kwargs["max_tokens"] = max_tokens

            stream = client.chat.completions.create(**kwargs)
            for event in stream:
                if event.choices and event.choices[0].delta.content:
                    yielded_any = True
                    yield event.choices[0].delta.content
            return
        except Exception as exc:
            if not yielded_any and _is_chat_unsupported_error(exc):
                logger.debug(
                    "Modelo %s no soporta chat; usando endpoint /completions", model
                )
                combined_prompt = (
                    f"{system_prompt.strip()}\n\n{current_user_prompt.strip()}\n\nRespuesta:\n"
                )
                comp_kwargs: dict[str, Any] = {
                    "model": model,
                    "prompt": combined_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens if (max_tokens is not None and max_tokens > 0) else 256,
                }
                comp_resp = client.completions.create(**comp_kwargs)
                if comp_resp.choices and getattr(comp_resp.choices[0], "text", None):
                    yield comp_resp.choices[0].text
                return
            if (
                not yielded_any
                and attempt < max_retries
                and _is_context_length_error(exc)
            ):
                new_tokens = max(128, int(estimate_tokens(current_user_prompt) * 0.6))
                logger.warning(
                    "Contexto excedido en %s (intento %d/%d); recortando prompt a ~%d tokens",
                    role.value,
                    attempt + 1,
                    max_retries,
                    new_tokens,
                )
                current_user_prompt = truncate_to_tokens(current_user_prompt, new_tokens)
                continue
            if _is_context_length_error(exc):
                raise ValueError(
                    "El contenido supera la ventana de contexto del modelo configurado. "
                    "Reduce el tamaño del texto o ajusta max_context_tokens."
                ) from exc
            raise


def chat(
    role: ModelRole,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    on_chunk: Callable[[str], None] | None = None,
    max_tokens: int | None = None,
) -> str:
    parts: list[str] = []
    for piece in chat_stream(
        role,
        system_prompt,
        user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        parts.append(piece)
        if on_chunk is not None:
            on_chunk(piece)
    return "".join(parts)


def _decide_gemini(
    base_url: str,
    api_key: str,
    model: str,
    state: str,
    questions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    clean_base = base_url.strip().rstrip("/")
    if clean_base.lower().endswith("/openai"):
        clean_base = clean_base[: -len("/openai")]
    url = f"{clean_base}/decisions"

    gemini_questions: dict[str, dict[str, Any]] = {}
    orig_types: dict[str, str] = {}
    for key, spec in questions.items():
        q_type = str(spec.get("type", "")).lower()
        orig_types[key] = q_type
        instructions = str(spec.get("instructions") or spec.get("question") or "").strip()
        if q_type in ("boolean", "noul"):
            gemini_questions[key] = {
                "type": "noul",
                "instructions": instructions,
            }
        elif q_type in ("choice", "integer"):
            criteria = spec.get("criteria") or spec.get("choices")
            if not criteria and isinstance(spec.get("options"), list):
                criteria = {str(opt): f"Opción {opt}" for opt in spec["options"]}
            if not criteria:
                raise ValueError(
                    f"La pregunta '{key}' de tipo '{q_type}' requiere 'criteria' o 'choices' para Gemini Decisions."
                )
            gemini_questions[key] = {
                "type": "choice",
                "instructions": instructions,
                "criteria": {str(k): str(v) for k, v in criteria.items()},
            }
        else:
            gemini_questions[key] = dict(spec)

    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["x-goog-api-key"] = api_key.strip()

    response = httpx.post(
        url,
        headers=headers,
        json={
            "model": _normalize_gemini_decision_model(model),
            "input": state,
            "questions": gemini_questions,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    body = response.json()
    raw_answers = body.get("answers", {})
    parsed: dict[str, Any] = {}
    for key, ans in raw_answers.items():
        if not isinstance(ans, dict):
            parsed[key] = ans
            continue
        ans_type = ans.get("type")
        if ans_type == "noul":
            parsed[key] = float(ans.get("noul", 0.0)) >= 0.5
        elif ans_type == "choice":
            choice_val = ans.get("choice")
            if orig_types.get(key) == "integer" and isinstance(choice_val, str) and choice_val.isdigit():
                parsed[key] = int(choice_val)
            else:
                parsed[key] = choice_val
        elif ans_type == "score":
            parsed[key] = ans.get("score")
        else:
            parsed[key] = ans
    return parsed


def decide(state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cfg = settings.get_role(ModelRole.Decision)
    if cfg is None:
        raise ValueError("Rol Decisión no configurado")
    base = cfg.base_url.strip().rstrip("/")
    if not base:
        raise ValueError("Base URL de Decisión vacía")

    budget = get_role_context_budget(ModelRole.Decision, reserve_output_ratio=0.2)
    safe_state = truncate_to_tokens(state, max(200, budget - 200))

    if _is_gemini_decision_config(base, cfg.model):
        return _decide_gemini(
            base_url=base,
            api_key=cfg.api_key,
            model=cfg.model,
            state=safe_state,
            questions=questions,
        )

    url = f"{base}/systemone"
    headers = {"Content-Type": "application/json"}
    if cfg.api_key.strip():
        headers["Authorization"] = f"Bearer {cfg.api_key.strip()}"
    response = httpx.post(
        url,
        headers=headers,
        json={"model": cfg.model.strip(), "state": safe_state, "questions": questions},
        timeout=20.0,
    )
    response.raise_for_status()
    body = response.json()
    return body["data"]["result"]["answers"]
