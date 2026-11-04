import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Secrets that must never be used to sign tokens/sessions in production.
_WEAK_SECRETS = {"", "change-me", "changeme", "secret", "jwt-secret", "test"}


class Settings(BaseSettings):
    app_name: str = "Monitoring PKL"
    debug: bool = True
    sql_echo: bool = False
    database_url: str = "sqlite:///./app.db"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    face_encryption_key: str | None = None
    face_max_failed_attempts: int = 5
    face_lock_minutes: int = 10
    # Cosine-similarity threshold for accepting a face match. MUST be validated
    # against a labelled test set (measured FAR/FRR), not copied from a tutorial.
    face_verify_threshold: float = 0.45
    # Minimum Laplacian variance for the (fail-closed) liveness heuristic.
    face_liveness_min_laplacian: float = 15.0
    # Standalone face ML service. When face_service_url is empty the app runs the
    # model in-process (development only); set both url + token in production.
    face_service_url: str = ""
    face_service_token: str = ""
    face_service_timeout_seconds: float = 8.0
    # Maximum accepted image payload (base64 chars) for a single capture.
    face_max_image_bytes: int = 4_000_000
    # Max face-ML requests per minute per client (used by the ML service).
    face_service_rate_per_minute: int = 120
    # Face registration quality: require several quality-checked samples whose
    # embeddings are mutually consistent before a template is stored (BAB V).
    face_register_min_samples: int = 3
    face_register_max_samples: int = 8
    face_embedding_consistency_min: float = 0.5
    # Rate limits for biometric endpoints (requests per minute). Prevents CPU
    # exhaustion and brute-force matching (audit finding F-22).
    face_rate_per_user_per_minute: int = 10
    face_rate_per_ip_per_minute: int = 30
    # Persist login throttle events in the database so limits survive restarts
    # and apply across multiple worker processes.
    rate_limit_persistent: bool = True
    # SMTP — set via .env, optional
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_enabled: bool = False
    app_base_url: str = "http://127.0.0.1:8000"

    model_config = SettingsConfigDict(env_file=".env")

    @model_validator(mode="after")
    def _enforce_secure_secret(self) -> "Settings":
        """Refuse to start in production with a weak/default signing secret (F-07)."""
        if not self.debug and self.jwt_secret_key.strip().lower() in _WEAK_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong, unique value when DEBUG=false. "
                "Set it in the .env file (see .env.example)."
            )
        return self


settings = Settings()

if settings.jwt_secret_key.strip().lower() in _WEAK_SECRETS:
    logger.warning(
        "JWT_SECRET_KEY is weak/default — set a strong secret via .env before production."
    )
if not settings.face_encryption_key:
    logger.warning(
        "FACE_ENCRYPTION_KEY is not set — biometric templates fall back to the JWT secret. "
        "Set a dedicated key in .env for production."
    )
