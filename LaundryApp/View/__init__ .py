# views/__init__.py

from .Expenses import (
    create_expense_field,
    expense_field_list,
    edit_expense_field,
    delete_expense_field,
    expense_form,
    expense_list,
    edit_expense_record,
    delete_expense_record,
)

from .customers import (
    customer_management,
    customer_add,
    customer_edit,
    customer_delete,
    customer_orders,
)
from .usermanage import *
__all__ = [
    # Expenses
    "create_expense_field",
    "expense_field_list",
    "edit_expense_field",
    "delete_expense_field",
    "expense_form",
    "expense_list",
    "edit_expense_record",
    "delete_expense_record",

    # Customers
    "search_customers",
    "customer_management",
    "customer_add",
    "customer_edit",
    "customer_delete",
    "customer_orders",

    #Users

    'user_add',
    'user_edit',
    'user_delete',
    'user_profile',
    'user_management',
]
