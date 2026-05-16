import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "tabibak_secret_123")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "tabibak_admin_2026")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

    DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite")
    DB_PATH = os.path.join(BASE_DIR, "tabibak.db")

    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "tabibak")
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "tabibak")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "tabibak")

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    @classmethod
    def get_db_url(cls):
        if cls.DB_ENGINE == "postgres":
            return f"postgresql://{cls.POSTGRES_USER}:{cls.POSTGRES_PASSWORD}@{cls.POSTGRES_HOST}:{cls.POSTGRES_PORT}/{cls.POSTGRES_DB}"
        return cls.DB_PATH
