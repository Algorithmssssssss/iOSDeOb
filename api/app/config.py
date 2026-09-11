import os


class Settings:
    database_path: str = os.environ.get("DATABASE_PATH", "/data/app.db")
    uploads_dir: str = os.environ.get("UPLOADS_DIR", "/uploads")
    redis_url: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    max_upload_bytes: int = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024))
    internal_token: str = os.environ.get("INTERNAL_TOKEN", "dev-internal-token-change-me")


settings = Settings()
