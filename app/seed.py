"""
seed.py — Garante que usuários e dados essenciais existam no banco.

Executado automaticamente ao iniciar a aplicação (via create_app).
É SEGURO executar múltiplas vezes: nunca sobrescreve dados existentes.

Usuários configuráveis via variáveis de ambiente:
  ADMIN_USER / ADMIN_PASSWORD / ADMIN_FULL_NAME
  SEED_USERS  — JSON com lista de usuários adicionais, ex:
    '[{"username":"mfruttuoso","full_name":"Murilo Fruttuoso","role":"admin","password":"senha123"},
      {"username":"aprovador","full_name":"João Aprovador","role":"approver","password":"senha456"}]'
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


def seed_users(app, db):
    """
    Garante que os usuários essenciais existam no banco.
    Nunca apaga ou modifica usuários existentes — apenas CRIA os que faltam.
    """
    from app.models import User
    from config import Config

    try:
        # ── 1. Usuário admin padrão ───────────────────────────────────────────
        admin_username = Config.DEFAULT_ADMIN_USERNAME  # env: ADMIN_USER
        admin_password = Config.DEFAULT_ADMIN_PASSWORD  # env: ADMIN_PASSWORD
        admin_fullname = Config.DEFAULT_ADMIN_FULL_NAME  # env: ADMIN_FULL_NAME

        _ensure_user(
            db,
            username=admin_username,
            full_name=admin_fullname,
            password=admin_password,
            role="admin",
        )

        # ── 2. Usuários adicionais via SEED_USERS (JSON) ─────────────────────
        seed_json = os.environ.get("SEED_USERS", "")
        if seed_json:
            try:
                extra_users = json.loads(seed_json)
                for u in extra_users:
                    _ensure_user(
                        db,
                        username=u.get("username", ""),
                        full_name=u.get("full_name", u.get("username", "")),
                        password=u.get("password", ""),
                        role=u.get("role", "user"),
                    )
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning(f"SEED_USERS inválido: {exc}")

        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        logger.error(f"Erro no seed de usuários: {exc}")


def _ensure_user(db, username, full_name, password, role):
    """Cria o usuário SOMENTE se não existir. Nunca modifica existentes."""
    from app.models import User

    if not username or not password:
        return

    existing = User.query.filter_by(username=username).first()
    if existing:
        logger.debug(f"seed: usuário '{username}' já existe — ignorando.")
        return

    user = User(
        username=username,
        full_name=full_name or username,
        role=role if role in ("admin", "approver", "buyer", "requester", "user") else "user",
        is_active_user=True,
    )
    user.set_password(password)
    db.session.add(user)
    logger.info(f"seed: usuário '{username}' ({role}) criado.")
