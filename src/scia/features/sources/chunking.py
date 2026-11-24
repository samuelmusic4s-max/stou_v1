from langchain_text_splitters import RecursiveCharacterTextSplitter

from scia.shared.config import settings
from scia.shared.models import Chunk


def split_text_into_chunks(
    text: str, project_id: str, source_id: str, heading: str = ""
) -> list[Chunk]:
    if not text.strip():
        return []

    chunk_size = max(200, settings.length_embeddings)
    chunk_overlap = min(chunk_size // 4, max(0, settings.overlap * 5))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            r"\n\n",
            r"\n",
            # Corta en punto seguido, evitando abreviaturas comunes (etc., ej., vs., Dr., Sr.)
            r"(?<!\betc)(?<!\bej)(?<!\bvs)(?<!\bDr)(?<!\bSr)\.\s+",
            r" ",
            r"",
        ],
        is_separator_regex=True,
        keep_separator="end",
    )
    parts = splitter.split_text(text)

    return [
        Chunk(
            project_id=project_id,
            source_id=source_id,
            text=part.strip(),
            position=idx,
            heading=heading,
        )
        for idx, part in enumerate(parts)
        if part.strip()
    ]
