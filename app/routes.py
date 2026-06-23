import os
import shutil
import tempfile
from datetime import datetime
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.decorators import admin_required
from app.extensions import db
from app.models import ActionLog, Product, StockMovement, User
from app.services import (
    current_timestamp_for_filename,
    dashboard_stats,
    dataframe_to_excel_response,
    distinct_categories,
    distinct_stores,
    import_products_from_excel,
    log_action,
    movement_query_with_filters,
    movements_to_dataframe,
    parse_number,
    product_query_with_filters,
    products_to_dataframe,
    sqlite_database_path,
)


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    stats = dashboard_stats()
    return render_template("dashboard.html", **stats)


@main_bp.route("/products")
@login_required
def products_list():
    page = request.args.get("page", 1, type=int)
    search_term = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    store = request.args.get("store", "").strip()
    low_only = request.args.get("low_only", "0") == "1"

    pagination = product_query_with_filters(search_term, category, low_only, store=store).paginate(
        page=page,
        per_page=current_app.config["ITEMS_PER_PAGE"],
        error_out=False,
    )

    return render_template(
        "products/list.html",
        pagination=pagination,
        products=pagination.items,
        categories=distinct_categories(),
        stores=distinct_stores(),
        search_term=search_term,
        category=category,
        store=store,
        low_only=low_only,
    )


@main_bp.route("/products/critical")
@login_required
def products_critical():
    return redirect(url_for("main.products_list", low_only=1))


