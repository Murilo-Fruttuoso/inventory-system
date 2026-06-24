"""
Rotas do módulo de Plano de Contas e Orçamento.
Blueprint: budget_bp  (prefixo /budget)
"""
from datetime import datetime

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
from sqlalchemy import func

from app.decorators import admin_required
from app.extensions import db
from app.models import AccountPlan, Budget, PurchaseRequest, Quotation
from app.services import log_action, parse_number

budget_bp = Blueprint("budget", __name__, url_prefix="/budget")


# -----------------------------------------------------------------------
# Dashboard de orçamento
# -----------------------------------------------------------------------
@budget_bp.route("/")
@login_required
def overview():
    year = request.args.get("year", datetime.utcnow().year, type=int)
    summary_type = request.args.get("type", "")  # DESPESAS / RECEITA / etc.

    plans = AccountPlan.query.filter_by(is_active=True).order_by(
        AccountPlan.code.asc()
    ).all()

    # Calcular total utilizado por plano (compras aprovadas/compradas)
    # Usa o total_approved da solicitação vinculada
    used_by_plan = {}
    approved_requests = PurchaseRequest.query.filter(
        PurchaseRequest.status.in_(["approved", "purchased"]),
        PurchaseRequest.account_plan_id.isnot(None),
        func.strftime("%Y", PurchaseRequest.purchase_date) == str(year),
    ).all()

    for pr in approved_requests:
        pid = pr.account_plan_id
        val = pr.total_approved or pr.total_estimated or 0
        used_by_plan[pid] = used_by_plan.get(pid, 0) + val

    # Orçamentos do ano
    budgets_by_plan = {}
    for b in Budget.query.filter_by(year=year, month=None).all():
        budgets_by_plan[b.account_plan_id] = b

    # Build summary rows
    rows = []
    for plan in plans:
        if summary_type and plan.summary != summary_type:
            continue
        budget = budgets_by_plan.get(plan.id)
        budgeted = budget.budgeted_value if budget else 0.0
        used = used_by_plan.get(plan.id, 0.0)
        available = budgeted - used
        rows.append(
            {
                "plan": plan,
                "budgeted": budgeted,
                "used": used,
                "available": available,
                "pct": round((used / budgeted * 100) if budgeted > 0 else 0, 1),
                "budget_obj": budget,
            }
        )

    # Totals
    total_budgeted = sum(r["budgeted"] for r in rows)
    total_used = sum(r["used"] for r in rows)
    total_available = total_budgeted - total_used

    unique_types = (
        db.session.query(AccountPlan.summary)
        .filter(AccountPlan.is_active == True, AccountPlan.summary.isnot(None))
        .distinct()
        .order_by(AccountPlan.summary)
        .all()
    )
    summary_types = [t[0] for t in unique_types if t[0]]

    return render_template(
        "budget/overview.html",
        rows=rows,
        year=year,
        summary_type=summary_type,
        summary_types=summary_types,
        total_budgeted=total_budgeted,
        total_used=total_used,
        total_available=total_available,
    )


# -----------------------------------------------------------------------
# Plano de Contas — CRUD
# -----------------------------------------------------------------------
@budget_bp.route("/accounts")
@login_required
def accounts_list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    acc_type = request.args.get("summary", "").strip()

    query = AccountPlan.query
    if search:
        like = f"%{search}%"
        query = query.filter(
            AccountPlan.description.ilike(like) | AccountPlan.code.ilike(like)
        )
    if acc_type:
        query = query.filter_by(summary=acc_type)

    pagination = query.order_by(AccountPlan.code.asc()).paginate(
        page=page,
        per_page=current_app.config.get("ITEMS_PER_PAGE", 20),
        error_out=False,
    )

    unique_types = (
        db.session.query(AccountPlan.summary)
        .filter(AccountPlan.is_active == True, AccountPlan.summary.isnot(None))
        .distinct()
        .order_by(AccountPlan.summary)
        .all()
    )
    summary_types = [t[0] for t in unique_types if t[0]]

    return render_template(
        "budget/accounts_list.html",
        pagination=pagination,
        accounts=pagination.items,
        search=search,
        acc_type=acc_type,
        summary_types=summary_types,
    )


