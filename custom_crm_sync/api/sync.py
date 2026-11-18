import json
import traceback
from contextlib import contextmanager
import requests
import frappe
from frappe import _
from frappe.frappeclient import FrappeClient
from frappe.utils import now_datetime


@contextmanager
def suppress_hierarchy_notifications():
    """Context manager to avoid notification loops/storms during sync operations."""
    prev = getattr(frappe.flags, "skip_hierarchy_notify", False)
    frappe.flags.skip_hierarchy_notify = True
    try:
        yield
    finally:
        frappe.flags.skip_hierarchy_notify = prev


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


# ─────────────────────────────────────────────
# ITEM SYNC  (ERPNext Item → CRM Product)
# ─────────────────────────────────────────────

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
    with suppress_hierarchy_notifications():
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


@frappe.whitelist(allow_guest=True)
def handle_item_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data or not (data.get("item_code") or data.get("name")):
            return {"status": "ignored", "message": "No item data received"}

        with suppress_hierarchy_notifications():
            product_name = upsert_crm_product(data)
        log_event("Item Sync", "ERP to CRM", "Success", "CRM Product", product_name, data)
        return {"status": "success", "product": product_name}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Item Sync", "ERP to CRM", "Error", "Item", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_items():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_items", 1):
            pull_all_items()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled item sync failed")


# ─────────────────────────────────────────────
# CUSTOMER SYNC  (ERPNext Customer → CRM Organization)
# ─────────────────────────────────────────────

def ensure_remote_customer_field_defaults():
    try:
        client = get_erpnext_client()
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
    with suppress_hierarchy_notifications():
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


@frappe.whitelist(allow_guest=True)
def handle_customer_webhook():
    data = None
    try:
        data = parse_request_data()
        if not data or not (data.get("customer_name") or data.get("name")):
            return {"status": "ignored", "message": "No customer data received"}

        with suppress_hierarchy_notifications():
            org_name = upsert_crm_organization(data)
        log_event("Customer Sync", "ERP to CRM", "Success", "CRM Organization", org_name, data)
        return {"status": "success", "organization": org_name}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Customer Sync", "ERP to CRM", "Error", "Customer", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_customers():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_customers", 1):
            pull_all_customers()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled customer sync failed")


# ─────────────────────────────────────────────
# CONTACT SYNC  (ERPNext Contact → CRM Contact & CRM Lead)
# ─────────────────────────────────────────────

def upsert_crm_contact(contact_data):
    first_name = (contact_data.get("first_name") or "").strip()
    last_name = (contact_data.get("last_name") or "").strip()
    full_name = (contact_data.get("full_name") or f"{first_name} {last_name}").strip()
    if not full_name and not contact_data.get("name"):
        return None

    email = (contact_data.get("email_id") or "").strip()
    phone = (contact_data.get("phone") or "").strip()
    mobile_no = (contact_data.get("mobile_no") or "").strip()

    if not phone and contact_data.get("phone_nos"):
        for p in contact_data["phone_nos"]:
            if p.get("phone"):
                phone = p["phone"].strip()
                if not mobile_no:
                    mobile_no = phone
                break

    if not email and contact_data.get("email_ids"):
        for e in contact_data["email_ids"]:
            if e.get("email_id"):
                email = e["email_id"].strip()
                break

    org_name = ""
    links = contact_data.get("links") or []
    for l in links:
        if l.get("link_doctype") in ["Customer", "CRM Organization"]:
            org_name = l.get("link_name")
            break

    # 1. Upsert standard Contact doc
    existing_contact = None
    if email:
        existing_contact = frappe.db.get_value("Contact", {"email_id": email}, "name")
    if not existing_contact and full_name:
        existing_contact = frappe.db.get_value("Contact", {"first_name": first_name or full_name, "last_name": last_name or ""}, "name")
    if not existing_contact and contact_data.get("name") and frappe.db.exists("Contact", contact_data.get("name")):
        existing_contact = contact_data.get("name")

    if existing_contact:
        cdoc = frappe.get_doc("Contact", existing_contact)
        if first_name: cdoc.first_name = first_name
        if last_name: cdoc.last_name = last_name
        if email: cdoc.email_id = email
        if phone: cdoc.phone = phone
        if mobile_no: cdoc.mobile_no = mobile_no
    else:
        cdoc = frappe.new_doc("Contact")
        cdoc.first_name = first_name or full_name
        cdoc.last_name = last_name or ""
        cdoc.email_id = email
        cdoc.phone = phone
        cdoc.mobile_no = mobile_no

    if org_name:
        target_doctype = "CRM Organization" if frappe.db.exists("CRM Organization", org_name) else "Customer"
        already = any(l.link_doctype == target_doctype and l.link_name == org_name for l in cdoc.get("links", []))
        if not already:
            cdoc.append("links", {
                "link_doctype": target_doctype,
                "link_name": org_name
            })

    cdoc.save(ignore_permissions=True)
    contact_name = cdoc.name

    # 2. Upsert CRM Lead (for Frappe CRM Desk view)
    existing_lead = None
    if email:
        existing_lead = frappe.db.get_value("CRM Lead", {"email": email}, "name")
    if not existing_lead and mobile_no:
        existing_lead = frappe.db.get_value("CRM Lead", {"mobile_no": mobile_no}, "name")
    if not existing_lead and full_name:
        existing_lead = frappe.db.get_value("CRM Lead", {"first_name": first_name or full_name, "last_name": last_name or ""}, "name")

    if existing_lead:
        ldoc = frappe.get_doc("CRM Lead", existing_lead)
        if first_name: ldoc.first_name = first_name
        if last_name: ldoc.last_name = last_name
        if email and not ldoc.email: ldoc.email = email
        if mobile_no and not ldoc.mobile_no: ldoc.mobile_no = mobile_no
        if org_name and not ldoc.organization: ldoc.organization = org_name
        ldoc.save(ignore_permissions=True)
    else:
        ldoc = frappe.new_doc("CRM Lead")
        ldoc.first_name = first_name or full_name
        ldoc.last_name = last_name or ""
        ldoc.email = email
        ldoc.mobile_no = mobile_no or phone
        if org_name: ldoc.organization = org_name
        ldoc.insert(ignore_permissions=True)

    return contact_name


