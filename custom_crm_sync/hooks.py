app_name = "custom_crm_sync"
app_title = "Custom CRM Sync"
app_publisher = "Agrovisions"
app_description = "Bi-directional Cross-Site Sync between Frappe CRM and ERPNext"
app_email = "usman.agro7c@gmail.com"
app_license = "mit"

# Includes in <head>
# ------------------

# include js in doctype views
doctype_js = {
    "CRM Deal": "public/js/crm_deal.js"
}

# Document Events
# ---------------
doc_events = {
    "CRM Deal": {
        "after_insert": "custom_crm_sync.api.notify.on_change",
        "on_update": "custom_crm_sync.api.notify.on_change"
    },
    "CRM Lead": {
        "after_insert": "custom_crm_sync.api.notify.on_change",
        "on_update": "custom_crm_sync.api.notify.on_change"
    },
    "CRM Task": {
        "after_insert": "custom_crm_sync.api.notify.on_change",
        "on_update": "custom_crm_sync.api.notify.on_change"
    },
    "CRM Organization": {
        "after_insert": "custom_crm_sync.api.notify.on_change",
        "on_update": "custom_crm_sync.api.notify.on_change"
    },
    "Contact": {
        "after_insert": "custom_crm_sync.api.notify.on_change",
        "on_update": "custom_crm_sync.api.notify.on_change"
    }
}

# Scheduled Tasks
# ---------------
scheduler_events = {
    "hourly": [
        "custom_crm_sync.api.sync.sync_recent_items",
        "custom_crm_sync.api.sync.sync_recent_customers",
        "custom_crm_sync.api.sync.sync_recent_contacts",
        "custom_crm_sync.api.sync.sync_recent_quotations",
        "custom_crm_sync.api.sync.sync_recent_sales_orders"
    ]
}
