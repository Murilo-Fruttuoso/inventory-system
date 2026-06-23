from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)

    movements = db.relationship("StockMovement", back_populates="user", lazy=True)
    logs = db.relationship("ActionLog", back_populates="user", lazy=True)
    purchases = db.relationship("Purchase", back_populates="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.is_active_user


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text)
    category = db.Column(db.String(100), nullable=False, index=True)
    brand = db.Column(db.String(100))
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
        db.UniqueConstraint("name", "category", name="uq_products_name_category"),
    )

    __mapper_args__ = {"version_id_col": version_id}

    @property
    def low_stock(self):
        return self.quantity <= self.quantity_min

    @property
    def total_stock_value(self):
        return (self.unit_value or 0.0) * (self.quantity or 0.0)


class StockMovement(db.Model):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
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
