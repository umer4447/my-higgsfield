"""Settings, validated at import.

A bad or missing environment variable crashes the process at boot rather than
producing a 500 on the first request that happens to need it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["dev", "test", "staging", "prod"] = "dev"

    # Runtime uses the pooled endpoint; migrations use the direct one.
    database_url: str
    direct_database_url: str = ""
    test_database_url: str = ""
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]

    jwt_secret: SecretStr
    cursor_secret: SecretStr
    ip_hash_salt: SecretStr

    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 2_592_000

    cors_origins: str = "http://localhost:3000"

    upstream_base_url: str = "https://image.pollinations.ai/prompt/"
    upstream_timeout_seconds: float = 55.0
    upstream_tokens_per_second: float = 0.7
    upstream_bucket_capacity: int = 4

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./.storage"
    storage_public_base_url: str = "/v1/frames"
    # Required when storage_backend is "s3"; validated below rather than
    # discovered when the first frame fails to store.
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""

    max_queue_depth: int = 500
    anon_signup_credits: int = 40

    @field_validator("jwt_secret", "cursor_secret", "ip_hash_salt")
    @classmethod
    def _long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("secrets must be at least 32 characters")
        return v

    @model_validator(mode="after")
    def _anchor_storage_dir(self) -> "Settings":
        """Resolve a relative storage dir against the repo root, not the cwd.

        The API runs from api/ and the seed script from the repo root. With a
        relative path the two processes get different stores, and the symptom is
        every frame 404ing while the files plainly exist.
        """
        path = Path(self.storage_local_dir)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            object.__setattr__(
                self, "storage_local_dir", str((repo_root / path).resolve())
            )
        return self

    @model_validator(mode="after")
    def _storage_is_usable(self) -> "Settings":
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
