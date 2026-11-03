import json
import traceback
import requests
import frappe
from frappe import _
from frappe.frappeclient import FrappeClient
from frappe.utils import now_datetime


def get_sync_settings():
    settings = frappe.get_single("Custom CRM Sync Settings")
    if not settings.enabled:
        frappe.throw(_("Custom CRM Sync is not enabled."))
    return settings


def get_erpnext_client():
    settings = get_sync_settings()
    api_key = settings.api_key
    api_secret = settings.get_password("api_secret")
    if not api_key or not api_secret:
        frappe.throw(_("API Key and Secret must be configured in Custom CRM Sync Settings."))
    
    return FrappeClient(
        url=settings.erpnext_url.rstrip("/"),
        api_key=api_key,
        api_secret=api_secret
    )


def log_event(event_type, direction, status, reference_doctype="", reference_name="", payload=None, error_message="", tb=""):
    try:
        log = frappe.new_doc("Custom CRM Sync Log")
        log.event_type = event_type
        log.direction = direction
        log.status = status
        log.reference_doctype = reference_doctype
        log.reference_name = reference_name
        log.payload = json.dumps(payload, indent=2, default=str) if isinstance(payload, (dict, list)) else str(payload or "")
        log.error_message = str(error_message)[:500] if error_message else ""
        log.traceback = str(tb) if tb else ""
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Failed to create Custom CRM Sync Log")


def upsert_crm_product(item):
    item_code = item.get("name") or item.get("item_code")
    if not item_code:
        return None
    
    item_name = item.get("item_name") or item_code
    rate = item.get("standard_rate") or 0.0
    disabled = 1 if item.get("disabled") else 0
    description = item.get("description") or ""
    image = item.get("image") or ""

    existing = frappe.db.get_value(
        "CRM Product",
        {"erpnext_item_code": item_code},
        ["name"],
        as_dict=True
    )

    if not existing:
        existing = frappe.db.get_value(
            "CRM Product",
            {"product_code": item_code},
            ["name"],
            as_dict=True
        )

    if existing:
        doc = frappe.get_doc("CRM Product", existing.name)
        doc.product_name = item_name
        doc.erpnext_item_code = item_code
        doc.standard_rate = rate
        doc.disabled = disabled
        if description and not doc.description:
            doc.description = description
        if image and not doc.image:
            doc.image = image
        doc.save(ignore_permissions=True)
        return doc.name
    else:
        doc = frappe.new_doc("CRM Product")
        doc.product_code = item_code
        doc.erpnext_item_code = item_code
        doc.product_name = item_name
        doc.standard_rate = rate
        doc.disabled = disabled
        doc.description = description
        doc.image = image
        doc.insert(ignore_permissions=True)
        return doc.name


@frappe.whitelist()
def pull_all_items():
    settings = get_sync_settings()
    url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Item"
    headers = {
        "Authorization": f"token {settings.api_key}:{settings.get_password('api_secret')}"
    }
    params = {
        "fields": json.dumps(["name", "item_code", "item_name", "standard_rate", "disabled", "description", "image"]),
        "limit_page_length": 0
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        err = f"Failed to fetch items from ERPNext: {resp.status_code} {resp.text}"
        log_event("Item Sync", "ERP to CRM", "Error", "Item", "", None, err)
        frappe.throw(err)

    items = resp.json().get("data", [])
    synced = 0
    for it in items:
        try:
            upsert_crm_product(it)
            synced += 1
        except Exception as e:
            log_event("Item Sync", "ERP to CRM", "Error", "Item", it.get("name"), it, str(e), traceback.format_exc())

    settings.last_item_sync = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    log_event("Item Sync", "ERP to CRM", "Success", "Item", f"Total: {synced}", {"synced_count": synced})
    return {"synced_count": synced}
