import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# load_dotenv NÃO sobrescreve variáveis já definidas no ambiente (override=False)
# Isso garante que as env vars do Render têm precedência sobre o .env local
load_dotenv(BASE_DIR / ".env", override=False)

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _build_db_uri():
    """
    Determina o URI do banco de dados:
    - Se DATABASE_URL começa com 'postgres': usa PostgreSQL (Render)
    - Caso contrário: SQLite local com caminho absoluto
    """
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres"):
        # Render usa postgres://, SQLAlchemy requer postgresql://
        return url.replace("postgres://", "postgresql://", 1)
    # SQLite local — sempre caminho absoluto
    return f"sqlite:///{INSTANCE_DIR / 'estoque.db'}"


def _build_engine_options():
    """
    Opções de conexão adequadas para cada banco.
    SQLite e PostgreSQL têm connect_args diferentes.
    """
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres"):
        # PostgreSQL: sem connect_args especiais, apenas pool
        return {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 5,
            "max_overflow": 10,
        }
    else:
        # SQLite: check_same_thread e timeout
        return {
            "connect_args": {"check_same_thread": False, "timeout": 30},
            "pool_pre_ping": True,
        }


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "altere-esta-chave-em-producao")

    SQLALCHEMY_DATABASE_URI = _build_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options()

    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", 10))
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    DEFAULT_ADMIN_FULL_NAME = os.getenv("ADMIN_FULL_NAME", "Administrador")
