from dotenv import load_dotenv
from enum import StrEnum
from dataclasses import dataclass, field
import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path

load_dotenv()

logger = logging.getLogger(__name__)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_buf = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), in_buf)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), "SC.IASettings", None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_buf = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), in_buf)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


def _read_existing_local_key(config_path: Path) -> bytes:
    env_secret = os.getenv("SCIA_SECRET_KEY")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()

    key_path = config_path.with_name(".scia.key")
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
    raise ValueError("Llave local de descifrado (.scia.key) no encontrada o inválida")


def _get_or_create_local_key(config_path: Path) -> bytes:
    env_secret = os.getenv("SCIA_SECRET_KEY")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()

    key_path = config_path.with_name(".scia.key")
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]

    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    if os.name != "nt":
        os.chmod(key_path, 0o600)
    return key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            enc_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _encrypt_bytes(plaintext: bytes, config_path: Path) -> dict[str, object]:
    if os.name == "nt":
        try:
            protected = _dpapi_protect(plaintext)
            return {
                "version": 1,
                "scheme": "dpapi",
                "payload": base64.b64encode(protected).decode("ascii"),
            }
        except Exception as exc:
            logger.warning("DPAPI no disponible, usando cifrado local: %s", exc)

    master = _get_or_create_local_key(config_path)
    nonce = os.urandom(16)
    enc_key = hashlib.sha256(master + b"enc").digest()
    mac_key = hashlib.sha256(master + b"mac").digest()
    stream = _keystream(enc_key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    blob = nonce + tag + ciphertext
    return {
        "version": 1,
        "scheme": "hmac-ctr-v1",
        "payload": base64.b64encode(blob).decode("ascii"),
    }


def _decrypt_envelope(envelope: dict, config_path: Path) -> bytes:
    scheme = envelope.get("scheme")
    payload_b64 = envelope.get("payload")
    if not isinstance(payload_b64, str):
        raise ValueError("Payload cifrado inválido")

    blob = base64.b64decode(payload_b64.encode("ascii"))

    if scheme == "dpapi":
        if os.name != "nt":
            raise ValueError("El archivo fue cifrado con Windows DPAPI")
        return _dpapi_unprotect(blob)

    if scheme == "hmac-ctr-v1":
        if len(blob) < 48:
            raise ValueError("Payload cifrado truncado")
        nonce = blob[:16]
        tag = blob[16:48]
        ciphertext = blob[48:]
        master = _read_existing_local_key(config_path)
        enc_key = hashlib.sha256(master + b"enc").digest()
        mac_key = hashlib.sha256(master + b"mac").digest()
        expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("Integridad de configuración inválida (archivo modificado)")
        stream = _keystream(enc_key, nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream))

    raise ValueError(f"Esquema de cifrado no soportado: {scheme}")


class ModelRole(StrEnum):
    Embeddings = "Embeddings"
    Decision = "Decision"
    Generator = "Generator"
    Repair = "Repair"


@dataclass
class RoleConfig:
    base_url: str
    api_key: str
    model: str
    max_context_tokens: int = 4096


@dataclass
class Settings:
    database_url: str
    length_embeddings: int
    overlap: int
    database_name: str = "scia"
    max_concurrency: int = 4
    roles: dict[ModelRole, RoleConfig] = field(default_factory=dict)

    def get_role(self, role: ModelRole) -> RoleConfig | None:
        if not isinstance(role, ModelRole):
            return None
        return self.roles.get(role)

    def update_role(
        self,
        role: ModelRole,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_context_tokens: int | None = None,
    ) -> None:
        if not isinstance(role, ModelRole):
            return
        current_model = self.roles.get(role)
        if current_model is None:
            current_model = RoleConfig(base_url="", api_key="", model="")
        if base_url is not None:
            current_model.base_url = base_url
        if api_key is not None:
            current_model.api_key = api_key
        if model is not None:
            current_model.model = model
        if max_context_tokens is not None and _is_int(max_context_tokens) and max_context_tokens >= 512:
            current_model.max_context_tokens = max_context_tokens
        self.roles[role] = current_model

    def update_all_roles(self, base_url: str, api_key: str | None = None) -> None:
        for role in ModelRole:
            self.update_role(role, base_url=base_url, api_key=api_key)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def get_config_path() -> Path:
    override = os.getenv("SCIA_CONFIG_PATH")
    if override:
        return Path(override)
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "SC.IA" / "settings.json"
    return Path.home() / ".config" / "scia" / "settings.json"


