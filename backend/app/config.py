"""Settings from environment variables, falling back to deploy/.env (dev).

Real environment variables win over the file. In Docker the file is absent and
compose passes the variables in.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / "deploy" / ".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL. The API always connects as jansetu_app (RLS applies), never as the owner.
    pghost: str = "127.0.0.1"
    pgport: int = 5432
    postgres_db: str = "jansetu"
    jansetu_app_password: SecretStr
    db_pool_size: int = 10

    # Tokens
    jwt_secret: SecretStr = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    # Login lockout
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # Comma-separated browser origins allowed to call the API (portal dev server).
    cors_origins: str = ""

    # Uploaded images (candidate photo, symbol, slip headers): <files_dir>/<workspace id>/<file id>.
    # Docker: the `files` volume at /srv/files. Laptop: a git-ignored folder.
    files_dir: Path = ROOT / "jansetu-private" / "files"

    # Background worker (app/worker.py): seconds between looks at an empty queue, and the
    # lease of a claimed job (a running job past it is taken again: its worker died).
    worker_poll_seconds: float = 2.0
    worker_lease_seconds: int = 300

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="jansetu_app",
            password=self.jansetu_app_password.get_secret_value(),
            host=self.pghost,
            port=self.pgport,
            database=self.postgres_db,
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
