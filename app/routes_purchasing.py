"""
Rotas do módulo de Solicitações de Compra e Cotações.
Blueprint: purchasing_bp  (prefixo /purchasing)
"""
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.decorators import admin_required
from app.extensions import db
from app.models import AccountPlan, PurchaseRequest, Quotation, User
from app.services import log_action, parse_number

_VALID_ROLES_BUYER = ("admin", "approver", "buyer")

purchasing_bp = Blueprint("purchasing", __name__, url_prefix="/purchasing")


def _approver_required(f):
    """Decorator: requer role admin ou approver."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_approver:
            abort(403)
        return f(*args, **kwargs)

    return decorated


# -----------------------------------------------------------------------
# Listagem de solicitações
# -----------------------------------------------------------------------
@purchasing_bp.route("/")
@login_required
def list_requests():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    search = request.args.get("q", "").strip()

    query = PurchaseRequest.query

    # Usuários comuns só veem suas próprias solicitações
    if not current_user.is_approver and not current_user.is_admin:
        query = query.filter_by(requester_id=current_user.id)

    if status_filter:
        query = query.filter_by(status=status_filter)
    if search:
        like = f"%{search}%"
        query = query.filter(
            PurchaseRequest.title.ilike(like)
            | PurchaseRequest.justification.ilike(like)
        )

    pagination = query.order_by(PurchaseRequest.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config.get("ITEMS_PER_PAGE", 10),
        error_out=False,
    )

    return render_template(
        "purchasing/list.html",
        pagination=pagination,
        requests=pagination.items,
        status_filter=status_filter,
        search=search,
        STATUS_LABELS={
            "draft": "Rascunho",
            "pending_quote": "Aguardando Cotação",
            "quoted": "Cotado",
            "pending_approval": "Aguardando Aprovação",
            "approved": "Aprovado",
            "rejected": "Reprovado",
            "purchased": "Comprado",
            "cancelled": "Cancelado",
        },
    )


# -----------------------------------------------------------------------
# Painel do aprovador (notificações)
# -----------------------------------------------------------------------
@purchasing_bp.route("/approvals")
@login_required
@_approver_required
def approvals_panel():
    pending = (
        PurchaseRequest.query.filter_by(status="pending_approval")
        .order_by(PurchaseRequest.created_at.asc())
        .all()
    )
    quoted = (
        PurchaseRequest.query.filter_by(status="quoted")
        .order_by(PurchaseRequest.created_at.asc())
        .all()
    )
    recent_approved = (
        PurchaseRequest.query.filter(
            PurchaseRequest.status.in_(["approved", "rejected", "purchased"])
        )
        .order_by(PurchaseRequest.updated_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "purchasing/approvals.html",
        pending=pending,
        quoted=quoted,
        recent_approved=recent_approved,
    )


# -----------------------------------------------------------------------
# Nova solicitação
# -----------------------------------------------------------------------
@purchasing_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_request():
    account_plans = AccountPlan.query.filter_by(is_active=True).order_by(
        AccountPlan.code.asc()
    ).all()
    approvers = User.query.filter(
        User.role.in_(["admin", "approver"]), User.is_active_user == True
    ).order_by(User.full_name.asc()).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        justification = request.form.get("justification", "").strip()
        items_description = request.form.get("items_description", "").strip()
        approver_id = request.form.get("approver_id", type=int)
        account_plan_id = request.form.get("account_plan_id", type=int) or None
        cost_center = request.form.get("cost_center", "").strip()
        purchase_date_str = request.form.get("purchase_date", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        installments = max(int(request.form.get("installments") or 1), 1)
        due_date = request.form.get("due_date", "").strip()
        delivery_deadline = request.form.get("delivery_deadline", "").strip()
        delivery_location = request.form.get("delivery_location", "").strip()
        purchase_type = request.form.get("purchase_type", "").strip()
        request_type = request.form.get("request_type", "").strip()
        area_team = request.form.get("area_team", "").strip()
        is_urgent = bool(request.form.get("is_urgent"))
        is_recurring = bool(request.form.get("is_recurring"))
        recurrence = request.form.get("recurrence", "").strip()
        exclusive_supplier = bool(request.form.get("exclusive_supplier"))
        exclusive_supplier_name = request.form.get("exclusive_supplier_name", "").strip()
        purchase_link_pr = request.form.get("purchase_link", "").strip()
        legale_launch = request.form.get("legale_launch", "").strip()
        legale_title = request.form.get("legale_title", "").strip()
        has_three_quotes = bool(request.form.get("has_three_quotes"))

        if not title:
            flash("Título da solicitação é obrigatório.", "danger")
            return render_template(
                "purchasing/form.html",
                account_plans=account_plans,
                approvers=approvers,
                pr=None,
            )

        purchase_date = datetime.utcnow()
        if purchase_date_str:
            try:
                purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d")
            except ValueError:
                pass

        pr = PurchaseRequest(
            title=title,
            requester_id=current_user.id,
            approver_id=approver_id or None,
            account_plan_id=account_plan_id,
            cost_center=cost_center,
            justification=justification,
            items_description=items_description,
            status="draft",
            purchase_date=purchase_date,
            payment_method=payment_method,
            installments=installments,
            due_date=due_date or None,
            delivery_deadline=delivery_deadline,
            delivery_location=delivery_location or None,
            purchase_type=purchase_type or None,
            request_type=request_type or None,
            area_team=area_team or None,
            is_urgent=is_urgent,
            is_recurring=is_recurring,
            recurrence=recurrence or None,
            exclusive_supplier=exclusive_supplier,
            exclusive_supplier_name=exclusive_supplier_name or None,
            purchase_link=purchase_link_pr or None,
            legale_launch=legale_launch or None,
            legale_title=legale_title or None,
            has_three_quotes=has_three_quotes,
        )
        db.session.add(pr)
        db.session.flush()
        log_action(
            current_user,
            "solicitacao_criada",
            f"Solicitação '{title}' criada.",
            entity_type="purchase_request",
            entity_id=pr.id,
            ip_address=request.remote_addr,
            commit=False,
        )
        db.session.commit()
        flash("Solicitação criada com sucesso.", "success")
        return redirect(url_for("purchasing.view_request", pr_id=pr.id))

    return render_template(
        "purchasing/form.html",
        account_plans=account_plans,
        approvers=approvers,
        pr=None,
    )


# -----------------------------------------------------------------------
# Visualizar solicitação
# -----------------------------------------------------------------------
@purchasing_bp.route("/<int:pr_id>")
@login_required
def view_request(pr_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    # Usuários comuns só veem suas próprias solicitações
    if not current_user.is_approver and not current_user.is_admin:
        if pr.requester_id != current_user.id:
            abort(403)
    return render_template("purchasing/detail.html", pr=pr)


# -----------------------------------------------------------------------
# Editar solicitação
# -----------------------------------------------------------------------
@purchasing_bp.route("/<int:pr_id>/edit", methods=["GET", "POST"])
@login_required
def edit_request(pr_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    if not current_user.is_admin and pr.requester_id != current_user.id:
        abort(403)
    if pr.status not in ("draft", "pending_quote"):
        flash("Solicitação não pode ser editada no status atual.", "warning")
        return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    account_plans = AccountPlan.query.filter_by(is_active=True).order_by(
        AccountPlan.code.asc()
    ).all()
    approvers = User.query.filter(
        User.role.in_(["admin", "approver"]), User.is_active_user == True
    ).order_by(User.full_name.asc()).all()

    if request.method == "POST":
        pr.title = request.form.get("title", "").strip()
        pr.justification = request.form.get("justification", "").strip()
        pr.items_description = request.form.get("items_description", "").strip()
        pr.approver_id = request.form.get("approver_id", type=int) or None
        pr.account_plan_id = request.form.get("account_plan_id", type=int) or None
        pr.cost_center = request.form.get("cost_center", "").strip()
        pr.payment_method = request.form.get("payment_method", "").strip()
        pr.installments = max(int(request.form.get("installments") or 1), 1)
        pr.due_date = request.form.get("due_date", "").strip() or None
        pr.delivery_deadline = request.form.get("delivery_deadline", "").strip()
        pr.delivery_location = request.form.get("delivery_location", "").strip() or None
        pr.purchase_type = request.form.get("purchase_type", "").strip() or None
        pr.request_type = request.form.get("request_type", "").strip() or None
        pr.area_team = request.form.get("area_team", "").strip() or None
        pr.is_urgent = bool(request.form.get("is_urgent"))
        pr.is_recurring = bool(request.form.get("is_recurring"))
        pr.recurrence = request.form.get("recurrence", "").strip() or None
        pr.exclusive_supplier = bool(request.form.get("exclusive_supplier"))
        pr.exclusive_supplier_name = request.form.get("exclusive_supplier_name", "").strip() or None
        pr.purchase_link = request.form.get("purchase_link", "").strip() or None
        pr.legale_launch = request.form.get("legale_launch", "").strip() or None
        pr.legale_title = request.form.get("legale_title", "").strip() or None
        pr.has_three_quotes = bool(request.form.get("has_three_quotes"))
        purchase_date_str = request.form.get("purchase_date", "").strip()
        if purchase_date_str:
            try:
                pr.purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d")
            except ValueError:
                pass

        if not pr.title:
            flash("Título é obrigatório.", "danger")
            return render_template(
                "purchasing/form.html", account_plans=account_plans,
                approvers=approvers, pr=pr
            )
        db.session.commit()
        flash("Solicitação atualizada.", "success")
        return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    return render_template(
        "purchasing/form.html",
        account_plans=account_plans,
        approvers=approvers,
        pr=pr,
    )


# -----------------------------------------------------------------------
# Mudar status (ação rápida)
# -----------------------------------------------------------------------
@purchasing_bp.route("/<int:pr_id>/status", methods=["POST"])
@login_required
def change_status(pr_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    new_status = request.form.get("status", "").strip()

    allowed_transitions = {
        # (current_status, new_status): roles_allowed
        ("draft", "pending_quote"): ["admin", "user", "approver"],
        ("draft", "cancelled"): ["admin", "user", "approver"],
        ("pending_quote", "quoted"): ["admin", "user", "approver"],
        ("pending_quote", "cancelled"): ["admin", "user", "approver"],
        ("quoted", "pending_approval"): ["admin", "user", "approver"],
        ("quoted", "cancelled"): ["admin", "approver"],
        ("pending_approval", "approved"): ["admin", "approver"],
        ("pending_approval", "rejected"): ["admin", "approver"],
        ("approved", "purchased"): ["admin", "approver"],
        ("approved", "cancelled"): ["admin", "approver"],
        ("rejected", "draft"): ["admin", "user", "approver"],
    }

    key = (pr.status, new_status)
    allowed_roles = allowed_transitions.get(key)

    if not allowed_roles:
        flash(f"Transição de '{pr.status}' para '{new_status}' não permitida.", "danger")
        return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    if current_user.role not in allowed_roles:
        if not (current_user.is_admin or current_user.is_approver):
            abort(403)

    # Aprovador só pode aprovar/rejeitar solicitações direcionadas a ele
    if new_status in ("approved", "rejected") and not current_user.is_admin:
        if pr.approver_id and pr.approver_id != current_user.id:
            flash("Você não é o aprovador designado para esta solicitação.", "danger")
            return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    approval_note = request.form.get("approval_note", "").strip()
    total_approved = parse_number(request.form.get("total_approved", 0))

    pr.status = new_status
    pr.updated_at = datetime.utcnow()
    if approval_note:
        pr.approval_note = approval_note
    if new_status == "approved":
        pr.approver_id = current_user.id
        pr.total_approved = total_approved or pr.total_estimated

    log_action(
        current_user,
        f"solicitacao_{new_status}",
        f"Solicitação '{pr.title}' (ID {pr_id}) passou para '{new_status}'.",
        entity_type="purchase_request",
        entity_id=pr_id,
        ip_address=request.remote_addr,
    )
    flash(f"Status alterado para '{pr.status_label}'.", "success")
    return redirect(url_for("purchasing.view_request", pr_id=pr_id))


# -----------------------------------------------------------------------
# Excluir solicitação (somente admin e rascunhos)
# -----------------------------------------------------------------------
@purchasing_bp.route("/<int:pr_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_request(pr_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    title = pr.title
    db.session.delete(pr)
    db.session.commit()
    flash(f"Solicitação '{title}' excluída.", "success")
    return redirect(url_for("purchasing.list_requests"))


# -----------------------------------------------------------------------
# COTAÇÕES
# -----------------------------------------------------------------------
@purchasing_bp.route("/<int:pr_id>/quotations/new", methods=["GET", "POST"])
@login_required
def new_quotation(pr_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    if pr.status not in ("pending_quote", "quoted", "draft"):
        flash("Não é possível adicionar cotações no status atual.", "warning")
        return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    if request.method == "POST":
        supplier = request.form.get("supplier", "").strip()
        brand = request.form.get("brand", "").strip()
        purchase_link = request.form.get("purchase_link", "").strip()
        quantity = max(parse_number(request.form.get("quantity", 1)), 0.001)
        unit_price = max(parse_number(request.form.get("unit_price", 0)), 0)
        freight = max(parse_number(request.form.get("freight", 0)), 0)
        total_value = round(quantity * unit_price + freight, 2)
        payment_method = request.form.get("payment_method", "").strip()
        delivery_deadline = request.form.get("delivery_deadline", "").strip()
        invoice_number = request.form.get("invoice_number", "").strip()
        invoice_attached = bool(request.form.get("invoice_attached"))
        notes = request.form.get("notes", "").strip()
        purchase_date_str = request.form.get("purchase_date", "").strip()
        purchase_date = datetime.utcnow()
        if purchase_date_str:
            try:
                purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d")
            except ValueError:
                pass

        if not supplier:
            flash("Fornecedor é obrigatório.", "danger")
            return render_template("purchasing/quotation_form.html", pr=pr, q=None)

        installments_q = max(int(request.form.get("installments") or 1), 1)
        q = Quotation(
            purchase_request_id=pr_id,
            supplier=supplier,
            brand=brand or None,
            purchase_link=purchase_link or None,
            quantity=quantity,
            unit_price=unit_price,
            freight=freight,
            total_value=total_value,
            payment_method=payment_method,
            installments=installments_q,
            delivery_deadline=delivery_deadline,
            invoice_number=invoice_number or None,
            invoice_attached=invoice_attached,
            notes=notes,
            purchase_date=purchase_date,
        )
        db.session.add(q)

        # Atualizar estimativa total com a cotação mais barata
        pr.total_estimated = total_value
        if pr.status == "draft":
            pr.status = "pending_quote"
        elif pr.status == "pending_quote":
            pr.status = "quoted"

        log_action(
            current_user,
            "cotacao_adicionada",
            f"Cotação de '{supplier}' adicionada à solicitação '{pr.title}'.",
            entity_type="quotation",
            ip_address=request.remote_addr,
            commit=False,
        )
        db.session.commit()
        flash("Cotação adicionada com sucesso.", "success")
        return redirect(url_for("purchasing.view_request", pr_id=pr_id))

    return render_template("purchasing/quotation_form.html", pr=pr, q=None)


@purchasing_bp.route("/<int:pr_id>/quotations/<int:q_id>/select", methods=["POST"])
@login_required
def select_quotation(pr_id, q_id):
    pr = PurchaseRequest.query.get_or_404(pr_id)
    # Unselect all
    for q in pr.quotations:
        q.is_selected = False
    # Select chosen
    chosen = Quotation.query.get_or_404(q_id)
    chosen.is_selected = True
    pr.total_estimated = chosen.total_value
    db.session.commit()
    flash(f"Cotação de '{chosen.supplier}' selecionada.", "success")
    return redirect(url_for("purchasing.view_request", pr_id=pr_id))


@purchasing_bp.route("/<int:pr_id>/quotations/<int:q_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_quotation(pr_id, q_id):
    q = Quotation.query.get_or_404(q_id)
    db.session.delete(q)
    db.session.commit()
    flash("Cotação removida.", "success")
    return redirect(url_for("purchasing.view_request", pr_id=pr_id))
