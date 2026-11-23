import json
import traceback
from datetime import timedelta
import frappe
from frappe import _
from frappe.utils import escape_html, now_datetime, validate_email_address


def _get_time_parts(value):
    if not value:
        return 0, 0
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return hours, minutes
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value.hour, value.minute
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def _get_target_time(now, time_value):
    """Build today's target datetime (naive, system timezone) from a time value."""
    hour, minute = _get_time_parts(time_value)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def get_delivery_config(settings):
    """
    Safely extract delivery configuration.
    Supports both direct DocType fields (post-migration) and delivery_schedule JSON string (pre-migration).
    Returns (delivery_mode, scheduled_time, interval_minutes).
    """
    if not settings:
        return "instant", "09:00", 60

    sched_json = {}
    raw_schedule = getattr(settings, "delivery_schedule", None)
    if raw_schedule:
        try:
            sched_json = json.loads(raw_schedule)
        except Exception:
            sched_json = {}

    raw_mode = getattr(settings, "delivery_mode", None) or sched_json.get("delivery_mode") or "Instant"
    mode_str = str(raw_mode).strip().lower()
    if "sched" in mode_str:
        delivery_mode = "scheduled"
    elif "interv" in mode_str:
        delivery_mode = "interval"
    else:
        delivery_mode = "instant"

    raw_time = getattr(settings, "scheduled_time", None) or sched_json.get("scheduled_time") or "09:00"
    scheduled_time = str(raw_time)[:5]

    try:
        raw_interval = getattr(settings, "interval_minutes", None) or sched_json.get("interval_minutes") or 60
        interval_minutes = int(raw_interval)
    except Exception:
        interval_minutes = 60

    return delivery_mode, scheduled_time, interval_minutes


def get_notification_settings_doc():
    """Return the CRM Notification Settings single doc or None if not installed yet."""
    if not frappe.db.exists("DocType", "CRM Notification Settings"):
        return None
    return frappe.get_single("CRM Notification Settings")


