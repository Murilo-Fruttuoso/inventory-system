import os
from pathlib import Path

from flask import Flask
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from config import Config
from app.extensions import db, login_manager


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    finally:
        cursor.close()


def create_app():
    base_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_path=str(base_dir / "instance"),
        instance_relative_config=False,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config.from_object(Config)

    # GARANTE que o banco está no mesmo instance_path do Flask
    # Só usa DATABASE_URL se for PostgreSQL (evita sqlite:/// relativo do .env local)
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres"):
        # Render.com usa postgres://, SQLAlchemy requer postgresql://
        app.config["SQLALCHEMY_DATABASE_URI"] = _db_url.replace(
            "postgres://", "postgresql://", 1
        )
    else:
        # Sempre usa caminho absoluto para SQLite
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"sqlite:///{os.path.join(app.instance_path, 'estoque.db')}"
        )

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.instance_path, "backups"), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app.auth import auth_bp
    from app.routes import main_bp
    from app.routes_purchasing import purchasing_bp
    from app.routes_budget import budget_bp
    from app.routes_purchasing_import import purchasing_import_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(purchasing_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(purchasing_import_bp)

    @app.context_processor
    def inject_environment():
        from flask_login import current_user
        pending_count = 0
        try:
            if current_user.is_authenticated and current_user.is_approver:
                from app.models import PurchaseRequest
                pending_count = PurchaseRequest.query.filter_by(
                    status="pending_approval"
                ).count()
        except Exception:
            pass
        return {
            "app_name": "Controle de Estoque",
            "pending_approvals_count": pending_count,
        }

    # ── Filtro Jinja2: formata número como moeda brasileira (R$ 1.234,56) ──
    @app.template_filter("brl")
    def brl_filter(value):
        """Converte float/int para formato monetário brasileiro: R$ 1.234,56"""
        try:
            v = float(value or 0)
            # Formata com 2 casas decimais e separador de milhar
            formatted = f"{abs(v):,.2f}"          # "1,234.56"
            formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
            # "1.234,56"
            prefix = "R$ " if v >= 0 else "R$ -"
            return f"{prefix}{formatted}"
        except (TypeError, ValueError):
            return "R$ 0,00"

    with app.app_context():
        db.create_all()
        _safe_migrate(app)
        _ensure_default_admin()

    return app


def _safe_migrate(app):
    """Add new columns to existing tables without dropping anything."""
    try:
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        # --- users: add role 'approver' support (no schema change needed, just ensure column exists)
        if "users" in existing_tables:
            user_cols = [c["name"] for c in inspector.get_columns("users")]
            # role column already exists — nothing to add

        # --- purchase_requests
        if "purchase_requests" in existing_tables:
            pr_cols = [c["name"] for c in inspector.get_columns("purchase_requests")]
            _add_col_if_missing(pr_cols, "purchase_requests", "purchase_date",
                                "DATETIME DEFAULT (datetime('now'))")
            _add_col_if_missing(pr_cols, "purchase_requests", "payment_method", "VARCHAR(80)")
            _add_col_if_missing(pr_cols, "purchase_requests", "installments", "INTEGER DEFAULT 1")
            _add_col_if_missing(pr_cols, "purchase_requests", "due_date", "VARCHAR(20)")
            _add_col_if_missing(pr_cols, "purchase_requests", "delivery_deadline", "VARCHAR(80)")
            _add_col_if_missing(pr_cols, "purchase_requests", "invoice_number", "VARCHAR(80)")
            _add_col_if_missing(pr_cols, "purchase_requests", "forms_id", "VARCHAR(100)")
            _add_col_if_missing(pr_cols, "purchase_requests", "forms_submitted_at", "DATETIME")
            _add_col_if_missing(pr_cols, "purchase_requests", "total_approved",
                                "FLOAT NOT NULL DEFAULT 0.0")
            _add_col_if_missing(pr_cols, "purchase_requests", "legale_launch", "VARCHAR(100)")
            _add_col_if_missing(pr_cols, "purchase_requests", "legale_title", "VARCHAR(200)")
            _add_col_if_missing(pr_cols, "purchase_requests", "purchase_link", "TEXT")
            _add_col_if_missing(pr_cols, "purchase_requests", "is_urgent", "BOOLEAN DEFAULT 0")
            _add_col_if_missing(pr_cols, "purchase_requests", "is_recurring", "BOOLEAN DEFAULT 0")
            _add_col_if_missing(pr_cols, "purchase_requests", "recurrence", "VARCHAR(50)")
            _add_col_if_missing(pr_cols, "purchase_requests", "delivery_location", "VARCHAR(200)")
            _add_col_if_missing(pr_cols, "purchase_requests", "purchase_type", "VARCHAR(100)")
            _add_col_if_missing(pr_cols, "purchase_requests", "request_type", "VARCHAR(100)")
            _add_col_if_missing(pr_cols, "purchase_requests", "exclusive_supplier", "BOOLEAN DEFAULT 0")
            _add_col_if_missing(pr_cols, "purchase_requests", "exclusive_supplier_name", "VARCHAR(200)")
            _add_col_if_missing(pr_cols, "purchase_requests", "area_team", "VARCHAR(100)")
            _add_col_if_missing(pr_cols, "purchase_requests", "has_three_quotes", "BOOLEAN DEFAULT 0")
            _add_col_if_missing(pr_cols, "purchase_requests", "forms_status", "VARCHAR(50)")

        # --- quotations
        if "quotations" in existing_tables:
            q_cols = [c["name"] for c in inspector.get_columns("quotations")]
            _add_col_if_missing(q_cols, "quotations", "purchase_date",
                                "DATETIME DEFAULT (datetime('now'))")
            _add_col_if_missing(q_cols, "quotations", "invoice_number", "VARCHAR(80)")
            _add_col_if_missing(q_cols, "quotations", "freight", "FLOAT DEFAULT 0.0")
            _add_col_if_missing(q_cols, "quotations", "installments", "INTEGER DEFAULT 1")

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.warning(f"Migration warning (non-fatal): {exc}")


def _add_col_if_missing(existing_cols, table, col_name, col_def):
    if col_name not in existing_cols:
        try:
            db.session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            )
        except OperationalError:
            db.session.rollback()


def _ensure_default_admin():
    """
    Cria o usuário admin padrão SOMENTE se não existir nenhum usuário no banco.
    Isso garante que usuários existentes (mfruttuoso, apjesus, edonizeti) NUNCA
    sejam sobrescritos ou perdidos.
    """
    from app.models import User
    try:
        if User.query.count() > 0:
            return  # Usuários já existem — não faz nada
        admin = User(
            username=Config.DEFAULT_ADMIN_USERNAME,
            full_name=Config.DEFAULT_ADMIN_FULL_NAME,
            role="admin",
            is_active_user=True,
        )
        admin.set_password(Config.DEFAULT_ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()
    except Exception:
        db.session.rollback()
