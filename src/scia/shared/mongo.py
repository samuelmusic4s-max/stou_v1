import logging
import time

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from scia.shared.config import settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_current_url: str | None = None
_offline_until: float = 0.0
_offline_url: str | None = None

DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 1500
DEFAULT_CONNECT_TIMEOUT_MS = 1500
DEFAULT_SOCKET_TIMEOUT_MS = 4000
OFFLINE_COOLDOWN_SECONDS = 12.0


def mark_db_offline() -> None:
    global _offline_until, _offline_url
    _offline_url = settings.database_url
    _offline_until = time.monotonic() + OFFLINE_COOLDOWN_SECONDS


def reset_db_cooldown() -> None:
    global _offline_until, _offline_url
    _offline_until = 0.0
    _offline_url = None


def is_db_in_cooldown() -> bool:
    if _offline_url != settings.database_url:
        return False
    return time.monotonic() < _offline_until


def get_client() -> MongoClient:
    global _client, _current_url
    url = settings.database_url.strip() or "mongodb://localhost:27017"
    if _current_url != url or _client is None:
        if _client is not None:
            _client.close()
        _current_url = url
        reset_db_cooldown()
        _client = MongoClient(
            url,
            serverSelectionTimeoutMS=DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=DEFAULT_CONNECT_TIMEOUT_MS,
            socketTimeoutMS=DEFAULT_SOCKET_TIMEOUT_MS,
        )
    return _client


def get_db() -> Database:
    db_name = settings.database_name.strip() or "scia"
    return get_client()[db_name]


def get_projects_collection() -> Collection:
    return get_db()["projects"]


def get_sources_collection() -> Collection:
    return get_db()["sources"]


def get_chunks_collection() -> Collection:
    return get_db()["chunks"]


def ping_db() -> bool:
    reset_db_cooldown()
    try:
        get_client().admin.command("ping")
        reset_db_cooldown()
        return True
    except Exception as exc:
        mark_db_offline()
        logger.debug("Error al hacer ping a MongoDB: %s", exc)
        return False
