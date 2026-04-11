from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_env: str
    duckdb_path: Path
    gemini_api_key: str | None
    gemini_default_model: str
    gemini_complex_model: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        root = Path(__file__).resolve().parents[2]
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            duckdb_path=Path(os.getenv("DUCKDB_PATH", root / "data" / "odi_analytics.duckdb")),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_default_model=os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash"),
            gemini_complex_model=os.getenv("GEMINI_COMPLEX_MODEL", "gemini-2.5-pro"),
        )