@frappe.whitelist()
def get_notification_settings():
    """
    Fetch current notification configuration and hierarchy tree nodes.
    Requires an authenticated user session.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to view notification settings."), frappe.PermissionError)

    settings = get_notification_settings_doc()
    if not settings:
        return {"settings": {}, "tree": []}

    selected_nodes = [d.node for d in (settings.selected_nodes or []) if d.node]

    delivery_mode, scheduled_time, interval_minutes = get_delivery_config(settings)
    settings_dict = {
        "enabled": bool(settings.enabled),
        "mode": settings.mode or "All Ancestors",
        "selected_nodes": selected_nodes,
        "include_actor": bool(settings.include_actor),
        "extra_emails": settings.extra_emails or "",
        "app_base_url": settings.app_base_url or "https://pipedrive-crm.usman-agro7c.workers.dev",
        "deal_stage_change": bool(settings.deal_stage_change),
        "deal_updates": bool(settings.deal_updates),
        "leads": bool(settings.leads),
        "tasks": bool(settings.tasks),
        "quotations": bool(settings.quotations),
        "sales_orders": bool(settings.sales_orders),
        "other_records": bool(settings.other_records),
        "delivery_mode": delivery_mode,
        "scheduled_time": scheduled_time,
        "interval_minutes": interval_minutes,
        "delivery_schedule": getattr(settings, "delivery_schedule", None) or "",
        "last_dispatched": str(getattr(settings, "last_dispatched", None) or ""),
    }

    # Fetch hierarchy tree nodes from "CRM Sales Hierarchy"
    tree_nodes = []
    if frappe.db.exists("DocType", "CRM Sales Hierarchy"):
        has_notification_email = frappe.get_meta("CRM Sales Hierarchy").has_field("notification_email")
        fields = ["name", "full_name", "reports_to", "is_group", "user", "lft", "rgt"]
        if has_notification_email:
            fields.append("notification_email")

        records = frappe.get_all(
            "CRM Sales Hierarchy",
            fields=fields,
            order_by="lft asc"
        )

        # Batch resolve active user emails
        user_ids = [r.user for r in records if r.user]
        user_email_map = {}
        if user_ids:
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", user_ids], "enabled": 1},
                fields=["name", "email"]
            )
            user_email_map = {u.name: u.email for u in active_users}

        for r in records:
            email = ""
            if has_notification_email and r.get("notification_email"):
                email = r.get("notification_email").strip()
            elif r.user and r.user in user_email_map:
                email = user_email_map[r.user]

            tree_nodes.append({
                "name": r.name,
                "label": r.full_name or r.name,
                "parent": r.reports_to or "",
                "is_group": int(r.is_group or 0),
                "user": r.user or "",
                "email": email or "",
            })

    return {
        "settings": settings_dict,
        "tree": tree_nodes,
    }


@frappe.whitelist()
def save_notification_settings(payload=None):
    """
    Save notification configuration.
    Restricted to System Manager and Sales Manager roles.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to save notification settings."), frappe.PermissionError)

    user_roles = frappe.get_roles(frappe.session.user)
    if "System Manager" not in user_roles and "Sales Manager" not in user_roles:
        frappe.throw(_("Only System Managers or Sales Managers can modify notification settings."), frappe.PermissionError)

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            frappe.throw(_("Invalid JSON payload."))

    if not isinstance(payload, dict):
        payload = dict(frappe.form_dict)

    settings = get_notification_settings_doc()
    if not settings:
        frappe.throw(_("CRM Notification Settings DocType is not available on this site."))

    allowed_modes = ["Direct Parent", "All Ancestors", "Selected Nodes"]
    if "mode" in payload:
        mode = payload.get("mode")
        if mode not in allowed_modes:
            frappe.throw(_("Invalid mode '{0}'. Allowed modes: {1}").format(mode, ", ".join(allowed_modes)))
        settings.mode = mode

    if "enabled" in payload:
        settings.enabled = 1 if payload.get("enabled") else 0
    if "include_actor" in payload:
        settings.include_actor = 1 if payload.get("include_actor") else 0
    if "app_base_url" in payload:
        settings.app_base_url = (payload.get("app_base_url") or "").rstrip("/")

    # Extra emails validation
    if "extra_emails" in payload:
        raw_extras = payload.get("extra_emails") or ""
        valid_extras = []
        if raw_extras:
            for em in raw_extras.replace("\n", ",").split(","):
                em_clean = em.strip()
                if em_clean:
                    validate_email_address(em_clean, throw=True)
                    valid_extras.append(em_clean)
        settings.extra_emails = ", ".join(valid_extras)

    # Event toggles
    for evt in ["deal_stage_change", "deal_updates", "leads", "tasks", "quotations", "sales_orders", "other_records"]:
        if evt in payload:
            setattr(settings, evt, 1 if payload.get(evt) else 0)

    # Selected nodes
    if "selected_nodes" in payload:
        nodes = payload.get("selected_nodes") or []
        if isinstance(nodes, str):
            try:
                nodes = json.loads(nodes)
            except Exception:
                nodes = [n.strip() for n in nodes.split(",") if n.strip()]

        if not isinstance(nodes, list):
            frappe.throw(_("selected_nodes must be a list of hierarchy node identifiers."))

        # Verify nodes exist in CRM Sales Hierarchy
        if nodes:
            existing = set(frappe.get_all("CRM Sales Hierarchy", filters={"name": ["in", nodes]}, pluck="name"))
            invalid = [n for n in nodes if n not in existing]
            if invalid:
                frappe.throw(_("Unknown hierarchy nodes: {0}").format(", ".join(invalid)))

        settings.set("selected_nodes", [])
        for n in nodes:
            settings.append("selected_nodes", {"node": n})

    # Email Delivery Timing & Schedule
    if "delivery_mode" in payload:
        mode_val = str(payload.get("delivery_mode") or "Instant").strip().lower()
        if "sched" in mode_val:
            settings.delivery_mode = "Daily Scheduled"
        elif "interv" in mode_val:
            settings.delivery_mode = "Periodic Interval"
        else:
            settings.delivery_mode = "Instant"

    if "scheduled_time" in payload:
        settings.scheduled_time = payload.get("scheduled_time") or "09:00:00"

    if "interval_minutes" in payload:
        try:
            settings.interval_minutes = int(payload.get("interval_minutes") or 60)
        except (ValueError, TypeError):
            settings.interval_minutes = 60

    if "delivery_schedule" in payload:
        settings.delivery_schedule = payload.get("delivery_schedule")

    settings.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True}