@frappe.whitelist()
def pull_all_contacts():
    """Bulk pull all ERPNext Contacts → CRM Contact & CRM Lead"""
    settings = get_sync_settings()

    url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Contact"
    headers = {
        "Authorization": f"token {settings.api_key}:{settings.get_password('api_secret')}"
    }
    params = {
        "fields": json.dumps([
            "name", "first_name", "last_name", "full_name",
            "mobile_no", "phone", "email_id"
        ]),
        "limit_page_length": 500
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        err = f"Failed to fetch contacts from ERPNext: {resp.status_code} {resp.text}"
        log_event("Contact Sync", "ERP to CRM", "Error", "Contact", "", None, err)
        frappe.throw(err)

    contacts = resp.json().get("data", [])
    synced = 0
    with suppress_hierarchy_notifications():
        for ct in contacts:
            try:
                # Fetch full contact document for phone_nos, email_ids, links
                detail_url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Contact/{ct['name']}"
                det_resp = requests.get(detail_url, headers=headers, timeout=15)
                full_ct = det_resp.json().get("data", ct) if det_resp.status_code == 200 else ct

                contact_name = upsert_crm_contact(full_ct)
                ref_name = full_ct.get("full_name") or full_ct.get("name")
                log_event("Contact Sync", "ERP to CRM", "Success", "Contact", ref_name, full_ct)
                synced += 1
            except Exception as e:
                log_event("Contact Sync", "ERP to CRM", "Error", "Contact", ct.get("name", ""), ct, str(e), traceback.format_exc())

    settings.last_contact_sync = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    log_event("Contact Sync", "ERP to CRM", "Success", "Contact", f"Total: {synced}", {"synced_count": synced})
    return {"synced_count": synced}


@frappe.whitelist(allow_guest=True)
def handle_contact_webhook():
    """Webhook handler: ERPNext Contact → CRM Contact & CRM Lead"""
    data = None
    try:
        data = parse_request_data()
        if not data or not (data.get("first_name") or data.get("full_name") or data.get("name")):
            return {"status": "ignored", "message": "No contact data received"}

        with suppress_hierarchy_notifications():
            contact_name = upsert_crm_contact(data)
        ref_name = data.get("full_name") or data.get("first_name") or data.get("name")
        log_event("Contact Sync", "ERP to CRM", "Success", "Contact", ref_name, data)
        return {"status": "success", "contact": contact_name}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Contact Sync", "ERP to CRM", "Error", "Contact", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_contacts():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_contacts", 1):
            pull_all_contacts()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled contact sync failed")


# ─────────────────────────────────────────────
# QUOTATION SYNC  (ERPNext Quotation → CRM Deal)
# ─────────────────────────────────────────────

