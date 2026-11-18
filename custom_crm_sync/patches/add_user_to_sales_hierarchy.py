import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """
    Idempotent patch: Ensure 'user' and 'notification_email' fields exist on
    'CRM Sales Hierarchy' without duplicating or breaking existing schemas.
    """
    if not frappe.db.exists("DocType", "CRM Sales Hierarchy"):
        return

    meta = frappe.get_meta("CRM Sales Hierarchy")
    fields_to_add = []

    if not meta.has_field("user"):
        fields_to_add.append({
            "fieldname": "user",
            "label": "User",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "is_group",
            "reqd": 0,
            "in_list_view": 1,
            "in_standard_filter": 1,
        })

    if not meta.has_field("notification_email"):
        fields_to_add.append({
            "fieldname": "notification_email",
            "label": "Notification Email Override",
            "fieldtype": "Data",
            "options": "Email",
            "insert_after": "user",
            "reqd": 0,
            "description": "Optional override email for hierarchy notifications if different from User account email",
        })

    if fields_to_add:
        create_custom_fields(
            {"CRM Sales Hierarchy": fields_to_add},
            update=True
        )
        frappe.clear_cache(doctype="CRM Sales Hierarchy")