def resolve_recipients(actor_user, settings):
    """
    Resolve target email recipients based on the actor and hierarchy settings.
    - 'Direct Parent': Immediate parent node in CRM Sales Hierarchy.
    - 'All Ancestors': Full management ancestor chain up to root.
    - 'Selected Nodes': Admin-ticked nodes (actor independent).
    - Appends extra_emails.
    - Excludes actor unless include_actor is enabled.
    - De-duplicates case-insensitively.
    """
    if not settings or not settings.enabled:
        return []

    mode = settings.mode or "All Ancestors"
    target_node_ids = set()

    if mode == "Selected Nodes":
        for row in (settings.selected_nodes or []):
            if row.node:
                target_node_ids.add(row.node)
    else:
        # Need to find actor's node in CRM Sales Hierarchy
        actor_node = None
        if actor_user:
            actor_node = frappe.db.get_value(
                "CRM Sales Hierarchy",
                {"user": actor_user},
                ["name", "reports_to"],
                as_dict=True
            )

        if not actor_node:
            frappe.log_error(
                f"Actor user '{actor_user}' is not mapped to any node in CRM Sales Hierarchy.",
                "Hierarchy Notification - Actor Not Found"
            )
        else:
            if mode == "Direct Parent":
                if actor_node.reports_to:
                    target_node_ids.add(actor_node.reports_to)
            elif mode == "All Ancestors":
                try:
                    ancestors = frappe.utils.nestedset.get_ancestors_of("CRM Sales Hierarchy", actor_node.name)
                    for anc in ancestors:
                        target_node_ids.add(anc)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to get ancestors for hierarchy node {actor_node.name}: {str(e)}",
                        "Hierarchy Notification - Ancestor Lookup Failed"
                    )

    resolved_emails = set()

    if target_node_ids:
        has_notification_email = frappe.get_meta("CRM Sales Hierarchy").has_field("notification_email")
        fields = ["name", "user"]
        if has_notification_email:
            fields.append("notification_email")

        nodes = frappe.get_all("CRM Sales Hierarchy", filters={"name": ["in", list(target_node_ids)]}, fields=fields)
        user_ids = [n.user for n in nodes if n.user]

        user_email_map = {}
        if user_ids:
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", user_ids], "enabled": 1},
                fields=["name", "email"]
            )
            user_email_map = {u.name: u.email.strip().lower() for u in active_users if u.email}

        for n in nodes:
            if has_notification_email and n.get("notification_email"):
                resolved_emails.add(n.get("notification_email").strip().lower())
            elif n.user and n.user in user_email_map:
                resolved_emails.add(user_email_map[n.user])

    # Extra emails
    if settings.extra_emails:
        for em in settings.extra_emails.replace("\n", ",").split(","):
            cleaned = em.strip().lower()
            if cleaned and "@" in cleaned:
                resolved_emails.add(cleaned)

    # Actor inclusion / exclusion
    actor_email = None
    if actor_user:
        actor_email = frappe.db.get_value("User", actor_user, "email")

    if settings.include_actor and actor_email:
        # Explicitly add actor's own email to recipients
        resolved_emails.add(actor_email.strip().lower())
    elif not settings.include_actor and actor_user:
        # Remove actor from recipient list
        actor_emails_to_remove = {actor_user.strip().lower()}
        if actor_email:
            actor_emails_to_remove.add(actor_email.strip().lower())
        resolved_emails = {em for em in resolved_emails if em not in actor_emails_to_remove}

    return sorted(list(resolved_emails))


