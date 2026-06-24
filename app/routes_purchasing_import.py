"""
Importação em lote de Solicitações de Compra a partir de planilha Excel.
Campos aceitos são exatamente os do Microsoft Forms exportado.
Blueprint: purchasing_bp  (prefixo /purchasing  — registrado no __init__.py)
"""
import os
from datetime import datetime

import pandas as pd
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.decorators import buyer_required
from app.extensions import db
from app.models import AccountPlan, PurchaseRequest, User
from app.services import log_action, parse_number

purchasing_import_bp = Blueprint(
    "purchasing_import", __name__, url_prefix="/purchasing"
)

# Mapeamento: coluna do Excel → campo interno (case-insensitive normalizado)
FORMS_COLUMN_MAP = {
    "id": "forms_id",
    "hora de conclusão": "forms_submitted_at",
    "email": "_email_ignore",
    "nome": "title_from_name",
    "área/equipe do solicitante": "area_team",
    "fornecedor exclusivo?": "exclusive_supplier",
    "nome do fornecedor exclusivo": "exclusive_supplier_name",
    "tipo de compra": "purchase_type",
    "a compra é urgente?": "is_urgent",
    "a compra é recorrente?": "is_recurring",
    "periodicidade": "recurrence",
    "local de entrega": "delivery_location",
    "tipo de solicitação": "request_type",
    "justificativa": "justification",
    "itens (produto/material/serviço)": "items_description",
    "nome do aprovador": "_approver_name",
    "arquivo aprovação": "_ignore",
    "planilha detalhada": "_ignore",
    "3 orçamentos?": "has_three_quotes",
    "status aprovação": "forms_status",
    "nome aprovador": "_approver_name",
    "data aprovação": "_ignore",
    "fornecedor final": "_supplier_final",
    "status compra": "_status_map",
    "data da compra": "purchase_date",
    "valor total": "total_estimated",
    "forma de pagamento": "payment_method",
    "quantidade parcelas": "installments",
    "nota fiscal": "invoice_number",
    "data vencimento": "due_date",
    "data entrega": "delivery_deadline",
    "lançamento legale": "legale_launch",
    "título legale": "legale_title",
    "link compra": "purchase_link",
}

STATUS_MAP = {
    "comprado": "purchased",
    "aprovado": "approved",
    "reprovado": "rejected",
    "aguardando aprovação": "pending_approval",
    "em cotação": "pending_quote",
    "cotado": "quoted",
    "rascunho": "draft",
    "cancelado": "cancelled",
}


def _normalize_col(c):
    return str(c).strip().lower()


def _parse_bool(val):
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("sim", "yes", "true", "1", "s", "y")


def _parse_date(val):
    if not val or str(val).strip() in ("", "nan", "NaT"):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(val).strip()[:19], fmt)
        except ValueError:
            continue
    return None


