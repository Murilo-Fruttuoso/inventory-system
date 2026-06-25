"""
Rotas do módulo de Plano de Contas e Orçamento.
Blueprint: budget_bp  (prefixo /budget)
"""
import os
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
from sqlalchemy import extract, func

from app.decorators import admin_required, buyer_required
from app.extensions import db
from app.models import AccountPlan, Budget, MonthlyBudget, PurchaseRequest, Quotation
from app.services import log_action, parse_number


def _is_postgres():
    """Retorna True se o banco configurado é PostgreSQL."""
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith("postgres")

budget_bp = Blueprint("budget", __name__, url_prefix="/budget")


# -----------------------------------------------------------------------
# Dashboard de orçamento
# -----------------------------------------------------------------------
@budget_bp.route("/")
@login_required
@buyer_required
def overview():
    year = request.args.get("year", datetime.utcnow().year, type=int)
    summary_type = request.args.get("type", "")  # DESPESAS / RECEITA / etc.

    plans = AccountPlan.query.filter_by(is_active=True).order_by(
        AccountPlan.code.asc()
    ).all()

    # Calcular total utilizado por plano (compras aprovadas/compradas)
    # Usa o total_approved da solicitação vinculada
    used_by_plan = {}
    # Filtro de ano compatível com SQLite e PostgreSQL
    if _is_postgres():
        year_filter = extract("year", PurchaseRequest.purchase_date) == year
    else:
        year_filter = func.strftime("%Y", PurchaseRequest.purchase_date) == str(year)
    approved_requests = PurchaseRequest.query.filter(
        PurchaseRequest.status.in_(["approved", "purchased"]),
        PurchaseRequest.account_plan_id.isnot(None),
        year_filter,
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
@buyer_required
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


@budget_bp.route("/accounts/bulk-delete", methods=["POST"])
@login_required
@admin_required
def accounts_bulk_delete():
    """Excluir Plano de Contas em lote.

    Modos suportados (campo hidden 'mode'):
      - 'selected' → IDs individuais via checkboxes
      - 'inactive' → todas as contas inativas (is_active=False)
      - 'all'      → TODAS as contas (inclusive orçamentos vinculados)
    """
    mode = request.form.get("mode", "selected")

    if mode == "selected":
        ids_raw = request.form.getlist("ids")
        try:
            ids = [int(i) for i in ids_raw if str(i).strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            flash("Nenhuma conta selecionada.", "warning")
            return redirect(url_for("budget.accounts_list"))
        targets = AccountPlan.query.filter(AccountPlan.id.in_(ids)).all()

    elif mode == "inactive":
        targets = AccountPlan.query.filter_by(is_active=False).all()
        if not targets:
            flash("Nenhuma conta inativa encontrada.", "info")
            return redirect(url_for("budget.accounts_list"))

    elif mode == "all":
        targets = AccountPlan.query.all()

    else:
        flash("Modo de exclusão desconhecido.", "danger")
        return redirect(url_for("budget.accounts_list"))

    count = len(targets)
    if count == 0:
        flash("Nenhuma conta encontrada para os critérios informados.", "info")
        return redirect(url_for("budget.accounts_list"))

    try:
        for account in targets:
            db.session.delete(account)
        log_action(
            current_user,
            "plano_contas_excluido_lote",
            f"{count} contas do plano excluídas em lote (modo: {mode}).",
            ip_address=request.remote_addr,
        )
        db.session.commit()
        flash(f"{count} conta(s) excluída(s) com sucesso.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro ao excluir em lote: {exc}", "danger")

    return redirect(url_for("budget.accounts_list"))


@budget_bp.route("/monthly/bulk-delete", methods=["POST"])
@login_required
@admin_required
def monthly_bulk_delete():
    """Excluir Orçamentos Mensais em lote.

    Modos suportados:
      - 'selected'  → IDs individuais via checkboxes
      - 'month_year' → todos de um mês/ano específico
      - 'all'        → TODOS os orçamentos mensais
    """
    mode = request.form.get("mode", "selected")

    if mode == "selected":
        ids_raw = request.form.getlist("ids")
        try:
            ids = [int(i) for i in ids_raw if str(i).strip().isdigit()]
        except ValueError:
            ids = []
        if not ids:
            flash("Nenhum orçamento selecionado.", "warning")
            return redirect(url_for("budget.monthly_list"))
        targets = MonthlyBudget.query.filter(MonthlyBudget.id.in_(ids)).all()

    elif mode == "month_year":
        month_val = request.form.get("month_filter", type=int)
        year_val = request.form.get("year_filter", type=int)
        if not month_val or not year_val:
            flash("Selecione mês e ano.", "warning")
            return redirect(url_for("budget.monthly_list"))
        targets = MonthlyBudget.query.filter_by(month=month_val, year=year_val).all()

    elif mode == "all":
        targets = MonthlyBudget.query.all()

    else:
        flash("Modo de exclusão desconhecido.", "danger")
        return redirect(url_for("budget.monthly_list"))

    count = len(targets)
    if count == 0:
        flash("Nenhum orçamento encontrado para os critérios informados.", "info")
        return redirect(url_for("budget.monthly_list"))

    try:
        for mb in targets:
            db.session.delete(mb)
        log_action(
            current_user,
            "orcamento_mensal_excluido_lote",
            f"{count} orçamentos mensais excluídos em lote (modo: {mode}).",
            ip_address=request.remote_addr,
        )
        db.session.commit()
        flash(f"{count} orçamento(s) mensal(is) excluído(s) com sucesso.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro ao excluir em lote: {exc}", "danger")

    return redirect(url_for("budget.monthly_list"))


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
        from app.services import parse_number as pn

        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo Excel.", "danger")
            return redirect(url_for("budget.import_accounts"))

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".xlsx", ".xls"}:
            flash("Apenas arquivos .xlsx ou .xls são aceitos.", "danger")
            return redirect(url_for("budget.import_accounts"))

        try:
            # Lê apenas as colunas relevantes para economizar memória
            # O arquivo PlanoDeContas tem 8000+ linhas mas apenas ~87 códigos únicos
            df = pd.read_excel(file, dtype=str)
            df.columns = [str(c).strip().lower() for c in df.columns]
            df = df.fillna("")

            # ── DEDUPLICAÇÃO ────────────────────────────────────────────────
            # O arquivo tem múltiplas linhas por código (uma por lançamento).
            # Agrupamos por código e pegamos a primeira linha de cada grupo
            # para extrair os metadados do plano (descrição, resumido, etc.).
            # O valor "Orçado" é o mesmo em todas as linhas do mesmo código.
            col_code = "plano"
            if col_code not in df.columns:
                flash("Coluna 'Plano' não encontrada no arquivo.", "danger")
                return redirect(url_for("budget.import_accounts"))

            # Normalizar códigos e descartar inválidos
            def clean_code(raw):
                raw = str(raw).strip()
                if not raw or raw.lower() in ("nan", ""):
                    return None
                try:
                    return str(int(float(raw)))
                except (ValueError, OverflowError):
                    c = raw.replace(".0", "") if raw.endswith(".0") else raw
                    return c if c else None

            df["_code_clean"] = df[col_code].apply(clean_code)
            df = df[df["_code_clean"].notna()].copy()

            # Pegar primeira linha de cada código único (metadados são iguais em todas)
            df_unique = df.drop_duplicates(subset=["_code_clean"], keep="first")
            total_rows = len(df)
            unique_count = len(df_unique)

            created = 0
            updated = 0
            BATCH = 50  # commit a cada N registros para evitar lock de banco

            year_now = datetime.utcnow().year

            for i, (_, row) in enumerate(df_unique.iterrows()):
                code_clean = row["_code_clean"]
                description = str(
                    row.get("descrição", row.get("descricao", ""))
                ).strip()
                if not description:
                    description = code_clean  # fallback

                summary = str(row.get("resumido", "")).strip() or None
                totalizer = str(row.get("totalizadora", "")).strip() or None
                account_type = str(row.get("tipo", "")).strip() or None
                cost_center = str(row.get("empresa/unidade", "")).strip() or None
                area = str(row.get("área", row.get("area", ""))).strip() or None
                budgeted_raw = row.get("orçado", row.get("orcado", ""))

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
                    acc_obj = existing
                    updated += 1
                else:
                    acc_obj = AccountPlan(
                        code=code_clean,
                        description=description,
                        summary=summary,
                        totalizer=totalizer,
                        account_type=account_type,
                        cost_center=cost_center,
                        area=area,
                    )
                    db.session.add(acc_obj)
                    db.session.flush()
                    created += 1

                # Seed orçamento anual se coluna "Orçado" tiver valor
                budgeted_str = str(budgeted_raw).strip()
                if budgeted_str and budgeted_str not in ("", "0", "0.0", "nan"):
                    try:
                        budgeted_val = abs(pn(budgeted_raw))
                    except Exception:
                        budgeted_val = 0.0
                    if budgeted_val > 0 and acc_obj.id:
                        b = Budget.query.filter_by(
                            account_plan_id=acc_obj.id, year=year_now, month=None
                        ).first()
                        if not b:
                            db.session.add(
                                Budget(
                                    account_plan_id=acc_obj.id,
                                    year=year_now,
                                    month=None,
                                    budgeted_value=budgeted_val,
                                )
                            )

                # Commit em lotes para evitar timeout e lock excessivo
                if (i + 1) % BATCH == 0:
                    db.session.commit()

            db.session.commit()
            flash(
                f"Importação concluída: {created} contas criadas, {updated} atualizadas "
                f"(arquivo tinha {total_rows} linhas → {unique_count} planos únicos).",
                "success",
            )
            return redirect(url_for("budget.accounts_list"))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro na importação de plano de contas")
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
            # Auto-detectar estrutura do arquivo:
            # Formato A (novo, sem linha de título): header na row 0, colunas sem ":"
            # Formato B (antigo, com linha de título "ORÇAMENTO DESPESAS..."): header na row 1
            # Estratégia: tentar header=0 primeiro; se primeira célula não for código numérico
            # e sim texto de título, então usar header=1.
            df = pd.read_excel(file, header=0, dtype=str)
            df.columns = [str(c).strip() for c in df.columns]

            # Verificar se é Formato B: primeira coluna tem nome genérico (título mesclado)
            # e primeira linha de dados contém o verdadeiro cabeçalho (começa com "CÓDIGO")
            first_col_name = str(df.columns[0]).strip().upper()
            has_real_header_in_row0 = any(
                k in first_col_name for k in ("CÓDIGO", "CODIGO", "PLANO", "CÓDIGO DO PLANO")
            )
            if not has_real_header_in_row0:
                # Formato B: a row 0 dos dados pode ser o cabeçalho real
                first_data_row = df.iloc[0]
                if str(first_data_row.iloc[0]).strip().upper().startswith("CÓDIGO"):
                    # Usar row 0 como header
                    df.columns = [str(v).strip() for v in first_data_row.values]
                    df = df.iloc[1:].reset_index(drop=True)
                else:
                    # Tentar header=1 (linha de título na row 0)
                    file.seek(0)
                    df2 = pd.read_excel(file, header=1, dtype=str)
                    cols2 = [str(c).strip().upper() for c in df2.columns]
                    if any("CÓDIGO" in c or "CODIGO" in c for c in cols2):
                        df = df2

            # Normalizar colunas: UPPERCASE, sem espaços extras, sem dois-pontos finais
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
            return redirect(url_for("budget.monthly_list", month=month_form, year=year_form))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Erro na importação mensal")
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
# Visualizar e excluir Orçamentos Mensais
# -----------------------------------------------------------------------
MONTH_NAMES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


@budget_bp.route("/monthly")
@login_required
@buyer_required
def monthly_list():
    """Lista todos os registros de orçamento mensal com filtros de mês/ano."""
    month = request.args.get("month", datetime.utcnow().month, type=int)
    year = request.args.get("year", datetime.utcnow().year, type=int)
    search = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    q = (
        db.session.query(MonthlyBudget, AccountPlan)
        .join(AccountPlan, MonthlyBudget.account_plan_id == AccountPlan.id)
        .filter(MonthlyBudget.year == year, MonthlyBudget.month == month)
    )
    if search:
        like = f"%{search}%"
        q = q.filter(
            AccountPlan.code.ilike(like) | AccountPlan.description.ilike(like)
        )

    # Totais (sem paginar)
    all_rows = q.order_by(AccountPlan.code.asc()).all()
    total_budgeted = sum(mb.budgeted_value or 0 for mb, _ in all_rows)
    total_adjusted = sum(mb.adjusted_value or 0 for mb, _ in all_rows)
    total_realized = sum(mb.realized_value or 0 for mb, _ in all_rows)

    # Anos disponíveis
    years_q = (
        db.session.query(MonthlyBudget.year)
        .distinct()
        .order_by(MonthlyBudget.year.desc())
        .all()
    )
    available_years = [r[0] for r in years_q] or [datetime.utcnow().year]

    months_sel = list(enumerate(MONTH_NAMES, start=1))

    # Paginação manual
    per_page = 50
    total_items = len(all_rows)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    rows_page = all_rows[start: start + per_page]

    return render_template(
        "budget/monthly_list.html",
        rows=rows_page,
        month=month,
        year=year,
        search=search,
        months=months_sel,
        available_years=available_years,
        total_budgeted=total_budgeted,
        total_adjusted=total_adjusted,
        total_realized=total_realized,
        total_items=total_items,
        page=page,
        total_pages=total_pages,
        month_name=MONTH_NAMES[month - 1] if 1 <= month <= 12 else str(month),
    )


@budget_bp.route("/monthly/<int:mb_id>/delete", methods=["POST"])
@login_required
@admin_required
def monthly_delete(mb_id):
    """Exclui um registro de orçamento mensal."""
    mb = MonthlyBudget.query.get_or_404(mb_id)
    plan = AccountPlan.query.get(mb.account_plan_id)
    month = mb.month
    year = mb.year
    try:
        db.session.delete(mb)
        db.session.commit()
        plan_name = f"{plan.code} - {plan.description}" if plan else f"ID {mb.account_plan_id}"
        flash(f"Orçamento '{plan_name}' ({MONTH_NAMES[month-1]}/{year}) excluído.", "success")
        log_action(
            current_user,
            "orcamento_mensal_excluido",
            f"MonthlyBudget #{mb_id} ({plan_name} {month:02d}/{year}) excluído.",
            ip_address=request.remote_addr,
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro ao excluir: {exc}", "danger")
    return redirect(url_for("budget.monthly_list", month=month, year=year))


@budget_bp.route("/monthly/delete-all", methods=["POST"])
@login_required
@admin_required
def monthly_delete_all():
    """Exclui TODOS os orçamentos de um mês/ano (com confirmação)."""
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int)
    if not month or not year:
        flash("Mês e ano são obrigatórios.", "danger")
        return redirect(url_for("budget.monthly_list"))
    try:
        deleted = MonthlyBudget.query.filter_by(year=year, month=month).delete()
        db.session.commit()
        flash(
            f"{deleted} registros de {MONTH_NAMES[month-1]}/{year} excluídos.",
            "success",
        )
        log_action(
            current_user,
            "orcamento_mensal_excluido_lote",
            f"Todos os MonthlyBudgets de {month:02d}/{year} excluídos ({deleted} registros).",
            ip_address=request.remote_addr,
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Erro ao excluir: {exc}", "danger")
    return redirect(url_for("budget.monthly_list", month=month, year=year))


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
    """Painel de fornecedores.

    Inclui duas fontes de dados:
    1. Cotações formais (Quotation.is_selected=True) vinculadas a PRs aprovadas/compradas.
    2. PRs aprovadas/compradas SEM cotação formal, usando exclusive_supplier_name
       (PRs importadas do Forms ou com fornecedor exclusivo sem cotação).
    """
    # Filtros de data
    date_from_str = request.args.get("date_from", "")
    date_to_str = request.args.get("date_to", "")

    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
        except ValueError:
            pass

    # ── Fonte 1: cotações formais selecionadas ──────────────────────────
    q_formal = (
        db.session.query(
            Quotation.supplier.label("supplier"),
            func.count(Quotation.id).label("qty"),
            func.sum(Quotation.total_value).label("total"),
        )
        .join(PurchaseRequest)
        .filter(
            Quotation.is_selected == True,
            PurchaseRequest.status.in_(["approved", "purchased"]),
        )
    )
    if date_from:
        q_formal = q_formal.filter(PurchaseRequest.purchase_date >= date_from)
    if date_to:
        q_formal = q_formal.filter(PurchaseRequest.purchase_date <= date_to)

    formal_rows = q_formal.group_by(Quotation.supplier).all()

    # ── Fonte 2: PRs sem cotação formal mas com fornecedor registrado ──
    # Considera PRs que não têm nenhuma cotação is_selected=True
    # e têm exclusive_supplier_name preenchido
    subq_has_selected = (
        db.session.query(Quotation.purchase_request_id)
        .filter(Quotation.is_selected == True)
        .subquery()
    )
    q_no_quote = (
        db.session.query(PurchaseRequest)
        .filter(
            PurchaseRequest.status.in_(["approved", "purchased"]),
            PurchaseRequest.exclusive_supplier_name.isnot(None),
            PurchaseRequest.exclusive_supplier_name != "",
            ~PurchaseRequest.id.in_(
                db.session.query(subq_has_selected.c.purchase_request_id)
            ),
        )
    )
    if date_from:
        q_no_quote = q_no_quote.filter(PurchaseRequest.purchase_date >= date_from)
    if date_to:
        q_no_quote = q_no_quote.filter(PurchaseRequest.purchase_date <= date_to)

    no_quote_prs = q_no_quote.all()

    # Agrupa PRs sem cotação por nome do fornecedor
    no_quote_map = {}  # supplier_name -> {qty, total}
    for pr in no_quote_prs:
        sup = pr.exclusive_supplier_name.strip()
        if not sup:
            continue
        val = pr.total_approved or pr.total_estimated or 0
        if sup not in no_quote_map:
            no_quote_map[sup] = {"qty": 0, "total": 0.0}
        no_quote_map[sup]["qty"] += 1
        no_quote_map[sup]["total"] += val

    # ── Combina as duas fontes ──────────────────────────────────────────
    combined = {}  # supplier_name -> {qty, total}

    for row in formal_rows:
        sup = row.supplier or "Desconhecido"
        combined[sup] = {
            "supplier": sup,
            "qty": (row.qty or 0),
            "total": (row.total or 0.0),
        }

    for sup, data in no_quote_map.items():
        if sup in combined:
            combined[sup]["qty"] += data["qty"]
            combined[sup]["total"] += data["total"]
        else:
            combined[sup] = {
                "supplier": sup,
                "qty": data["qty"],
                "total": data["total"],
            }

    # Converte para lista ordenada por total decrescente
    # Cria namedtuple-like objects para compatibilidade com o template
    from collections import namedtuple
    SupplierRow = namedtuple("SupplierRow", ["supplier", "qty", "total"])
    supplier_rows = sorted(
        [SupplierRow(**v) for v in combined.values()],
        key=lambda r: r.total,
        reverse=True,
    )

    total_spend = sum(r.total or 0 for r in supplier_rows)

    # ── Detalhe por fornecedor (drill-down) ────────────────────────────
    top_supplier = request.args.get("supplier", "")
    supplier_detail = []  # lista de (PurchaseRequest, QuotationLike)

    if top_supplier:
        # Namedtuple que imita os campos de Quotation usados no template
        FakeQuotation = namedtuple("FakeQuotation", ["total_value"])

        # Detalhe via cotações formais
        formal_detail = (
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
        supplier_detail.extend(formal_detail)

        # Detalhe via PRs sem cotação formal
        if len(supplier_detail) < 20:
            no_quote_detail = (
                db.session.query(PurchaseRequest)
                .filter(
                    PurchaseRequest.status.in_(["approved", "purchased"]),
                    PurchaseRequest.exclusive_supplier_name == top_supplier,
                    ~PurchaseRequest.id.in_(
                        db.session.query(subq_has_selected.c.purchase_request_id)
                    ),
                )
                .order_by(PurchaseRequest.purchase_date.desc())
                .limit(20 - len(supplier_detail))
                .all()
            )
            for pr in no_quote_detail:
                val = pr.total_approved or pr.total_estimated or 0
                supplier_detail.append((pr, FakeQuotation(total_value=val)))

        # Ordena tudo por data
        supplier_detail.sort(
            key=lambda x: x[0].purchase_date or datetime.min, reverse=True
        )

    return render_template(
        "budget/suppliers.html",
        supplier_rows=supplier_rows,
        supplier_detail=supplier_detail,
        top_supplier=top_supplier,
        total_spend=total_spend,
        date_from=date_from_str,
        date_to=date_to_str,
    )