@frappe.whitelist()
def preview_recipients(mode, selected_nodes=None, user=None):
    """
    Simulate recipient resolution for UI preview panels.
    Allows passing a custom mode, selected_nodes list, and actor user.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to preview recipients."), frappe.PermissionError)

    settings = get_notification_settings_doc()
    if not settings:
        return {"recipients": [], "count": 0}

    # Create an in-memory clone of settings with preview overrides
    class MockSettings:
        pass

    mock_settings = MockSettings()
    mock_settings.enabled = True
    mock_settings.mode = mode or settings.mode or "All Ancestors"
    mock_settings.include_actor = settings.include_actor
    mock_settings.extra_emails = settings.extra_emails

    if selected_nodes is not None:
        if isinstance(selected_nodes, str):
            try:
                selected_nodes = json.loads(selected_nodes)
            except Exception:
                selected_nodes = [s.strip() for s in selected_nodes.split(",") if s.strip()]

        class NodeRow:
            def __init__(self, node):
                self.node = node

        mock_settings.selected_nodes = [NodeRow(n) for n in selected_nodes if n]
    else:
        mock_settings.selected_nodes = settings.selected_nodes

    actor_user = user or frappe.session.user
    recipients = resolve_recipients(actor_user, mock_settings)
    return {"recipients": recipients, "count": len(recipients)}


@frappe.whitelist()
def send_test_notification():
    """
    Send an immediate test notification to resolved recipients for the current user.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required."), frappe.PermissionError)

    settings = get_notification_settings_doc()
    if not settings:
        frappe.throw(_("CRM Notification Settings not found."))

    recipients = resolve_recipients(frappe.session.user, settings)
    if not recipients:
        frappe.throw(_("No recipients resolved for current user under mode '{0}'.").format(settings.mode))

    now = now_datetime().strftime("%d %b %Y, %I:%M %p")
    subject = "✅ [AgroCRM] Test Notification Email"
    content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #10b981; border-radius: 12px; overflow: hidden; background-color: #ffffff;">
      <div style="background: linear-gradient(135deg, #059669, #047857); padding: 20px 24px; color: #ffffff;">
        <h2 style="margin: 0; font-size: 18px; font-weight: 700;">AgroCRM · Hierarchy Test Notification</h2>
      </div>
      <div style="padding: 24px; color: #334155; font-size: 13px; line-height: 1.6;">
        <p>This is a live test notification sent from the <strong>Frappe CRM Hierarchy Notification System</strong>.</p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px;">
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600; width: 140px;">Dispatched By:</td><td>{escape_html(frappe.session.user)}</td></tr>
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Active Mode:</td><td><strong>{escape_html(settings.mode)}</strong></td></tr>
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Date & Time:</td><td>{now}</td></tr>
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Resolved Recipients:</td><td>{escape_html(', '.join(recipients))}</td></tr>
        </table>
      </div>
    </div>
    """.strip()

    frappe.sendmail(
        recipients=recipients,
        subject=subject,
        message=content,
        now=True
    )

    return {"success": True, "recipients": recipients}


# ─────────────────────────────────────────────
# HTML EMAIL TEMPLATES (Ported from AgroCRM)
# ─────────────────────────────────────────────

def get_record_url(app_base_url, doctype, docname):
    base = app_base_url.rstrip("/")
    if doctype == "CRM Deal":
        return f"{base}/deals/{docname}"
    elif doctype == "CRM Lead":
        return f"{base}/leads/{docname}"
    elif doctype == "Quotation":
        return f"{base}/quotations/{docname}"
    elif doctype == "Sales Order":
        return f"{base}/orders/{docname}"
    elif doctype == "CRM Organization":
        return f"{base}/organizations/{docname}"
    elif doctype == "Contact":
        return f"{base}/contacts/{docname}"
    return base


def format_stage_change_html(app_base_url, deal_id, deal_title, from_stage, to_stage, organization, deal_value, modified_by):
    deal_url = get_record_url(app_base_url, "CRM Deal", deal_id)
    now = now_datetime().strftime("%d %b %Y, %I:%M %p")
    val_str = f"{deal_value:,.2f}" if isinstance(deal_value, (int, float)) else str(deal_value or "0")

    from_stage_html = ""
    if from_stage:
        from_stage_html = f"""
        <span style="background-color: #e2e8f0; color: #475569; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600;">{escape_html(from_stage)}</span>
        <span style="margin: 0 10px; font-size: 15px; color: #94a3b8;">➔</span>
        """

    org_row = ""
    if organization:
        org_row = f'<tr><td style="padding: 8px 0; color: #64748b; font-weight: 600;">Organization:</td><td style="color: #0f172a;">{escape_html(organization)}</td></tr>'

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 620px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; background-color: #ffffff; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
      <div style="background: linear-gradient(135deg, #1e293b, #0f172a); padding: 22px 24px; color: #ffffff;">
        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 4px; font-weight: 600;">AgroCRM · Deal Stage Alert</div>
        <h1 style="margin: 0; font-size: 20px; font-weight: 700; color: #ffffff;">Deal Stage Changed</h1>
      </div>

      <div style="padding: 24px;">
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 20px; text-align: center;">
          {from_stage_html}
          <span style="background-color: #10b981; color: #ffffff; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;">New Stage: {escape_html(to_stage)}</span>
        </div>

        <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px;">
          <tr><td style="padding: 8px 0; color: #64748b; font-weight: 600; width: 140px;">Deal:</td><td style="color: #0f172a; font-weight: bold;">{escape_html(deal_title or deal_id)} ({escape_html(deal_id)})</td></tr>
          {org_row}
          <tr><td style="padding: 8px 0; color: #64748b; font-weight: 600;">Deal Value:</td><td style="color: #0f172a; font-weight: bold;">PKR {escape_html(val_str)}</td></tr>
          <tr><td style="padding: 8px 0; color: #64748b; font-weight: 600;">Modified By:</td><td style="color: #0f172a;">{escape_html(modified_by or '')}</td></tr>
          <tr><td style="padding: 8px 0; color: #64748b; font-weight: 600;">Date & Time:</td><td style="color: #0f172a;">{now}</td></tr>
        </table>

        <div style="text-align: center; margin-top: 24px;">
          <a href="{deal_url}" style="background-color: #0f172a; color: #ffffff; padding: 10px 22px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">View Deal in AgroCRM</a>
        </div>
      </div>
    </div>
    """.strip()