@purchasing_import_bp.route("/import", methods=["GET", "POST"])
@login_required
@buyer_required
def import_requests():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo Excel.", "danger")
            return redirect(url_for("purchasing_import.import_requests"))

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".xlsx", ".xls"}:
            flash("Apenas arquivos .xlsx ou .xls são aceitos.", "danger")
            return redirect(url_for("purchasing_import.import_requests"))

        try:
            df = pd.read_excel(file)
            # Normalizar colunas
            df.columns = [_normalize_col(c) for c in df.columns]
            df = df.fillna("")

            created = 0
            skipped = 0
            errors = []

            for idx, row in df.iterrows():
                row_num = idx + 2  # Excel row number (1-based + header)
                try:
                    # forms_id — chave de deduplicação
                    forms_id = str(row.get("id", "")).strip()
                    # Pular se já importado
                    if forms_id:
                        existing = PurchaseRequest.query.filter_by(
                            forms_id=forms_id
                        ).first()
                        if existing:
                            skipped += 1
                            continue

                    # Title: usa "Nome" como título ou monta título genérico
                    name_val = str(row.get("nome", "")).strip()
                    items_val = str(row.get("itens (produto/material/serviço)", "")).strip()
                    title = name_val or items_val or f"Importado linha {row_num}"

                    # Data da compra
                    purchase_date = _parse_date(row.get("data da compra")) or datetime.utcnow()

                    # Aprovador por nome
                    approver_id = None
                    approver_name = str(row.get("nome do aprovador", row.get("nome aprovador", ""))).strip()
                    if approver_name:
                        u = User.query.filter(
                            User.full_name.ilike(f"%{approver_name}%"),
                            User.role.in_(["admin", "approver"]),
                        ).first()
                        if u:
                            approver_id = u.id

                    # Status
                    status_raw = str(row.get("status compra", "")).strip().lower()
                    status = STATUS_MAP.get(status_raw, "draft")

                    # Valores numéricos
                    total_raw = row.get("valor total", 0)
                    try:
                        total_estimated = float(str(total_raw).replace(",", ".").replace("r$", "").strip() or 0)
                    except (ValueError, TypeError):
                        total_estimated = 0.0

                    installments_raw = row.get("quantidade parcelas", 1)
                    try:
                        installments = max(int(float(str(installments_raw) or 1)), 1)
                    except (ValueError, TypeError):
                        installments = 1

                    pr = PurchaseRequest(
                        title=title,
                        requester_id=current_user.id,
                        approver_id=approver_id,
                        status=status,
                        justification=str(row.get("justificativa", "")).strip() or None,
                        items_description=items_val or None,
                        purchase_date=purchase_date,
                        payment_method=str(row.get("forma de pagamento", "")).strip() or None,
                        installments=installments,
                        due_date=str(row.get("data vencimento", "")).strip() or None,
                        delivery_deadline=str(row.get("data entrega", "")).strip() or None,
                        delivery_location=str(row.get("local de entrega", "")).strip() or None,
                        purchase_type=str(row.get("tipo de compra", "")).strip() or None,
                        request_type=str(row.get("tipo de solicitação", "")).strip() or None,
                        area_team=str(row.get("área/equipe do solicitante", "")).strip() or None,
                        is_urgent=_parse_bool(row.get("a compra é urgente?")),
                        is_recurring=_parse_bool(row.get("a compra é recorrente?")),
                        recurrence=str(row.get("periodicidade", "")).strip() or None,
                        exclusive_supplier=_parse_bool(row.get("fornecedor exclusivo?")),
                        exclusive_supplier_name=str(row.get("nome do fornecedor exclusivo", "")).strip() or None,
                        purchase_link=str(row.get("link compra", "")).strip() or None,
                        legale_launch=str(row.get("lançamento legale", "")).strip() or None,
                        legale_title=str(row.get("título legale", "")).strip() or None,
                        invoice_number=str(row.get("nota fiscal", "")).strip() or None,
                        has_three_quotes=_parse_bool(row.get("3 orçamentos?")),
                        forms_status=str(row.get("status aprovação", "")).strip() or None,
                        forms_id=forms_id or None,
                        total_estimated=total_estimated,
                    )
                    db.session.add(pr)
                    created += 1

                except Exception as e:
                    errors.append(f"Linha {row_num}: {e}")
                    continue

            db.session.commit()

            if created:
                log_action(
                    current_user,
                    "importacao_solicitacoes",
                    f"Importação em lote: {created} criadas, {skipped} ignoradas.",
                    ip_address=request.remote_addr,
                )
            msg = f"Importação concluída: {created} criadas, {skipped} já existiam."
            if errors:
                msg += f" {len(errors)} erros (ver abaixo)."
            flash(msg, "success" if not errors else "warning")
            if errors:
                for e in errors[:10]:
                    flash(e, "danger")
            return redirect(url_for("purchasing.list_requests"))

        except Exception as exc:
            db.session.rollback()
            flash(f"Erro ao processar arquivo: {exc}", "danger")

    return render_template(
        "purchasing/import_requests.html",
        FORMS_FIELDS=list(FORMS_COLUMN_MAP.keys()),
    )
