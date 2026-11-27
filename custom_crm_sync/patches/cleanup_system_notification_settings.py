import frappe

OBSOLETE_FIELDS = [
    "include_actor",
    "extra_emails",
    "app_base_url",
    "deal_stage_change",
    "deal_updates",
    "leads",
    "tasks",
    "quotations",
    "sales_orders",
    "other_records",
    "delivery_mode",
    "scheduled_time",
    "interval_minutes",
    "last_dispatched",
    "delivery_schedule",
]


def execute():
    """Remove obsolete non-hierarchy fields from CRM Notification Settings tabSingles."""
    if not frappe.db.exists("DocType", "CRM Notification Settings"):
        return

    frappe.db.delete(
        "Singles",
        {
            "doctype": "CRM Notification Settings",
            "field": ["in", OBSOLETE_FIELDS],
        },
    )
    frappe.db.commit()