def format_entity_change_html(app_base_url, doctype, docname, action, title=None, summary=None, details=None, modified_by=None):
    record_url = get_record_url(app_base_url, doctype, docname)
    now = now_datetime().strftime("%d %b %Y, %I:%M %p")

    extra_rows = ""
    if details and isinstance(details, dict):
        for k, v in details.items():
            if v is not None and v != "":
                extra_rows += f'<tr><td style="padding: 6px 0; color: #64748b; font-weight: 600; width: 140px;">{escape_html(str(k))}:</td><td style="color: #0f172a;">{escape_html(str(v))}</td></tr>'

    title_row = f'<tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Title / Name:</td><td style="color: #0f172a;">{escape_html(title)}</td></tr>' if title else ""
    summary_row = f'<tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Summary:</td><td style="color: #0f172a;">{escape_html(summary)}</td></tr>' if summary else ""

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 620px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; background-color: #ffffff; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
      <div style="background: linear-gradient(135deg, #1e293b, #0f172a); padding: 22px 24px; color: #ffffff;">
        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 4px; font-weight: 600;">AgroCRM · System Notification</div>
        <h1 style="margin: 0; font-size: 20px; font-weight: 700; color: #ffffff;">{escape_html(doctype)} {escape_html(action)}</h1>
      </div>

      <div style="padding: 24px;">
        <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px;">
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600; width: 140px;">Record Type:</td><td style="color: #0f172a; font-weight: 600;">{escape_html(doctype)}</td></tr>
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Record ID:</td><td style="color: #0f172a; font-weight: bold;">{escape_html(docname)}</td></tr>
          {title_row}
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Action:</td><td style="color: #0f172a;"><span style="background-color: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-weight: 600;">{escape_html(action)}</span></td></tr>
          {summary_row}
          {extra_rows}
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Modified By:</td><td style="color: #0f172a;">{escape_html(modified_by or '')}</td></tr>
          <tr><td style="padding: 6px 0; color: #64748b; font-weight: 600;">Date & Time:</td><td style="color: #0f172a;">{now}</td></tr>
        </table>

        <div style="text-align: center; margin-top: 24px;">
          <a href="{record_url}" style="background-color: #0f172a; color: #ffffff; padding: 10px 22px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; display: inline-block;">Open in AgroCRM</a>
        </div>
      </div>
    </div>
    """.strip()


# ─────────────────────────────────────────────
# HOOKS & DISPATCH LOGIC
# ─────────────────────────────────────────────

def dispatch_or_queue_notification(recipients, subject, content, reference_doctype, reference_name):
    """
    Decides whether to dispatch immediately or buffer into CRM Pending Notification.
    Instant mode: sends immediately.
    Scheduled or Periodic Interval: buffers into pending queue.
    """
    if not recipients:
        return

    settings = get_notification_settings_doc()
    delivery_mode, scheduled_time, interval_minutes = get_delivery_config(settings)

    if delivery_mode == "instant":
        _enqueue_mail(recipients, subject, content, reference_doctype, reference_name)
    else:
        try:
            recips_str = ", ".join(recipients) if isinstance(recipients, list) else str(recipients)
            pending = frappe.get_doc({
                "doctype": "CRM Pending Notification",
                "status": "Pending",
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "recipients": recips_str,
                "subject": subject,
                "content": content
            })
            pending.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"dispatch_or_queue_notification buffer error: {str(e)}")
            _enqueue_mail(recipients, subject, content, reference_doctype, reference_name)


@frappe.whitelist()
def process_notification_queue():
    """
    Triggered every minute by cron '* * * * *'.
    Evaluates whether daily scheduled time has arrived or periodic interval has elapsed,
    and dispatches all pending notifications.
    Can also be manually triggered by System Managers.
    """
    try:
        settings = get_notification_settings_doc()
        if not settings or not settings.enabled:
            return {"dispatched": 0, "status": "disabled"}

        delivery_mode, scheduled_time, interval_minutes = get_delivery_config(settings)
        if delivery_mode == "instant":
            return {"dispatched": 0, "status": "instant_mode"}

        now = now_datetime()
        today = frappe.utils.getdate(now)
        should_send = False

        if delivery_mode == "scheduled":
            # Daily Scheduled Time evaluation (from notification_templates pattern)
            target = _get_target_time(now, scheduled_time)
            raw_last_run = getattr(settings, "last_dispatched", None)

            already_sent_today = False
            if raw_last_run:
                last_run = frappe.utils.get_datetime(raw_last_run)
                already_sent_today = (frappe.utils.getdate(last_run) == today and last_run >= target)

            if now >= target and not already_sent_today:
                should_send = True

        elif delivery_mode == "interval":
            # Periodic Interval evaluation (from notification_templates pattern)
            interval_delta = timedelta(minutes=interval_minutes)
            raw_last_run = getattr(settings, "last_dispatched", None)

            if not raw_last_run:
                should_send = True
            else:
                last_run = frappe.utils.get_datetime(raw_last_run)
                if (now - last_run) >= interval_delta:
                    should_send = True

        if not should_send:
            return {"dispatched": 0, "status": "not_due"}

        # Fetch pending notifications
        if not frappe.db.exists("DocType", "CRM Pending Notification"):
            return {"dispatched": 0, "status": "no_pending_doctype"}

        pending_records = frappe.get_all(
            "CRM Pending Notification",
            filters={"status": "Pending"},
            fields=["name", "recipients", "subject", "content", "reference_doctype", "reference_name"],
            order_by="creation asc",
            limit=200
        )

        if not pending_records:
            frappe.db.set_single_value("CRM Notification Settings", "last_dispatched", now, update_modified=False)
            return {"dispatched": 0, "status": "empty_queue"}

        dispatched_count = 0
        for item in pending_records:
            recips = [r.strip() for r in item.recipients.split(",") if r.strip()]
            _enqueue_mail(
                recipients=recips,
                subject=item.subject,
                content=item.content,
                reference_doctype=item.reference_doctype,
                reference_name=item.reference_name
            )
            frappe.db.set_value("CRM Pending Notification", item.name, "status", "Dispatched")
            dispatched_count += 1

        frappe.db.set_single_value("CRM Notification Settings", "last_dispatched", now, update_modified=False)
        frappe.db.commit()
        return {"dispatched": dispatched_count, "status": "success"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"process_notification_queue error: {str(e)}")
        return {"dispatched": 0, "status": "error", "error": str(e)}


@frappe.whitelist()
def get_queue_status():
    """
    Return current queue status, delivery mode, pending count, and recent email dispatches.
    Accessible to authenticated users.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required."), frappe.PermissionError)

    settings = get_notification_settings_doc()
    delivery_mode, scheduled_time, interval_minutes = get_delivery_config(settings)

    pending_count = 0
    dispatched_count = 0
    pending_items = []

    if frappe.db.exists("DocType", "CRM Pending Notification"):
        pending_count = frappe.db.count("CRM Pending Notification", {"status": "Pending"})
        dispatched_count = frappe.db.count("CRM Pending Notification", {"status": "Dispatched"})
        pending_items = frappe.get_all(
            "CRM Pending Notification",
            fields=["name", "status", "reference_doctype", "reference_name", "recipients", "subject", "creation"],
            order_by="creation desc",
            limit=10
        )

    # Also inspect recent Frappe Email Queue
    recent_emails = []
    if frappe.db.exists("DocType", "Email Queue"):
        recent_emails = frappe.get_all(
            "Email Queue",
            fields=["name", "status", "sender", "creation", "modified"],
            order_by="creation desc",
            limit=5
        )

    return {
        "delivery_mode": delivery_mode,
        "scheduled_time": scheduled_time,
        "interval_minutes": interval_minutes,
        "last_dispatched": str(getattr(settings, "last_dispatched", None) or ""),
        "pending_count": pending_count,
        "dispatched_count": dispatched_count,
        "pending_items": pending_items,
        "recent_emails": recent_emails,
    }


