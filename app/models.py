from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # roles: admin | approver | buyer | user
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)

    movements = db.relationship("StockMovement", back_populates="user", lazy=True)
    logs = db.relationship("ActionLog", back_populates="user", lazy=True)
    purchases = db.relationship("Purchase", back_populates="user", lazy=True)
    purchase_requests = db.relationship("PurchaseRequest", back_populates="requester", lazy=True,
                                        foreign_keys="PurchaseRequest.requester_id")
    approvals = db.relationship("PurchaseRequest", back_populates="approver", lazy=True,
                                foreign_keys="PurchaseRequest.approver_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.is_active_user

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_approver(self):
        return self.role in ("admin", "approver")

    @property
    def is_buyer(self):
        """Comprador: acessa compras, orçamento, relatórios — não acessa admin."""
        return self.role in ("admin", "approver", "buyer")

    @property
    def can_manage_users(self):
        return self.role == "admin"


# ---------------------------------------------------------------------------
# Product (unchanged, preserving all constraints)
# ---------------------------------------------------------------------------
class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text)
    category = db.Column(db.String(100), nullable=False, index=True)
    brand = db.Column(db.String(100))
    store = db.Column(db.String(100), nullable=False, default="", index=True)
    unit = db.Column(db.String(30), nullable=False)
    unit_value = db.Column(db.Float, nullable=False, default=0.0)
    quantity = db.Column(db.Float, nullable=False, default=0)
    quantity_min = db.Column(db.Float, nullable=False, default=0)
    location = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    version_id = db.Column(db.Integer, nullable=False, default=1)

    movements = db.relationship(
        "StockMovement",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )
    purchases = db.relationship(
        "Purchase",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )

    __table_args__ = (
        db.CheckConstraint("quantity >= 0", name="ck_products_quantity_non_negative"),
        db.CheckConstraint(
            "quantity_min >= 0", name="ck_products_quantity_min_non_negative"
        ),
        db.UniqueConstraint("name", "category", "store", name="uq_products_name_category_store"),
    )

    __mapper_args__ = {"version_id_col": version_id}

    @property
    def low_stock(self):
        return self.quantity <= self.quantity_min

    @property
    def total_stock_value(self):
        return (self.unit_value or 0.0) * (self.quantity or 0.0)


# ---------------------------------------------------------------------------
# StockMovement (unchanged)
# ---------------------------------------------------------------------------
class StockMovement(db.Model):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    store = db.Column(db.String(100), nullable=False, default="", index=True)
    direction = db.Column(db.String(10), nullable=False, index=True)
    reason = db.Column(db.String(60), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    previous_quantity = db.Column(db.Float, nullable=False)
    new_quantity = db.Column(db.Float, nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = db.relationship("Product", back_populates="movements")
    user = db.relationship("User", back_populates="movements")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_movements_quantity_positive"),
        db.CheckConstraint(
            "direction IN ('IN', 'OUT')", name="ck_movements_direction_valid"
        ),
    )


# ---------------------------------------------------------------------------
# Purchase (unchanged)
# ---------------------------------------------------------------------------
class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_value = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(150))
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = db.relationship("Product", back_populates="purchases")
    user = db.relationship("User", back_populates="purchases")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_purchases_quantity_positive"),
        db.CheckConstraint("unit_price >= 0", name="ck_purchases_unit_price_non_negative"),
        db.CheckConstraint("total_value >= 0", name="ck_purchases_total_value_non_negative"),
    )


# ---------------------------------------------------------------------------
# ActionLog (unchanged)
# ---------------------------------------------------------------------------
class ActionLog(db.Model):
    __tablename__ = "action_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    description = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="logs")


# ---------------------------------------------------------------------------
# AccountPlan  (Plano de Contas)
# ---------------------------------------------------------------------------
class AccountPlan(db.Model):
    __tablename__ = "account_plans"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    description = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.String(50))          # Resumido: DESPESAS / RECEITA …
    totalizer = db.Column(db.String(100))        # Totalizadora
    account_type = db.Column(db.String(10))      # Tipo: PG / RC / BB …
    cost_center = db.Column(db.String(100))      # Empresa/Unidade
    area = db.Column(db.String(100))             # Área
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    budgets = db.relationship("Budget", back_populates="account_plan",
                              cascade="all, delete-orphan", lazy=True)
    monthly_budgets = db.relationship("MonthlyBudget", back_populates="account_plan",
                                      cascade="all, delete-orphan", lazy=True)
    purchase_requests = db.relationship("PurchaseRequest", back_populates="account_plan", lazy=True)


