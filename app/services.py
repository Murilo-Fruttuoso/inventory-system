from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Dict, Iterable

import pandas as pd
from flask import current_app
from sqlalchemy import func, or_

from app.extensions import db
from app.models import ActionLog, Product, StockMovement


ALLOWED_IMPORT_EXTENSIONS = {".xlsx", ".xls"}


def parse_number(value, default=0.0):
    if value is None or value == "":
        return float(default)
    if isinstance(value, str):
        value = value.strip().replace(".", "").replace(",", ".") if value.count(",") == 1 and value.count(".") > 1 else value.strip().replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_columns(columns: Iterable[str]):
    return [str(col).strip().lower() for col in columns]


def distinct_categories():
    rows = db.session.query(Product.category).filter(Product.category.isnot(None)).distinct().order_by(Product.category).all()
    return [row[0] for row in rows if row[0]]


def distinct_stores():
    rows = db.session.query(Product.store).filter(Product.store.isnot(None), Product.store != "").distinct().order_by(Product.store).all()
    return [row[0] for row in rows if row[0]]


def log_action(user, action, description, entity_type=None, entity_id=None, ip_address=None, commit=True):
    log = ActionLog(
        user_id=getattr(user, "id", None),
        action=action,
        description=description,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
    )
    db.session.add(log)
    if commit:
        db.session.commit()
    return log


def product_query_with_filters(search_term="", category="", low_only=False, brand="", store=""):
    query = Product.query
    if search_term:
        like = f"%{search_term}%"
        query = query.filter(
            or_(
                Product.name.ilike(like),
                Product.description.ilike(like),
                Product.category.ilike(like),
                Product.location.ilike(like),
                Product.brand.ilike(like),
            )
        )
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))
    if store:
        query = query.filter(Product.store == store)
    if low_only:
        query = query.filter(Product.quantity <= Product.quantity_min)
    return query.order_by(Product.store.asc(), Product.name.asc())


def movement_query_with_filters(start_date="", end_date="", product_id="", category="", direction="", store=""):
    query = StockMovement.query.join(Product).join(StockMovement.user)
    if start_date:
        query = query.filter(func.date(StockMovement.created_at) >= start_date)
    if end_date:
        query = query.filter(func.date(StockMovement.created_at) <= end_date)
    if product_id:
        query = query.filter(StockMovement.product_id == int(product_id))
    if category:
        query = query.filter(Product.category == category)
    if direction:
        query = query.filter(StockMovement.direction == direction)
    if store:
        query = query.filter(StockMovement.store == store)
    return query.order_by(StockMovement.created_at.desc())


def products_to_dataframe(products):
    rows = []
    for product in products:
        rows.append(
            {
                "ID": product.id,
                "Unidade/Filial": product.store or "",
                "Nome": product.name,
                "Marca": product.brand or "",
                "Descrição": product.description or "",
                "Categoria": product.category,
                "Unid. Medida": product.unit,
                "Valor Unitário (R$)": product.unit_value or 0.0,
                "Quantidade": product.quantity,
                "Valor Total (R$)": round(product.total_stock_value, 2),
                "Quantidade mínima": product.quantity_min,
                "Estoque baixo": "Sim" if product.low_stock else "Não",
                "Localização": product.location or "",
                "Data de cadastro": product.created_at.strftime("%d/%m/%Y %H:%M"),
                "Observações": product.notes or "",
            }
        )
    return pd.DataFrame(rows)


def movements_to_dataframe(movements):
    rows = []
    for movement in movements:
        unit_value = movement.product.unit_value or 0.0
        rows.append(
            {
                "ID": movement.id,
                "Data": movement.created_at.strftime("%d/%m/%Y %H:%M"),
                "Unidade/Filial": movement.store or "",
                "Produto": movement.product.name,
                "Marca": movement.product.brand or "",
                "Categoria": movement.product.category,
                "Direção": "Entrada" if movement.direction == "IN" else "Saída",
                "Tipo": movement.reason,
                "Quantidade": movement.quantity,
                "Valor Unitário (R$)": unit_value,
                "Valor Movimentação (R$)": round(unit_value * movement.quantity, 2),
                "Saldo anterior": movement.previous_quantity,
                "Novo saldo": movement.new_quantity,
                "Responsável": movement.user.full_name,
                "Usuário": movement.user.username,
                "Observações": movement.note or "",
            }
        )
    return pd.DataFrame(rows)