def on_change(doc, method=None):
    """
    Unified doc_events hook handler for CRM records.
    Never blocks saving, safe against loops and bulk syncs.
    """
    try:
        # Loop & bulk import guards
        if (
            getattr(frappe.flags, "in_import", False)
            or getattr(frappe.flags, "in_migrate", False)
            or getattr(frappe.flags, "in_install", False)
            or getattr(frappe.flags, "in_patch", False)
            or getattr(frappe.flags, "skip_hierarchy_notify", False)
        ):
            return

        settings = get_notification_settings_doc()
        if not settings or not settings.enabled:
            return

        doctype = doc.doctype
        actor_user = doc.modified_by or doc.owner or frappe.session.user

        # Ignore automated system changes
        if actor_user in ["Administrator", "Guest"] and not settings.include_actor:
            # Still process if administrator is explicitly mapped in hierarchy
            pass

        app_base_url = settings.app_base_url or "https://pipedrive-crm.usman-agro7c.workers.dev"

        if doctype == "CRM Deal":
            # CRM Deal has no 'deal_title' field — use organization_name or name as label
            deal_label = getattr(doc, "organization_name", None) or getattr(doc, "organization", None) or doc.name
            # Correct field names: deal_value (not annual_revenue), expected_closure_date (not expected_closing_date)
            deal_value = getattr(doc, "deal_value", None) or getattr(doc, "annual_revenue", None) or 0

            if method == "after_insert":
                if not settings.deal_updates:
                    return
                recipients = resolve_recipients(actor_user, settings)
                if not recipients:
                    return
                subject = f"🎯 [New Deal] Deal \"{deal_label}\" created"
                content = format_entity_change_html(
                    app_base_url, doctype, doc.name, "Created",
                    title=deal_label,
                    details={"Stage": doc.status, "Deal Value": f"PKR {deal_value:,.2f}" if deal_value else "0", "Organization": doc.organization},
                    modified_by=actor_user
                )
                dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)

            elif method == "on_update":
                has_stage_changed = doc.has_value_changed("status")
                if has_stage_changed:
                    if not settings.deal_stage_change:
                        return
                    prev_doc = doc.get_doc_before_save()
                    from_stage = prev_doc.status if prev_doc else ""
                    to_stage = doc.status

                    recipients = resolve_recipients(actor_user, settings)
                    if not recipients:
                        return

                    subject = f"🎯 [Stage Alert] Deal \"{deal_label}\" moved to \"{to_stage}\""
                    content = format_stage_change_html(
                        app_base_url, doc.name, deal_label,
                        from_stage, to_stage, doc.organization, deal_value, actor_user
                    )
                    dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)
                else:
                    if not settings.deal_updates:
                        return
                    # Check if meaningful fields changed (using correct field names)
                    meaningful = ["deal_value", "organization", "lead", "probability", "expected_closure_date", "organization_name"]
                    changed = [f for f in meaningful if doc.has_value_changed(f)]
                    if not changed:
                        return

                    recipients = resolve_recipients(actor_user, settings)
                    if not recipients:
                        return

                    changed_details = {doc.meta.get_label(f) or f: getattr(doc, f) for f in changed}
                    subject = f"[AgroCRM Alert] Deal \"{deal_label}\" updated"
                    content = format_entity_change_html(
                        app_base_url, doctype, doc.name, "Updated",
                        title=deal_label, details=changed_details, modified_by=actor_user
                    )
                    dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)

        elif doctype == "CRM Lead":
            if not settings.leads:
                return
            recipients = resolve_recipients(actor_user, settings)
            if not recipients:
                return

            action = "Created" if method == "after_insert" else "Updated"
            lead_name = f"{doc.first_name or ''} {doc.last_name or ''}".strip() or doc.name
            subject = f"[AgroCRM Alert] Lead \"{lead_name}\" was {action}"
            content = format_entity_change_html(
                app_base_url, doctype, doc.name, action,
                title=lead_name,
                details={"Organization": doc.organization, "Email": doc.email, "Mobile": doc.mobile_no},
                modified_by=actor_user
            )
            dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)

        elif doctype == "CRM Task":
            if not settings.tasks:
                return
            recipients = resolve_recipients(actor_user, settings)
            if not recipients:
                return

            action = "Created" if method == "after_insert" else "Updated"
            subject = f"[AgroCRM Alert] Task \"{doc.title or doc.name}\" was {action}"
            content = format_entity_change_html(
                app_base_url, doctype, doc.name, action,
                title=doc.title,
                details={"Status": doc.status, "Priority": doc.priority, "Due Date": str(doc.due_date or "")},
                modified_by=actor_user
            )
            dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)

        elif doctype in ["CRM Organization", "Contact"]:
            if not settings.other_records:
                return
            recipients = resolve_recipients(actor_user, settings)
            if not recipients:
                return

            action = "Created" if method == "after_insert" else "Updated"
            title = doc.organization_name if doctype == "CRM Organization" else f"{doc.first_name or ''} {doc.last_name or ''}".strip()
            subject = f"[AgroCRM Alert] {doctype} \"{title or doc.name}\" was {action}"
            content = format_entity_change_html(
                app_base_url, doctype, doc.name, action,
                title=title, modified_by=actor_user
            )
            dispatch_or_queue_notification(recipients, subject, content, doctype, doc.name)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Hierarchy notify on_change failed: {str(e)}")


