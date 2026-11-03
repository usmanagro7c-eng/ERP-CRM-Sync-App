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

# Scheduled Tasks
# ---------------
scheduler_events = {
    "hourly": [
        "custom_crm_sync.api.sync.sync_recent_items"
    ]
}