@frappe.whitelist()
def pull_all_quotations():
    """Bulk pull all ERPNext Quotations → update CRM Deals & create Sync Logs"""
    settings = get_sync_settings()

    url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Quotation"
    headers = {
        "Authorization": f"token {settings.api_key}:{settings.get_password('api_secret')}"
    }
    params = {
        "fields": json.dumps([
            "name", "party_name", "quotation_to", "grand_total", "docstatus", "status", "transaction_date"
        ]),
        "limit_page_length": 500,
        "order_by": "creation asc"
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        err = f"Failed to fetch quotations from ERPNext: {resp.status_code} {resp.text}"
        log_event("Quotation Sync", "ERP to CRM", "Error", "Quotation", "", None, err)
        frappe.throw(err)

    quotations = resp.json().get("data", [])
    synced = 0
    with suppress_hierarchy_notifications():
        for q in quotations:
            try:
                qtn_name = q.get("name")
                party_name = q.get("party_name")
                grand_total = q.get("grand_total") or 0.0
                docstatus = q.get("docstatus", 0)
                status_text = "Submitted" if docstatus == 1 else ("Cancelled" if docstatus == 2 else "Draft")

                crm_deal = None
                if party_name:
                    crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": party_name}, "name")
                    if not crm_deal:
                        crm_deal = frappe.db.get_value("CRM Deal", {"organization": party_name}, "name")

                ref_name = f"{qtn_name} ({party_name})" if party_name else qtn_name
                if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
                    deal_doc = frappe.get_doc("CRM Deal", crm_deal)
                    comment = f"ERPNext Quotation {qtn_name} ({status_text}): PKR {grand_total:,.2f}"
                    deal_doc.add_comment("Comment", comment)

                    if deal_doc.status == "Qualification" and docstatus == 1:
                        deal_doc.status = "Proposal/Quotation"
                        deal_doc.save(ignore_permissions=True)

                log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", ref_name, q)
                synced += 1
            except Exception as e:
                log_event("Quotation Sync", "ERP to CRM", "Error", "Quotation", q.get("name", ""), q, str(e), traceback.format_exc())

    settings.last_quotation_sync = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", f"Total: {synced}", {"synced_count": synced})
    return {"synced_count": synced}


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
        party_name = data.get("party_name")

        if not crm_deal and party_name:
            crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": party_name}, "name")
            if not crm_deal:
                crm_deal = frappe.db.get_value("CRM Deal", {"organization": party_name}, "name")

        status_text = "Submitted" if docstatus == 1 else ("Cancelled" if docstatus == 2 else "Draft")
        ref_name = f"{qtn_name} ({party_name})" if party_name else qtn_name

        if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
            comment = f"ERPNext Quotation {qtn_name} ({status_text}) updated: Grand Total PKR {grand_total:,.2f}"
            deal_doc = frappe.get_doc("CRM Deal", crm_deal)
            deal_doc.add_comment("Comment", comment)

            if deal_doc.status == "Qualification" and docstatus == 1:
                deal_doc.status = "Proposal/Quotation"
                deal_doc.save(ignore_permissions=True)

            log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", ref_name, data)

            try:
                from custom_crm_sync.api.notify import notify_entity
                notify_entity(
                    doctype="Quotation",
                    docname=ref_name,
                    action=status_text,
                    details={
                        "Grand Total": f"PKR {grand_total:,.2f}",
                        "Party Name": party_name,
                        "Status": status_text,
                        "Linked Deal": crm_deal
                    },
                    crm_deal=crm_deal
                )
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Failed to dispatch hierarchy notification for quotation")

            return {"status": "success", "deal": crm_deal}

        log_event("Quotation Sync", "ERP to CRM", "Success", "Quotation", ref_name, data)

        try:
            from custom_crm_sync.api.notify import notify_entity
            notify_entity(
                doctype="Quotation",
                docname=ref_name,
                action=status_text,
                details={
                    "Grand Total": f"PKR {grand_total:,.2f}",
                    "Party Name": party_name,
                    "Status": status_text
                },
                crm_deal=crm_deal
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Failed to dispatch hierarchy notification for quotation")

        return {"status": "success", "message": "Quotation logged"}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Quotation Sync", "ERP to CRM", "Error", "Quotation", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_quotations():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_quotations", 1):
            pull_all_quotations()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled quotation sync failed")


# ─────────────────────────────────────────────
# SALES ORDER SYNC  (ERPNext Sales Order → CRM Deal)
# ─────────────────────────────────────────────

@frappe.whitelist()
def pull_all_sales_orders():
    """Bulk pull all ERPNext Sales Orders → update CRM Deals & create Sync Logs"""
    settings = get_sync_settings()

    url = f"{settings.erpnext_url.rstrip('/')}/api/resource/Sales Order"
    headers = {
        "Authorization": f"token {settings.api_key}:{settings.get_password('api_secret')}"
    }
    params = {
        "fields": json.dumps([
            "name", "customer", "grand_total", "docstatus", "status", "transaction_date"
        ]),
        "limit_page_length": 500,
        "order_by": "creation asc"
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        err = f"Failed to fetch sales orders from ERPNext: {resp.status_code} {resp.text}"
        log_event("Sales Order Sync", "ERP to CRM", "Error", "Sales Order", "", None, err)
        frappe.throw(err)

    orders = resp.json().get("data", [])
    synced = 0
    with suppress_hierarchy_notifications():
        for so in orders:
            try:
                so_name = so.get("name")
                customer = so.get("customer")
                grand_total = so.get("grand_total") or 0.0
                docstatus = so.get("docstatus", 0)
                status_text = "Submitted" if docstatus == 1 else ("Cancelled" if docstatus == 2 else "Draft")

                crm_deal = None
                if customer:
                    crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": customer}, "name")
                    if not crm_deal:
                        crm_deal = frappe.db.get_value("CRM Deal", {"organization": customer}, "name")

                ref_name = f"{so_name} ({customer})" if customer else so_name
                if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
                    deal_doc = frappe.get_doc("CRM Deal", crm_deal)
                    comment = f"ERPNext Sales Order {so_name} ({status_text}): PKR {grand_total:,.2f}"
                    deal_doc.add_comment("Comment", comment)

                    if docstatus == 1 and deal_doc.status != "Won":
                        deal_doc.status = "Won"
                        deal_doc.annual_revenue = grand_total
                        deal_doc.save(ignore_permissions=True)

                log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", ref_name, so)
                synced += 1
            except Exception as e:
                log_event("Sales Order Sync", "ERP to CRM", "Error", "Sales Order", so.get("name", ""), so, str(e), traceback.format_exc())

    settings.last_sales_order_sync = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", f"Total: {synced}", {"synced_count": synced})
    return {"synced_count": synced}


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
        status_text = "Submitted" if docstatus == 1 else ("Cancelled" if docstatus == 2 else "Draft")

        crm_deal = None
        if customer:
            crm_deal = frappe.db.get_value("CRM Deal", {"erpnext_customer": customer}, "name")
            if not crm_deal:
                crm_deal = frappe.db.get_value("CRM Deal", {"organization": customer}, "name")

        ref_name = f"{so_name} ({customer})" if customer else so_name

        if crm_deal and frappe.db.exists("CRM Deal", crm_deal):
            deal_doc = frappe.get_doc("CRM Deal", crm_deal)
            comment = f"Sales Order {so_name} ({status_text}) placed on ERPNext for PKR {grand_total:,.2f}"
            deal_doc.add_comment("Comment", comment)

            if docstatus == 1 and deal_doc.status != "Won":
                deal_doc.status = "Won"
                deal_doc.annual_revenue = grand_total
                deal_doc.save(ignore_permissions=True)

            log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", ref_name, data)

            try:
                from custom_crm_sync.api.notify import notify_entity
                notify_entity(
                    doctype="Sales Order",
                    docname=ref_name,
                    action=status_text,
                    details={
                        "Grand Total": f"PKR {grand_total:,.2f}",
                        "Customer": customer,
                        "Status": status_text,
                        "Linked Deal": crm_deal
                    },
                    crm_deal=crm_deal
                )
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Failed to dispatch hierarchy notification for sales order")

            return {"status": "success", "deal": crm_deal}

        log_event("Sales Order Sync", "ERP to CRM", "Success", "Sales Order", ref_name, data)

        try:
            from custom_crm_sync.api.notify import notify_entity
            notify_entity(
                doctype="Sales Order",
                docname=ref_name,
                action=status_text,
                details={
                    "Grand Total": f"PKR {grand_total:,.2f}",
                    "Customer": customer,
                    "Status": status_text
                },
                crm_deal=crm_deal
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Failed to dispatch hierarchy notification for sales order")

        return {"status": "success", "message": "Sales order logged"}
    except Exception as e:
        tb = traceback.format_exc()
        log_event("Sales Order Sync", "ERP to CRM", "Error", "Sales Order", "", data, str(e), tb)
        return {"status": "error", "message": str(e)}


def sync_recent_sales_orders():
    try:
        settings = frappe.get_single("Custom CRM Sync Settings")
        if settings.enabled and getattr(settings, "auto_sync_sales_orders", 1):
            pull_all_sales_orders()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Scheduled sales order sync failed")