@main_bp.route("/products/new", methods=["GET", "POST"])
@login_required
@admin_required
def products_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        unit = request.form.get("unit", "").strip()
        brand = request.form.get("brand", "").strip()
        store = request.form.get("store", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        quantity = max(parse_number(request.form.get("quantity", 0)), 0)
        quantity_min = max(parse_number(request.form.get("quantity_min", 0)), 0)
        unit_value = max(parse_number(request.form.get("unit_value", 0)), 0.0)

        if not name or not category or not unit:
            flash("Nome, categoria e unidade são obrigatórios.", "danger")
            return render_template("products/form.html", product=None, stores=distinct_stores())

        product = Product(
            name=name,
            category=category,
            brand=brand or None,
            store=store,
            unit=unit,
            unit_value=unit_value,
            description=description,
            location=location,
            notes=notes,
            quantity=quantity,
            quantity_min=quantity_min,
        )
        try:
            db.session.add(product)
            db.session.flush()

            if quantity > 0:
                movement = StockMovement(
                    product_id=product.id,
                    user_id=current_user.id,
                    store=store,
                    direction="IN",
                    reason="saldo_inicial",
                    quantity=quantity,
                    previous_quantity=0,
                    new_quantity=quantity,
                    note="Saldo inicial informado no cadastro do produto.",
                )
                db.session.add(movement)

            log_action(
                current_user,
                "produto_criado",
                f"Produto {name} cadastrado na unidade '{store or 'não definida'}'.",
                entity_type="product",
                entity_id=product.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Produto cadastrado com sucesso.", "success")
            return redirect(url_for("main.products_list"))
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um produto com o mesmo nome, categoria e unidade.", "danger")

    return render_template("products/form.html", product=None, stores=distinct_stores())


@main_bp.route("/products/<int:product_id>")
@login_required
def products_detail(product_id):
    product = Product.query.get_or_404(product_id)
    recent_movements = (
        StockMovement.query.filter_by(product_id=product.id)
        .order_by(StockMovement.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "products/detail.html", product=product, recent_movements=recent_movements
    )


@main_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def products_edit(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        product.name = request.form.get("name", "").strip()
        product.category = request.form.get("category", "").strip()
        product.brand = request.form.get("brand", "").strip() or None
        product.store = request.form.get("store", "").strip()
        product.unit = request.form.get("unit", "").strip()
        product.unit_value = max(parse_number(request.form.get("unit_value", 0)), 0.0)
        product.description = request.form.get("description", "").strip()
        product.location = request.form.get("location", "").strip()
        product.notes = request.form.get("notes", "").strip()
        product.quantity_min = max(parse_number(request.form.get("quantity_min", 0)), 0)

        if not product.name or not product.category or not product.unit:
            flash("Nome, categoria e unidade são obrigatórios.", "danger")
            return render_template("products/form.html", product=product, stores=distinct_stores())

        try:
            log_action(
                current_user,
                "produto_editado",
                f"Produto {product.name} atualizado.",
                entity_type="product",
                entity_id=product.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Produto atualizado com sucesso.", "success")
            return redirect(url_for("main.products_detail", product_id=product.id))
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um produto com o mesmo nome, categoria e unidade.", "danger")

    return render_template("products/form.html", product=product, stores=distinct_stores())


@main_bp.route("/movements")
@login_required
def movements_list():
    page = request.args.get("page", 1, type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    product_id = request.args.get("product_id", "")
    category = request.args.get("category", "")
    direction = request.args.get("direction", "")
    store = request.args.get("store", "")

    pagination = movement_query_with_filters(
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        category=category,
        direction=direction,
        store=store,
    ).paginate(page=page, per_page=current_app.config["ITEMS_PER_PAGE"], error_out=False)

    return render_template(
        "movements/list.html",
        pagination=pagination,
        movements=pagination.items,
        products=Product.query.order_by(Product.name.asc()).all(),
        categories=distinct_categories(),
        stores=distinct_stores(),
        selected_product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        selected_category=category,
        selected_direction=direction,
        selected_store=store,
    )


@main_bp.route("/movements/new", methods=["GET", "POST"])
@login_required
def movements_new():
    selected_product_id = request.args.get("product_id", type=int)

    if request.method == "POST":
        product_id = request.form.get("product_id", type=int)
        direction = request.form.get("direction", "IN")
        reason = request.form.get("reason", "")
        note = request.form.get("note", "").strip()
        quantity = parse_number(request.form.get("quantity", 0))
        store = request.form.get("store", "").strip()

        product = Product.query.get_or_404(product_id)

        if quantity <= 0:
            flash("Informe uma quantidade maior que zero.", "danger")
            return redirect(url_for("main.movements_new", product_id=product.id))

        if direction not in {"IN", "OUT"}:
            abort(400)

        previous_quantity = product.quantity
        if direction == "OUT" and quantity > previous_quantity:
            flash("Saída maior que o saldo disponível.", "danger")
            return redirect(url_for("main.movements_new", product_id=product.id))

        product.quantity = previous_quantity + quantity if direction == "IN" else previous_quantity - quantity
        movement = StockMovement(
            product_id=product.id,
            user_id=current_user.id,
            store=store or product.store,
            direction=direction,
            reason=reason or ("entrada_manual" if direction == "IN" else "saida_manual"),
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=product.quantity,
            note=note,
        )

        try:
            db.session.add(movement)
            log_action(
                current_user,
                "movimentacao_estoque",
                f"Movimentação {direction} no produto {product.name} (unidade: {store or product.store or 'não definida'}) qtd {quantity}.",
                entity_type="movement",
                entity_id=movement.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Movimentação registrada com sucesso.", "success")
            return redirect(url_for("main.movements_list"))
        except StaleDataError:
            db.session.rollback()
            flash(
                "Outro usuário alterou este produto ao mesmo tempo. Recarregue a página e tente novamente.",
                "warning",
            )
        except IntegrityError:
            db.session.rollback()
            flash("Não foi possível salvar a movimentação.", "danger")

    return render_template(
        "movements/form.html",
        products=Product.query.order_by(Product.name.asc()).all(),
        stores=distinct_stores(),
        selected_product_id=selected_product_id,
    )


@main_bp.route("/reports")
@login_required
def reports():
    stock_search = request.args.get("stock_q", "").strip()
    stock_category = request.args.get("stock_category", "").strip()
    stock_store = request.args.get("stock_store", "").strip()
    stock_low_only = request.args.get("stock_low_only", "0") == "1"
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    product_id = request.args.get("product_id", "")
    movement_category = request.args.get("movement_category", "")
    movement_store = request.args.get("movement_store", "")
    direction = request.args.get("direction", "")

    filtered_products = product_query_with_filters(
        search_term=stock_search,
        category=stock_category,
        low_only=stock_low_only,
        store=stock_store,
    ).all()

    filtered_movements = movement_query_with_filters(
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        category=movement_category,
        direction=direction,
        store=movement_store,
    ).limit(50).all()

    low_stock_products = product_query_with_filters(low_only=True, store=stock_store).all()

    return render_template(
        "reports.html",
        categories=distinct_categories(),
        stores=distinct_stores(),
        products=Product.query.order_by(Product.name.asc()).all(),
        filtered_products=filtered_products,
        filtered_movements=filtered_movements,
        low_stock_products=low_stock_products,
        stock_search=stock_search,
        stock_category=stock_category,
        stock_store=stock_store,
        stock_low_only=stock_low_only,
        start_date=start_date,
        end_date=end_date,
        selected_product_id=product_id,
        movement_category=movement_category,
        movement_store=movement_store,
        selected_direction=direction,
    )


@main_bp.route("/reports/export/current-stock")
@login_required
def export_current_stock():
    products = product_query_with_filters(
        search_term=request.args.get("stock_q", "").strip(),
        category=request.args.get("stock_category", "").strip(),
        low_only=request.args.get("stock_low_only", "0") == "1",
        store=request.args.get("stock_store", "").strip(),
    ).all()
    output, filename = dataframe_to_excel_response(
        {"Estoque atual": products_to_dataframe(products)},
        current_timestamp_for_filename("estoque_atual", "xlsx"),
    )
    log_action(
        current_user,
        "exportacao_excel",
        "Exportação do relatório de estoque atual.",
        entity_type="report",
        ip_address=request.remote_addr,
    )
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/reports/export/movements")
@login_required
def export_movements():
    movements = movement_query_with_filters(
        start_date=request.args.get("start_date", ""),
        end_date=request.args.get("end_date", ""),
        product_id=request.args.get("product_id", ""),
        category=request.args.get("movement_category", ""),
        direction=request.args.get("direction", ""),
        store=request.args.get("movement_store", ""),
    ).all()
    output, filename = dataframe_to_excel_response(
        {"Movimentações": movements_to_dataframe(movements)},
        current_timestamp_for_filename("movimentacoes", "xlsx"),
    )
    log_action(
        current_user,
        "exportacao_excel",
        "Exportação do relatório de movimentações.",
        entity_type="report",
        ip_address=request.remote_addr,
    )
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/reports/export/low-stock")
@login_required
def export_low_stock():
    products = product_query_with_filters(
        low_only=True,
        store=request.args.get("stock_store", "").strip(),
    ).all()
    output, filename = dataframe_to_excel_response(
        {"Estoque baixo": products_to_dataframe(products)},
        current_timestamp_for_filename("estoque_baixo", "xlsx"),
    )
    log_action(
        current_user,
        "exportacao_excel",
        "Exportação do relatório de produtos críticos.",
        entity_type="report",
        ip_address=request.remote_addr,
    )
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/products/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_products():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo Excel para importação.", "danger")
            return redirect(url_for("main.import_products"))

        extension = os.path.splitext(file.filename)[1].lower()
        if extension not in {".xlsx", ".xls"}:
            flash("Arquivo inválido. Envie um arquivo .xlsx ou .xls.", "danger")
            return redirect(url_for("main.import_products"))

        try:
            summary = import_products_from_excel(file, current_user, request.remote_addr)
            flash(
                f"Importação concluída: {summary['created']} criados, {summary['updated']} atualizados, {summary['skipped']} ignorados.",
                "success",
            )
            return redirect(url_for("main.products_list"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Falha na importação: {exc}", "danger")

    return render_template("import.html")


@main_bp.route("/users")
@login_required
@admin_required
def users_list():
    page = request.args.get("page", 1, type=int)
    pagination = User.query.order_by(User.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config["ITEMS_PER_PAGE"],
        error_out=False,
    )
    return render_template("users/list.html", pagination=pagination, users=pagination.items)


@main_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def users_new():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        is_active_user = request.form.get("is_active_user") == "on"

        if not username or not full_name or not password:
            flash("Usuário, nome completo e senha são obrigatórios.", "danger")
            return render_template("users/form.html", user_obj=None)

        user = User(
            username=username,
            full_name=full_name,
            role="admin" if role == "admin" else "user",
            is_active_user=is_active_user,
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.flush()
            log_action(
                current_user,
                "usuario_criado",
                f"Usuário {username} cadastrado com perfil {user.role}.",
                entity_type="user",
                entity_id=user.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Usuário cadastrado com sucesso.", "success")
            return redirect(url_for("main.users_list"))
        except IntegrityError:
            db.session.rollback()
            flash("Nome de usuário já existente.", "danger")

    return render_template("users/form.html", user_obj=None)


@main_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def users_edit(user_id):
    user_obj = User.query.get_or_404(user_id)

    if request.method == "POST":
        user_obj.username = request.form.get("username", "").strip()
        user_obj.full_name = request.form.get("full_name", "").strip()
        user_obj.role = "admin" if request.form.get("role") == "admin" else "user"
        user_obj.is_active_user = request.form.get("is_active_user") == "on"
        new_password = request.form.get("password", "")

        if not user_obj.username or not user_obj.full_name:
            flash("Usuário e nome completo são obrigatórios.", "danger")
            return render_template("users/form.html", user_obj=user_obj)

        if not user_obj.is_active_user and user_obj.id == current_user.id:
            flash("Você não pode desativar o próprio usuário logado.", "danger")
            return render_template("users/form.html", user_obj=user_obj)

        if new_password:
            user_obj.set_password(new_password)

        try:
            log_action(
                current_user,
                "usuario_editado",
                f"Usuário {user_obj.username} atualizado.",
                entity_type="user",
                entity_id=user_obj.id,
                ip_address=request.remote_addr,
                commit=False,
            )
            db.session.commit()
            flash("Usuário atualizado com sucesso.", "success")
            return redirect(url_for("main.users_list"))
        except IntegrityError:
            db.session.rollback()
            flash("Nome de usuário já existente.", "danger")

    return render_template("users/form.html", user_obj=user_obj)


@main_bp.route("/logs")
@login_required
@admin_required
def logs_list():
    page = request.args.get("page", 1, type=int)
    user_id = request.args.get("user_id", "")
    action = request.args.get("action", "").strip()

    query = ActionLog.query.join(User, ActionLog.user_id == User.id, isouter=True)
    if user_id:
        query = query.filter(ActionLog.user_id == int(user_id))
    if action:
        query = query.filter(ActionLog.action.ilike(f"%{action}%"))

    pagination = query.order_by(ActionLog.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config["ITEMS_PER_PAGE"],
        error_out=False,
    )
    return render_template(
        "logs.html",
        pagination=pagination,
        logs=pagination.items,
        users=User.query.order_by(User.username.asc()).all(),
        selected_user_id=user_id,
        action=action,
    )


@main_bp.route("/backup/download")
@login_required
@admin_required
def backup_download():
    db_path = sqlite_database_path()
    if not db_path or not os.path.exists(db_path):
        flash("Backup automático disponível apenas para a base SQLite local.", "warning")
        return redirect(url_for("main.reports"))

    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    shutil.copy2(db_path, temp_path)

    log_action(
        current_user,
        "backup_banco",
        "Backup simples do banco SQLite gerado para download.",
        entity_type="backup",
        ip_address=request.remote_addr,
    )

    return send_file(
        temp_path,
        as_attachment=True,
        download_name=current_timestamp_for_filename("backup_estoque", "db"),
    )
