"""
reset_products.py
=================
Zera completamente os dados de produtos, movimentações de estoque,
compras e logs de ação — MAS PRESERVA todos os usuários cadastrados.

Execute UMA VEZ antes do primeiro uso em produção:
    python reset_products.py

O script só roda se a variável de ambiente CONFIRM_RESET=yes estiver definida,
para evitar execução acidental.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from app.extensions import db
from app.models import ActionLog, Product, Purchase, StockMovement, User
from sqlalchemy import text


def reset_products():
    confirm = os.environ.get("CONFIRM_RESET", "").strip().lower()
    if confirm != "yes":
        print("⚠️  Este script apaga TODOS os produtos, movimentações, compras e logs.")
        print("    Os usuários são PRESERVADOS.")
        print()
        print("    Para confirmar, execute com a variável de ambiente:")
        print("        CONFIRM_RESET=yes python reset_products.py")
        sys.exit(1)

    app = create_app()
    with app.app_context():
        print("🔍 Verificando usuários antes do reset...")
        users = User.query.all()
        print(f"   → {len(users)} usuário(s) encontrado(s) — serão preservados:")
        for u in users:
            print(f"       id={u.id}  username={u.username}  role={u.role}  active={u.is_active_user}")

        print()
        print("🗑️  Apagando dados de estoque...")

        # Desabilita foreign key checks temporariamente (SQLite)
        db.session.execute(text("PRAGMA foreign_keys = OFF"))

        deleted_logs = db.session.query(ActionLog).delete()
        print(f"   ✓ {deleted_logs} log(s) de ação removido(s)")

        deleted_movements = db.session.query(StockMovement).delete()
        print(f"   ✓ {deleted_movements} movimentação(ões) removida(s)")

        deleted_purchases = db.session.query(Purchase).delete()
        print(f"   ✓ {deleted_purchases} compra(s) removida(s)")

        deleted_products = db.session.query(Product).delete()
        print(f"   ✓ {deleted_products} produto(s) removido(s)")

        # Reativa foreign keys
        db.session.execute(text("PRAGMA foreign_keys = ON"))

        db.session.commit()

        print()
        print("✅ Reset concluído com sucesso!")
        print(f"   Usuários preservados: {len(users)}")
        print("   Produtos, movimentações, compras e logs: ZERADOS")


if __name__ == "__main__":
    reset_products()
