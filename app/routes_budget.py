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

from app.decorators import admin_required, buyer_required
from app.extensions import db
from app.models import AccountPlan, Budget, MonthlyBudget, PurchaseRequest, Quotation
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


# -----------------------------------------------------------------------
# Importar Orçamento Mensal (Orçamento Despesas - Mês YYYY.xlsx)
# -----------------------------------------------------------------------
@budget_bp.route("/monthly/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_monthly():
    if request.method == "POST":
        import os
        import pandas as pd

        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo Excel.", "danger")
            return redirect(url_for("budget.import_monthly"))

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".xlsx", ".xls"}:
            flash("Apenas arquivos .xlsx ou .xls são aceitos.", "danger")
            return redirect(url_for("budget.import_monthly"))

        month_form = request.form.get("month", type=int) or datetime.utcnow().month
        year_form = request.form.get("year", type=int) or datetime.utcnow().year

        try:
            # O arquivo tem uma linha de título na row 0 ("ORÇAMENTO DESPESAS - JUNHO 2026")
            # e os cabeçalhos reais na row 1 — por isso usamos header=1
            # Tentamos header=1 primeiro; se não encontrar "CÓDIGO DO PLANO", tentamos header=0
            df = pd.read_excel(file, header=1)
            cols_upper = [str(c).strip().upper() for c in df.columns]
            if not any("CÓDIGO" in c or "CODIGO" in c for c in cols_upper):
                # Fallback: ler com header=0 e verificar se primeira linha é o cabeçalho real
                file.seek(0)
                df = pd.read_excel(file, header=0)
                first_row = df.iloc[0]
                if str(first_row.iloc[0]).strip().upper().startswith("CÓDIGO"):
                    df.columns = [str(v).strip() for v in first_row.values]
                    df = df.iloc[1:].reset_index(drop=True)

            # Normalizar colunas para UPPERCASE sem espaços extras
            # Também remover dois-pontos finais (ex: "ORÇADO - JUNHO:" → "ORÇADO - JUNHO")
            df.columns = [str(c).strip().upper().rstrip(":").strip() for c in df.columns]
            df = df.fillna("")

            created = 0
            updated = 0

            # Nomes de colunas possíveis para cada valor (após rstrip ":")
            month_names_pt = {
                1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
                5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
                9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
            }
            month_name = month_names_pt.get(month_form, str(month_form).zfill(2))

            def _col_val(row, *candidates):
                """Retorna o valor da primeira coluna candidata encontrada na row."""
                for c in candidates:
                    if c in row.index:
                        return row[c]
                return 0

            for _, row in df.iterrows():
                code_raw = str(_col_val(row, "CÓDIGO DO PLANO", "CODIGO DO PLANO")).strip()
                if not code_raw or code_raw in ("nan", "NAN", ""):
                    continue

                # Limpar código numérico (pode vir como float, ex: 2.0301e+10)
                try:
                    code = str(int(float(code_raw)))
                except (ValueError, OverflowError):
                    code = code_raw.replace(".0", "") if code_raw.endswith(".0") else code_raw

                plan = AccountPlan.query.filter_by(code=code).first()
                if not plan:
                    continue  # ignorar códigos sem cadastro

                def to_float(val):
                    try:
                        s = str(val).replace(",", ".").strip()
                        if not s or s.lower() in ("nan", ""):
                            return 0.0
                        return abs(float(s))
                    except (ValueError, TypeError):
                        return 0.0

                # Candidatos para cada coluna (o arquivo usa "ORÇADO - JUNHO" ou "ORÇADO - JUNHO:")
                budgeted = to_float(_col_val(
                    row,
                    f"ORÇADO - {month_name}",
                    f"ORÇADO - {str(month_form).zfill(2)}",
                    "ORÇADO",
                ))
                adjusted = to_float(_col_val(
                    row,
                    f"AJUSTADO - {month_name}",
                    f"AJUSTADO - {str(month_form).zfill(2)}",
                    "AJUSTADO",
                ))
                realized = to_float(_col_val(
                    row,
                    f"REALIZADO E PROJETADO {month_name}",
                    f"REALIZADO/PROJETADO {month_name}",
                    "REALIZADO E PROJETADO",
                    "REALIZADO/PROJETADO",
                    "REALIZADO",
                ))

                mb = MonthlyBudget.query.filter_by(
                    account_plan_id=plan.id, year=year_form, month=month_form
                ).first()
                if mb:
                    mb.budgeted_value = budgeted
                    mb.adjusted_value = adjusted
                    mb.realized_value = realized
                    mb.updated_at = datetime.utcnow()
                    updated += 1
                else:
                    db.session.add(MonthlyBudget(
                        account_plan_id=plan.id,
                        year=year_form,
                        month=month_form,
                        budgeted_value=budgeted,
                        adjusted_value=adjusted,
                        realized_value=realized,
                    ))
                    created += 1

            db.session.commit()
            flash(
                f"Orçamento mensal importado: {created} criados, {updated} atualizados "
                f"para {month_form:02d}/{year_form}.",
                "success",
            )
            return redirect(url_for("budget.budget_report"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Erro na importação: {exc}", "danger")

    months = [(i, m) for i, m in enumerate(
        ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"], start=1
    )]
    return render_template("budget/import_monthly.html",
                           months=months,
                           current_month=datetime.utcnow().month,
                           current_year=datetime.utcnow().year)


# -----------------------------------------------------------------------
# Relatório Consolidado — Orçado vs Realizado
# -----------------------------------------------------------------------
@budget_bp.route("/report")
@login_required
@buyer_required
def budget_report():
    month = request.args.get("month", datetime.utcnow().month, type=int)
    year = request.args.get("year", datetime.utcnow().year, type=int)
    summary_type = request.args.get("type", "")
    view_mode = request.args.get("view", "plan")  # plan | area | total

    plans = AccountPlan.query.filter_by(is_active=True).order_by(AccountPlan.code.asc()).all()

    # Monthly budgets for month/year
    mb_by_plan = {}
    for mb in MonthlyBudget.query.filter_by(year=year, month=month).all():
        mb_by_plan[mb.account_plan_id] = mb

    # Realizado do PlanoDeContas (Valor(R$) agregado por account_plan)
    # Usa PurchaseRequest aprovadas + compradas vinculadas a plano
    pr_used = {}
    for pr in PurchaseRequest.query.filter(
        PurchaseRequest.status.in_(["approved", "purchased"]),
        PurchaseRequest.account_plan_id.isnot(None),
    ).all():
        pid = pr.account_plan_id
        val = abs(pr.total_approved or pr.total_estimated or 0)
        pr_used[pid] = pr_used.get(pid, 0) + val

    rows = []
    for plan in plans:
        if summary_type and plan.summary != summary_type:
            continue
        mb = mb_by_plan.get(plan.id)
        budgeted = mb.budgeted_value if mb else 0.0
        adjusted = mb.adjusted_value if mb else 0.0
        realized_import = mb.realized_value if mb else 0.0
        pr_val = pr_used.get(plan.id, 0.0)
        # Realizado = maior entre valor do arquivo e compras registradas no sistema
        realized = max(realized_import, pr_val)
        available = budgeted - realized
        pct = round((realized / budgeted * 100) if budgeted > 0 else 0, 1)
        rows.append({
            "plan": plan,
            "budgeted": budgeted,
            "adjusted": adjusted,
            "realized": realized,
            "pr_committed": pr_val,
            "available": available,
            "pct": pct,
            "mb": mb,
        })

    # Totals
    total_budgeted = sum(r["budgeted"] for r in rows)
    total_adjusted = sum(r["adjusted"] for r in rows)
    total_realized = sum(r["realized"] for r in rows)
    total_available = total_budgeted - total_realized

    # Summary by area
    area_rows = {}
    for r in rows:
        area = r["plan"].area or "Sem Área"
        if area not in area_rows:
            area_rows[area] = {"area": area, "budgeted": 0, "realized": 0, "available": 0}
        area_rows[area]["budgeted"] += r["budgeted"]
        area_rows[area]["realized"] += r["realized"]
        area_rows[area]["available"] += r["available"]
    area_data = sorted(area_rows.values(), key=lambda x: x["budgeted"], reverse=True)

    unique_types = (
        db.session.query(AccountPlan.summary)
        .filter(AccountPlan.is_active == True, AccountPlan.summary.isnot(None))
        .distinct().order_by(AccountPlan.summary).all()
    )
    summary_types = [t[0] for t in unique_types if t[0]]

    months = [(i, m) for i, m in enumerate(
        ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"], start=1
    )]

    return render_template(
        "budget/report.html",
        rows=rows,
        area_data=area_data,
        month=month,
        year=year,
        summary_type=summary_type,
        summary_types=summary_types,
        view_mode=view_mode,
        months=months,
        total_budgeted=total_budgeted,
        total_adjusted=total_adjusted,
        total_realized=total_realized,
        total_available=total_available,
    )


# -----------------------------------------------------------------------
# Painel de Fornecedores
# -----------------------------------------------------------------------
@budget_bp.route("/suppliers")
@login_required
@buyer_required
def suppliers_panel():
    from sqlalchemy import case
    from datetime import timedelta

    # Filtros
    date_from_str = request.args.get("date_from", "")
    date_to_str = request.args.get("date_to", "")
    page = request.args.get("page", 1, type=int)

    # Base query: cotações selecionadas de solicitações aprovadas/compradas
    q = db.session.query(
        Quotation.supplier,
        func.count(Quotation.id).label("qty"),
        func.sum(Quotation.total_value).label("total"),
    ).join(PurchaseRequest).filter(
        Quotation.is_selected == True,
        PurchaseRequest.status.in_(["approved", "purchased"]),
    )

    if date_from_str:
        try:
            q = q.filter(
                PurchaseRequest.purchase_date >= datetime.strptime(date_from_str, "%Y-%m-%d")
            )
        except ValueError:
            pass
    if date_to_str:
        try:
            q = q.filter(
                PurchaseRequest.purchase_date <= datetime.strptime(date_to_str, "%Y-%m-%d")
            )
        except ValueError:
            pass

    supplier_rows = (
        q.group_by(Quotation.supplier)
        .order_by(func.sum(Quotation.total_value).desc())
        .all()
    )

    # Detalhes recentes por fornecedor (para drill-down)
    top_supplier = request.args.get("supplier", "")
    supplier_detail = []
    if top_supplier:
        supplier_detail = (
            db.session.query(PurchaseRequest, Quotation)
            .join(Quotation, Quotation.purchase_request_id == PurchaseRequest.id)
            .filter(
                Quotation.supplier == top_supplier,
                Quotation.is_selected == True,
                PurchaseRequest.status.in_(["approved", "purchased"]),
            )
            .order_by(PurchaseRequest.purchase_date.desc())
            .limit(20)
            .all()
        )

    total_spend = sum(r.total or 0 for r in supplier_rows)

    return render_template(
        "budget/suppliers.html",
        supplier_rows=supplier_rows,
        supplier_detail=supplier_detail,
        top_supplier=top_supplier,
        total_spend=total_spend,
        date_from=date_from_str,
        date_to=date_to_str,
    )
