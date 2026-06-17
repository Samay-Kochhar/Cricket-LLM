from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_repo_env(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_duckdb_path(root: Path) -> Path:
    configured = os.getenv("DUCKDB_PATH")
    default_path = root / "data" / "odi_analytics.duckdb"
    if not configured:
        return default_path

    configured_path = Path(configured)
    if configured_path.exists():
        return configured_path

    normalized = configured.replace("\\", "/")
    if normalized.startswith("/app/"):
        remapped = root / normalized.removeprefix("/app/")
        if remapped.exists():
            return remapped

    return configured_path


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_env: str
    duckdb_path: Path
    gemini_api_key: str | None
    gemini_default_model: str
    gemini_complex_model: str
    use_semantic_analytics_v2: bool
    semantic_v2_dev_fallback: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        root = Path(__file__).resolve().parents[2]
        _load_repo_env(root)
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            duckdb_path=_resolve_duckdb_path(root),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_default_model=os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-pro"),
            gemini_complex_model=os.getenv("GEMINI_COMPLEX_MODEL", "gemini-2.5-pro"),
            use_semantic_analytics_v2=os.getenv("USE_SEMANTIC_ANALYTICS_V2", "false").lower() in {"1", "true", "yes", "on"},
            semantic_v2_dev_fallback=os.getenv("SEMANTIC_V2_DEV_FALLBACK", "true").lower() in {"1", "true", "yes", "on"},
        )
