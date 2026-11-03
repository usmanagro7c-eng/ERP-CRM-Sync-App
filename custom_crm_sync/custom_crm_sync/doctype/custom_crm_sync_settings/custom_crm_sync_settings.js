frappe.ui.form.on("Custom CRM Sync Settings", {
    refresh: function(frm) {
        frm.add_custom_button(__("Sync All Items Now"), function() {
            frappe.show_alert({
                message: __("Starting full item sync from ERPNext..."),
                indicator: "blue"
            });
            frappe.call({
                method: "custom_crm_sync.api.sync.pull_all_items",
                freeze: true,
                freeze_message: __("Pulling Items from ERPNext..."),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __("Sync Complete"),
                            message: __("Synced {0} items successfully.", [r.message.synced_count || 0]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        });
    }
});
