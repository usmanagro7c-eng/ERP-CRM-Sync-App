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


def parse_request_data():
    try:
        raw = frappe.request.get_data(as_text=True)
        if raw and raw.strip():
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and any(k != "cmd" for k in parsed.keys()):
                return parsed
    except Exception:
        pass

    try:
        data = frappe.request.get_json()
        if data and isinstance(data, dict) and any(k != "cmd" for k in data.keys()):
            return data
    except Exception:
        pass

    data = dict(frappe.form_dict)
    data.pop("cmd", None)
    return data


@frappe.whitelist(allow_guest=True)
def handle_item_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data or not (data.get("item_code") or data.get("name")):
            return {"status": "ignored", "message": "No item data received"}

        product_name = upsert_crm_product(data)
        log_event("Item Sync", "ERP to CRM", "Success", "CRM Product", product_name, data)
        return {"status": "success", "product": product_name}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Item Sync", "ERP to CRM", "Error", "Item", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def handle_quotation_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data:
            return {"status": "ignored"}

        qtn_name = data.get("name")
        crm_deal = data.get("crm_deal")
        grand_total = data.get("grand_total") or 0.0
        docstatus = data.get("docstatus", 0)

        # If crm_deal not in data directly, look up customer's crm_deal
        if not crm_deal and data.get("party_name"):
            crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": data.get("party_name")}, "name")

        if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
            status_text = "Submitted" if docstatus == 1 else "Draft"
            comment = f"ERPNext Quotation {qtn_name} ({status_text}) updated: Grand Total PKR {grand_total:,.2f}"
            deal_doc = frappe.get_doc("CRM Deal", crm_deal)
            deal_doc.add_comment("Comment", comment)

            # If deal is still in early stage, move to Proposal/Quotation
            if deal_doc.status == "Qualification" and docstatus == 1:
                deal_doc.status = "Proposal/Quotation"
                deal_doc.save(ignore_permissions=True)

            log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", qtn_name, data)
            return {"status": "success", "deal": crm_deal}

        log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", qtn_name, data, "No linked CRM deal found")
        return {"status": "ignored", "message": "No linked deal"}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Quotation Sync", "ERP to CRM", "Error", "Quotation", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def handle_sales_order_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data:
            return {"status": "ignored"}

        so_name = data.get("name")
        customer = data.get("customer")
        grand_total = data.get("grand_total") or 0.0
        docstatus = data.get("docstatus", 0)

        crm_deal = None
        # Try finding via customer
        if customer:
            crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": customer}, "name")

        if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
            deal_doc = frappe.get_doc("CRM Deal", crm_deal)
            status_text = "Submitted" if docstatus == 1 else "Draft"
            comment = f"Sales Order {so_name} ({status_text}) placed on ERPNext for PKR {grand_total:,.2f}"
            deal_doc.add_comment("Comment", comment)

            # If Sales Order submitted, ensure deal is Won
            if docstatus == 1 and deal_doc.status != "Won":
                deal_doc.status = "Won"
                deal_doc.annual_revenue = grand_total
                deal_doc.save(ignore_permissions=True)

            log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", so_name, data)
            return {"status": "success", "deal": crm_deal}

        log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", so_name, data, "No linked CRM deal found")
        return {"status": "ignored", "message": "No linked deal"}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Sales Order Sync", "ERP to CRM", "Error", "Sales Order", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_items():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and settings.auto_sync_items:
            pull_all_items()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled item sync failed")


def ensure_remote_customer_field_defaults():
    try:
        client = get_erpnext_client()
        need_update = False
        cf1 = client.get_doc("Custom Field", "Customer-custom_tax_payer_type")
        if not cf1.get("default"):
            cf1["default"] = "Unregistered"
            client.update(cf1)
        cf2 = client.get_doc("Custom Field", "Customer-custom_buyer_province")
        if not cf2.get("default"):
            cf2["default"] = "PUNJAB"
            client.update(cf2)
    except Exception:
        pass


def upsert_crm_organization(cust_data):
    cust_name = cust_data.get("customer_name") or cust_data.get("name")
    if not cust_name:
        return None

    existing = frappe.db.get_value("CRM Organization", {"organization_name": cust_name}, ["name"], as_dict=True)
    if not existing:
        existing = frappe.db.get_value("CRM Organization", cust_name, ["name"], as_dict=True)

    website = cust_data.get("website") or ""
    currency = cust_data.get("default_currency") or "PKR"
    territory = cust_data.get("territory") or ""
    valid_crm_territory = territory if (territory and frappe.db.exists("CRM Territory", territory)) else None

    if existing:
        org = frappe.get_doc("CRM Organization", existing.name)
        if website and not org.website:
            org.website = website
        if valid_crm_territory and not org.territory:
            org.territory = valid_crm_territory
        org.save(ignore_permissions=True)
        return org.name
    else:
        org = frappe.new_doc("CRM Organization")
        org.organization_name = cust_name
        org.website = website
        org.currency = currency
        if valid_crm_territory:
            org.territory = valid_crm_territory
        org.insert(ignore_permissions=True)
        return org.name


@frappe.whitelist(allow_guest=True)
def handle_customer_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data or not (data.get("customer_name") or data.get("name")):
            return {"status": "ignored", "message": "No customer data received"}

        org_name = upsert_crm_organization(data)
        log_event("Customer Sync", "ERP to CRM", "Success", "CRM Organization", org_name, data)
        return {"status": "success", "organization": org_name}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Customer Sync", "ERP to CRM", "Error", "Customer", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def pull_all_customers():
    settings = get_sync_settings()
    ensure_remote_customer_field_defaults()

    url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Customer"
    headers = {
        "Authorization": f"token {settings.api_key}:{settings.get_password('api_secret')}"
    }
    params = {
        "fields": json.dumps(["name", "customer_name", "customer_type", "customer_group", "territory", "default_currency", "website"]),
        "limit_page_length": 0
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        err = f"Failed to fetch customers from ERPNext: {resp.status_code} {resp.text}"
        log_event("Customer Sync", "ERP to CRM", "Error", "Customer", "", None, err)
        frappe.throw(err)

    customers = resp.json().get("data", [])
    synced = 0
    for c in customers:
        try:
            upsert_crm_organization(c)
            synced += 1
        except Exception as e:
            log_event("Customer Sync", "ERP to CRM", "Error", "Customer", c.get("name"), c, str(e), traceback.format_exc())

    settings.last_customer_sync = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    log_event("Customer Sync", "ERP to CRM", "Success", "Customer", f"Total: {synced}", {"synced_count": synced})
    return {"synced_count": synced}


def sync_recent_customers():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_customers", 1):
            pull_all_customers()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled customer sync failed")