# ---------------------------------------------------------------------------
# Budget  (Orçamento por conta e período)
# ---------------------------------------------------------------------------
class Budget(db.Model):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    account_plan_id = db.Column(db.Integer, db.ForeignKey("account_plans.id"),
                                nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=True)   # NULL = anual
    budgeted_value = db.Column(db.Float, nullable=False, default=0.0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    account_plan = db.relationship("AccountPlan", back_populates="budgets")

    __table_args__ = (
        db.UniqueConstraint("account_plan_id", "year", "month",
                            name="uq_budget_account_year_month"),
        db.CheckConstraint("budgeted_value >= 0", name="ck_budget_value_non_negative"),
    )


# ---------------------------------------------------------------------------
# PurchaseRequest  (Solicitação de Compra — fluxo completo)
# Statuses: draft | pending_quote | quoted | pending_approval | approved | rejected | purchased | cancelled
# ---------------------------------------------------------------------------
class PurchaseRequest(db.Model):
    __tablename__ = "purchase_requests"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    account_plan_id = db.Column(db.Integer, db.ForeignKey("account_plans.id"),
                                nullable=True, index=True)
    cost_center = db.Column(db.String(100))
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    # Status flow:
    # draft → pending_quote → quoted → pending_approval → approved/rejected → purchased/cancelled
    justification = db.Column(db.Text)
    items_description = db.Column(db.Text)     # JSON list or free text
    total_estimated = db.Column(db.Float, default=0.0)
    total_approved = db.Column(db.Float, default=0.0)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)  # DATA DA COMPRA
    payment_method = db.Column(db.String(80))   # forma de pagamento
    installments = db.Column(db.Integer, default=1)  # quantidade de parcelas
    due_date = db.Column(db.String(20))         # data de vencimento
    delivery_deadline = db.Column(db.String(80))  # prazo de entrega
    invoice_number = db.Column(db.String(80))  # nota fiscal
    legale_launch = db.Column(db.String(100))  # Lançamento Legale
    legale_title = db.Column(db.String(200))   # Título Legale
    purchase_link = db.Column(db.Text)         # Link da compra
    is_urgent = db.Column(db.Boolean, default=False)
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence = db.Column(db.String(50))      # Periodicidade
    delivery_location = db.Column(db.String(200))  # Local de entrega
    purchase_type = db.Column(db.String(100))  # Tipo de Compra
    request_type = db.Column(db.String(100))   # Tipo de Solicitação
    exclusive_supplier = db.Column(db.Boolean, default=False)
    exclusive_supplier_name = db.Column(db.String(200))
    area_team = db.Column(db.String(100))      # Área/Equipe do Solicitante
    has_three_quotes = db.Column(db.Boolean, default=False)  # 3 Orçamentos?
    forms_status = db.Column(db.String(50))    # Status Aprovação (Forms)
    approval_note = db.Column(db.Text)         # nota do aprovador
    forms_id = db.Column(db.String(100))       # ID externo do Microsoft Forms
    forms_submitted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    requester = db.relationship("User", back_populates="purchase_requests",
                                foreign_keys=[requester_id])
    approver = db.relationship("User", back_populates="approvals",
                               foreign_keys=[approver_id])
    account_plan = db.relationship("AccountPlan", back_populates="purchase_requests")
    quotations = db.relationship("Quotation", back_populates="purchase_request",
                                 cascade="all, delete-orphan", lazy=True)

    @property
    def status_label(self):
        labels = {
            "draft": "Rascunho",
            "pending_quote": "Aguardando Cotação",
            "quoted": "Cotado",
            "pending_approval": "Aguardando Aprovação",
            "approved": "Aprovado",
            "rejected": "Reprovado",
            "purchased": "Comprado",
            "cancelled": "Cancelado",
        }
        return labels.get(self.status, self.status)

    @property
    def status_color(self):
        colors = {
            "draft": "secondary",
            "pending_quote": "warning",
            "quoted": "info",
            "pending_approval": "primary",
            "approved": "success",
            "rejected": "danger",
            "purchased": "success",
            "cancelled": "dark",
        }
        return colors.get(self.status, "secondary")

    @property
    def best_quotation(self):
        """Returns the selected quotation (is_selected=True) or cheapest."""
        selected = [q for q in self.quotations if q.is_selected]
        if selected:
            return selected[0]
        if self.quotations:
            return min(self.quotations, key=lambda q: q.total_value or 0)
        return None


# ---------------------------------------------------------------------------
# Quotation  (Cotação de fornecedor para uma solicitação)
# ---------------------------------------------------------------------------
class Quotation(db.Model):
    __tablename__ = "quotations"

    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id"),
                                    nullable=False, index=True)
    supplier = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(100))
    purchase_link = db.Column(db.Text)
    quantity = db.Column(db.Float, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False, default=0.0)
    freight = db.Column(db.Float, default=0.0)
    total_value = db.Column(db.Float, nullable=False, default=0.0)
    payment_method = db.Column(db.String(100))
    installments = db.Column(db.Integer, default=1)  # quantidade de parcelas
    delivery_deadline = db.Column(db.String(100))
    invoice_attached = db.Column(db.Boolean, default=False)
    invoice_number = db.Column(db.String(80))
    is_selected = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)  # DATA DA COMPRA
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    purchase_request = db.relationship("PurchaseRequest", back_populates="quotations")


# ---------------------------------------------------------------------------
# MonthlyBudget  (Orçamento mensal por conta — vinculado ao AccountPlan)
# Armazena orçado, ajustado e realizado-projetado do arquivo mensal
# ---------------------------------------------------------------------------
class MonthlyBudget(db.Model):
    __tablename__ = "monthly_budgets"

    id = db.Column(db.Integer, primary_key=True)
    account_plan_id = db.Column(db.Integer, db.ForeignKey("account_plans.id"),
                                nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)   # 1-12
    budgeted_value = db.Column(db.Float, nullable=False, default=0.0)    # Orçado
    adjusted_value = db.Column(db.Float, nullable=False, default=0.0)   # Ajustado
    realized_value = db.Column(db.Float, nullable=False, default=0.0)   # Realizado/Projetado
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    account_plan = db.relationship("AccountPlan", back_populates="monthly_budgets")

    __table_args__ = (
        db.UniqueConstraint("account_plan_id", "year", "month",
                            name="uq_monthly_budget_account_year_month"),
    )