def notify_entity(doctype, docname, action, details=None, crm_deal=None, actor_user=None):
    """
    Helper called for external events (e.g. ERPNext Quotation / Sales Order webhooks).
    """
    try:
        settings = get_notification_settings_doc()
        if not settings or not settings.enabled:
            return

        if doctype == "Quotation" and not settings.quotations:
            return
        if doctype == "Sales Order" and not settings.sales_orders:
            return

        # For external webhook events, actor is unknown on the CRM site.
        # If mode is Selected Nodes, recipients do not depend on actor.
        # Otherwise, resolve using the owner of the linked CRM Deal.
        effective_actor = actor_user
        if not effective_actor and crm_deal and frappe.db.exists("CRM Deal", crm_deal):
            effective_actor = frappe.db.get_value("CRM Deal", crm_deal, "owner")

        recipients = resolve_recipients(effective_actor, settings)
        if not recipients:
            return

        app_base_url = settings.app_base_url or "https://pipedrive-crm.usman-agro7c.workers.dev"
        subject = f"[AgroCRM Alert] {doctype} \"{docname}\" was {action}"
        content = format_entity_change_html(
            app_base_url, doctype, docname, action,
            title=docname, details=details, modified_by=effective_actor or "ERPNext Webhook"
        )

        dispatch_or_queue_notification(recipients, subject, content, doctype, docname)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"notify_entity failed for {doctype} {docname}: {str(e)}")


def _enqueue_mail(recipients, subject, content, reference_doctype, reference_name):
    """Safely enqueue an email dispatch."""
    if not recipients:
        return
    frappe.enqueue(
        frappe.sendmail,
        queue="short",
        enqueue_after_commit=True,
        recipients=recipients,
        subject=subject,
        message=content,
        reference_doctype=reference_doctype,
        reference_name=reference_name
    )
