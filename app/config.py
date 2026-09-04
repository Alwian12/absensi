from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # SMTP — set via .env, optional
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_enabled: bool = False
    app_base_url: str = "http://127.0.0.1:8000"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