@budget_bp.route("/accounts/new", methods=["GET", "POST"])
@login_required
@admin_required
def accounts_new():
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip()
        summary = request.form.get("summary", "").strip()
        totalizer = request.form.get("totalizer", "").strip()
        account_type = request.form.get("account_type", "").strip()
        cost_center = request.form.get("cost_center", "").strip()
        area = request.form.get("area", "").strip()

        if not code or not description:
            flash("Código e descrição são obrigatórios.", "danger")
            return render_template("budget/account_form.html", account=None)

        account = AccountPlan(
            code=code,
            description=description,
            summary=summary or None,
            totalizer=totalizer or None,
            account_type=account_type or None,
            cost_center=cost_center or None,
            area=area or None,
        )
        try:
            db.session.add(account)
            db.session.flush()
            log_action(
                current_user,
                "plano_contas_criado",
                f"Conta '{code} - {description}' criada.",
                entity_type="account_plan",
                entity_id=account.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Conta do plano criada com sucesso.", "success")
            return redirect(url_for("budget.accounts_list"))
        except Exception:
            db.session.rollback()
            flash("Código já cadastrado.", "danger")

    return render_template("budget/account_form.html", account=None)


@budget_bp.route("/accounts/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def accounts_edit(account_id):
    account = AccountPlan.query.get_or_404(account_id)

    if request.method == "POST":
        account.code = request.form.get("code", "").strip()
        account.description = request.form.get("description", "").strip()
        account.summary = request.form.get("summary", "").strip() or None
        account.totalizer = request.form.get("totalizer", "").strip() or None
        account.account_type = request.form.get("account_type", "").strip() or None
        account.cost_center = request.form.get("cost_center", "").strip() or None
        account.area = request.form.get("area", "").strip() or None
        account.is_active = request.form.get("is_active") == "on"

        if not account.code or not account.description:
            flash("Código e descrição são obrigatórios.", "danger")
            return render_template("budget/account_form.html", account=account)
        try:
            db.session.commit()
            flash("Conta atualizada.", "success")
            return redirect(url_for("budget.accounts_list"))
        except Exception:
            db.session.rollback()
            flash("Erro ao salvar. Verifique se o código não está duplicado.", "danger")

    return render_template("budget/account_form.html", account=account)


@budget_bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
@login_required
@admin_required
def accounts_delete(account_id):
    account = AccountPlan.query.get_or_404(account_id)
    try:
        db.session.delete(account)
        db.session.commit()
        flash(f"Conta '{account.code}' excluída.", "success")
    except Exception:
        db.session.rollback()
        flash("Não é possível excluir: existem orçamentos vinculados.", "danger")
    return redirect(url_for("budget.accounts_list"))


# -----------------------------------------------------------------------
# Orçamentos
# -----------------------------------------------------------------------
@budget_bp.route("/accounts/<int:account_id>/budget", methods=["GET", "POST"])
@login_required
@admin_required
def set_budget(account_id):
    account = AccountPlan.query.get_or_404(account_id)
    year = request.args.get("year", datetime.utcnow().year, type=int)

    budget = Budget.query.filter_by(
        account_plan_id=account_id, year=year, month=None
    ).first()

    if request.method == "POST":
        budgeted_value = max(parse_number(request.form.get("budgeted_value", 0)), 0)
        notes = request.form.get("notes", "").strip()
        year_form = request.form.get("year", year, type=int)

        if budget and budget.year == year_form:
            budget.budgeted_value = budgeted_value
            budget.notes = notes
            budget.updated_at = datetime.utcnow()
        else:
            budget = Budget(
                account_plan_id=account_id,
                year=year_form,
                month=None,
                budgeted_value=budgeted_value,
                notes=notes,
            )
            db.session.add(budget)
        try:
            db.session.commit()
            flash("Orçamento salvo com sucesso.", "success")
            return redirect(url_for("budget.overview", year=year_form))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao salvar orçamento: {e}", "danger")

    return render_template(
        "budget/budget_form.html", account=account, budget=budget, year=year
    )


# -----------------------------------------------------------------------
# Importar Plano de Contas do Excel
# -----------------------------------------------------------------------
@budget_bp.route("/accounts/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_accounts():
    if request.method == "POST":
        import os
        import pandas as pd

        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo Excel.", "danger")
            return redirect(url_for("budget.import_accounts"))

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".xlsx", ".xls"}:
            flash("Apenas arquivos .xlsx ou .xls são aceitos.", "danger")
            return redirect(url_for("budget.import_accounts"))

        try:
            df = pd.read_excel(file)
            df.columns = [str(c).strip().lower() for c in df.columns]
            created = 0
            updated = 0
            for _, row in df.fillna("").iterrows():
                code = str(row.get("plano", "")).strip()
                description = str(row.get("descrição", row.get("descricao", ""))).strip()
                if not code or not description:
                    continue

                # Clean numeric code (handles scientific notation like 1.01e10)
                try:
                    code_clean = str(int(float(code)))
                except (ValueError, OverflowError):
                    code_clean = code.replace(".0", "") if code.endswith(".0") else code

                summary = str(row.get("resumido", "")).strip() or None
                totalizer = str(row.get("totalizadora", "")).strip() or None
                account_type = str(row.get("tipo", "")).strip() or None
                cost_center = str(row.get("empresa/unidade", "")).strip() or None
                area = str(row.get("área", row.get("area", ""))).strip() or None
                budgeted_raw = row.get("orçado", row.get("orcado", 0))

                existing = AccountPlan.query.filter_by(code=code_clean).first()
                if existing:
                    existing.description = description
                    existing.summary = summary
                    existing.totalizer = totalizer
                    existing.account_type = account_type
                    if cost_center:
                        existing.cost_center = cost_center
                    if area:
                        existing.area = area
                    updated += 1
                else:
                    acc = AccountPlan(
                        code=code_clean,
                        description=description,
                        summary=summary,
                        totalizer=totalizer,
                        account_type=account_type,
                        cost_center=cost_center,
                        area=area,
                    )
                    db.session.add(acc)
                    db.session.flush()
                    created += 1

                # Seed budget if "Orçado" column has a value
                if budgeted_raw and str(budgeted_raw).strip() not in ("", "0"):
                    from app.services import parse_number as pn
                    budgeted = pn(budgeted_raw)
                    if budgeted > 0:
                        year_now = datetime.utcnow().year
                        acc_obj = AccountPlan.query.filter_by(code=code_clean).first()
                        if acc_obj:
                            b = Budget.query.filter_by(
                                account_plan_id=acc_obj.id, year=year_now, month=None
                            ).first()
                            if not b:
                                db.session.add(
                                    Budget(
                                        account_plan_id=acc_obj.id,
                                        year=year_now,
                                        month=None,
                                        budgeted_value=budgeted,
                                    )
                                )

            db.session.commit()
            flash(
                f"Importação concluída: {created} criadas, {updated} atualizadas.",
                "success",
            )
            return redirect(url_for("budget.accounts_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Erro na importação: {exc}", "danger")

    return render_template("budget/import_accounts.html")