def dataframe_to_excel_response(dataframes: Dict[str, pd.DataFrame], filename: str):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dataframes.items():
            safe_name = sheet_name[:31]
            if df.empty:
                df = pd.DataFrame([{"Mensagem": "Nenhum registro encontrado para os filtros informados."}])
            df.to_excel(writer, index=False, sheet_name=safe_name)
            worksheet = writer.sheets[safe_name]
            for column_cells in worksheet.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter
                for cell in column_cells:
                    cell_value = "" if cell.value is None else str(cell.value)
                    max_length = max(max_length, len(cell_value))
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 45)
    output.seek(0)
    return output, filename


def import_products_from_excel(file_storage, current_user, ip_address=None):
    dataframe = pd.read_excel(file_storage)
    dataframe.columns = normalize_columns(dataframe.columns)

    required_columns = {"nome", "categoria", "unidade"}
    missing = required_columns - set(dataframe.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Colunas obrigatórias ausentes: {missing_text}")

    created = 0
    updated = 0
    skipped = 0
    movement_count = 0

    for _, row in dataframe.fillna("").iterrows():
        name = str(row.get("nome", "")).strip()
        category = str(row.get("categoria", "")).strip()
        unit = str(row.get("unidade", "")).strip()

        if not name or not category or not unit:
            skipped += 1
            continue

        quantity = max(parse_number(row.get("quantidade", 0)), 0)
        quantity_min = max(parse_number(row.get("quantidade_minima", 0)), 0)
        description = str(row.get("descricao", "")).strip()
        location = str(row.get("localizacao", "")).strip()
        notes = str(row.get("observacoes", "")).strip()

        product = None
        raw_id = str(row.get("id", "")).strip()
        if raw_id.isdigit():
            product = Product.query.get(int(raw_id))
        if product is None:
            product = Product.query.filter_by(name=name, category=category).first()

        if product is None:
            product = Product(
                name=name,
                category=category,
                unit=unit,
                quantity=0,
                quantity_min=quantity_min,
                description=description,
                location=location,
                notes=notes,
            )
            db.session.add(product)
            db.session.flush()
            created += 1
        else:
            product.name = name
            product.category = category
            product.unit = unit
            product.quantity_min = quantity_min
            product.description = description
            product.location = location
            product.notes = notes
            updated += 1

        if quantity != product.quantity:
            previous_quantity = product.quantity
            direction = "IN" if quantity >= previous_quantity else "OUT"
            movement = StockMovement(
                product_id=product.id,
                user_id=current_user.id,
                direction=direction,
                reason="importacao_inicial" if previous_quantity == 0 and created > 0 else "ajuste_importacao",
                quantity=abs(quantity - previous_quantity),
                previous_quantity=previous_quantity,
                new_quantity=quantity,
                note="Movimento gerado automaticamente pela importação inicial via Excel.",
            )
            product.quantity = quantity
            db.session.add(movement)
            movement_count += 1

    log_action(
        current_user,
        "importacao_excel",
        f"Importação de produtos via Excel concluída. Criados: {created}, atualizados: {updated}, ignorados: {skipped}.",
        entity_type="import",
        entity_id=None,
        ip_address=ip_address,
        commit=False,
    )
    db.session.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "movements": movement_count,
    }


def sqlite_database_path():
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    return uri.replace("sqlite:///", "", 1)


def dashboard_stats():
    total_products = Product.query.count()
    total_quantity = db.session.query(func.coalesce(func.sum(Product.quantity), 0)).scalar() or 0
    low_stock_count = Product.query.filter(Product.quantity <= Product.quantity_min).count()
    recent_movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(10).all()
    critical_products = Product.query.filter(Product.quantity <= Product.quantity_min).order_by(Product.quantity.asc()).limit(10).all()
    all_products = Product.query.all()
    total_stock_value = sum(p.total_stock_value for p in all_products)
    # Resumo por unidade/filial
    store_summary = {}
    for p in all_products:
        s = p.store or "(sem unidade)"
        if s not in store_summary:
            store_summary[s] = {"products": 0, "value": 0.0}
        store_summary[s]["products"] += 1
        store_summary[s]["value"] += p.total_stock_value
    return {
        "total_products": total_products,
        "total_quantity": total_quantity,
        "low_stock_count": low_stock_count,
        "recent_movements": recent_movements,
        "critical_products": critical_products,
        "total_stock_value": total_stock_value,
        "store_summary": store_summary,
    }


def current_timestamp_for_filename(prefix, extension):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
