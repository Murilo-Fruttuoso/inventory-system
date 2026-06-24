from functools import wraps

from flask import abort
from flask_login import current_user


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role != "admin":
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped_view


def approver_required(view_func):
    """Permite acesso a admin e approver."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role not in ("admin", "approver"):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped_view


def buyer_required(view_func):
    """Permite acesso a admin, approver e buyer (Comprador).
    Comprador: acessa Compras, Orçamento, Relatórios — NÃO acessa Admin."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role not in ("admin", "approver", "buyer"):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped_view
