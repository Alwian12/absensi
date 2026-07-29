from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Monitoring PKL"
    debug: bool = True
    database_url: str = "sqlite:///./app.db"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
