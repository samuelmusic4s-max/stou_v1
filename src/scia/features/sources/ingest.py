from pathlib import Path
import hashlib
import shutil
from pypdf import PdfReader

from scia.shared.models import SourceType

UPLOADS_DIR = Path.home() / ".scia" / "uploads"
LIBRARY_UPLOADS_FOLDER = "_library"


def get_uploads_dir(project_id: str) -> Path:
    folder = project_id.strip() or LIBRARY_UPLOADS_FOLDER
    return (UPLOADS_DIR / folder).resolve()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def copy_source_file(file_path: str | Path, project_id: str) -> Path:
    src = Path(file_path).resolve()
    dest_dir = get_uploads_dir(project_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.parent == dest_dir:
        return src

    dest = (dest_dir / src.name).resolve()
    if dest.is_file():
        # Si es exactamente el mismo contenido, reutilizar la ruta para reindexar sin duplicar
        if _sha256_file(src) == _sha256_file(dest):
            shutil.copy2(src, dest)
            return dest
        # Si es un archivo distinto con el mismo nombre, evitar sobrescribirlo
        counter = 2
        while True:
            candidate = (dest_dir / f"{src.stem}_{counter}{src.suffix}").resolve()
            if not candidate.exists():
                dest = candidate
                break
            if _sha256_file(src) == _sha256_file(candidate):
                dest = candidate
                break
            counter += 1

    shutil.copy2(src, dest)
    return dest


def remove_source_file(file_path: str | Path, project_id: str) -> None:
    try:
        target = Path(file_path).resolve()
        dest_dir = get_uploads_dir(project_id)
        if target.is_file() and target.parent == dest_dir:
            target.unlink(missing_ok=True)
    except OSError:
        pass


def remove_project_uploads(project_id: str) -> None:
    folder = project_id.strip()
    if not folder or folder == LIBRARY_UPLOADS_FOLDER:
        return
    try:
        dest_dir = (UPLOADS_DIR / folder).resolve()
        if dest_dir.is_dir() and dest_dir.parent == UPLOADS_DIR.resolve():
            shutil.rmtree(dest_dir, ignore_errors=True)
    except OSError:
        pass


ALLOWED_SOURCE_TYPES: tuple[SourceType, ...] = tuple(
    t for t in SourceType if t != SourceType.Video
)


def allowed_extensions() -> list[str]:
    return [f".{t.value.lower()}" for t in ALLOWED_SOURCE_TYPES]


def detect_source_type(file_path: str | Path) -> SourceType:
    path = Path(file_path)
    suffix = path.suffix.lower()
    for source_type in ALLOWED_SOURCE_TYPES:
        if suffix == f".{source_type.value.lower()}":
            return source_type
    allowed = ", ".join(allowed_extensions())
    raise ValueError(f"Formato no soportado: {suffix}. Permitidos: {allowed}")


def extract_text(file_path: str | Path) -> str:
    file_type = detect_source_type(file_path)
    if file_type == SourceType.Md or file_type == SourceType.Txt:
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")
    elif file_type == SourceType.Pdf:
        reader = PdfReader(file_path)
        return "\n\n".join([page.extract_text() or "" for page in reader.pages])
    else:
        return ""