def _apply_persisted_settings(cfg: Settings, path: Path | None = None) -> None:
    config_path = path or get_config_path()
    if not config_path.exists():
        return
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        if "scheme" in raw and "payload" in raw:
            decrypted = _decrypt_envelope(raw, config_path)
            raw = json.loads(decrypted.decode("utf-8"))
            if not isinstance(raw, dict):
                return
    except Exception as exc:
        logger.warning("No se pudo leer la configuración persistida (%s): %s", config_path, exc)
        return

    if isinstance(raw.get("database_url"), str) and raw["database_url"].strip():
        cfg.database_url = raw["database_url"].strip()
    if isinstance(raw.get("database_name"), str) and raw["database_name"].strip():
        cfg.database_name = raw["database_name"].strip()
    if _is_int(raw.get("max_concurrency")) and raw["max_concurrency"] > 0:
        cfg.max_concurrency = raw["max_concurrency"]
    if _is_int(raw.get("length_embeddings")) and raw["length_embeddings"] > 0:
        cfg.length_embeddings = raw["length_embeddings"]
    if _is_int(raw.get("overlap")) and raw["overlap"] >= 0:
        cfg.overlap = raw["overlap"]

    roles_data = raw.get("roles")
    if isinstance(roles_data, dict):
        for role in ModelRole:
            role_raw = roles_data.get(role.value)
            if isinstance(role_raw, dict):
                cfg.update_role(
                    role,
                    base_url=role_raw.get("base_url") if isinstance(role_raw.get("base_url"), str) else None,
                    api_key=role_raw.get("api_key") if isinstance(role_raw.get("api_key"), str) else None,
                    model=role_raw.get("model") if isinstance(role_raw.get("model"), str) else None,
                    max_context_tokens=(
                        role_raw.get("max_context_tokens")
                        if _is_int(role_raw.get("max_context_tokens"))
                        else None
                    ),
                )


def save_settings(cfg: Settings | None = None, path: Path | None = None) -> bool:
    target = cfg or settings
    config_path = path or get_config_path()
    payload = {
        "database_url": target.database_url,
        "database_name": target.database_name,
        "max_concurrency": target.max_concurrency,
        "length_embeddings": target.length_embeddings,
        "overlap": target.overlap,
        "roles": {
            role.value: {
                "base_url": rc.base_url,
                "api_key": rc.api_key,
                "model": rc.model,
                "max_context_tokens": rc.max_context_tokens,
            }
            for role, rc in target.roles.items()
        },
    }
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        envelope = _encrypt_bytes(plaintext, config_path)
        config_path.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if os.name != "nt":
            os.chmod(config_path, 0o600)
        return True
    except Exception as exc:
        logger.warning("No se pudo guardar la configuración en %s: %s", config_path, exc)
        return False


def load_role_from_env(role: ModelRole) -> RoleConfig:
    prefix = role.upper()
    default_url = os.getenv("DEFAULT_BASE_URL", "http://localhost:1234/v1")
    default_key = os.getenv("DEFAULT_API_KEY", "lm-studio")
    default_ctx = max(512, _env_int("DEFAULT_MAX_CONTEXT_TOKENS", 4096))
    return RoleConfig(
        base_url=os.getenv(f"{prefix}_BASE_URL", default_url),
        api_key=os.getenv(f"{prefix}_API_KEY", default_key),
        model=os.getenv(f"{prefix}_MODEL", ""),
        max_context_tokens=max(512, _env_int(f"{prefix}_MAX_CONTEXT_TOKENS", default_ctx)),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Variable %s=%r inválida; usando valor por defecto %d", name, raw, default
        )
        return default


def load_settings(config_path: Path | None = None) -> Settings:
    roles = {}
    for role in ModelRole:
        roles[role] = load_role_from_env(role)

    cfg = Settings(
        database_url=os.getenv("DATABASE_URL", "mongodb://localhost:27017") or "mongodb://localhost:27017",
        database_name=os.getenv("DATABASE_NAME", "scia") or "scia",
        max_concurrency=max(1, _env_int("MAX_CONCURRENCY", 4)),
        roles=roles,
        length_embeddings=max(50, _env_int("MAX_LENGTH_EMBEDDINGS", 900)),
        overlap=max(0, _env_int("OVERLAP_WORDS", 20)),
    )
    _apply_persisted_settings(cfg, path=config_path)
    return cfg


settings = load_settings()
