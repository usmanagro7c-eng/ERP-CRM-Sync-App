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

        frm.add_custom_button(__("Sync All Customers Now"), function() {
            frappe.show_alert({
                message: __("Starting full customer sync from ERPNext..."),
                indicator: "blue"
            });
            frappe.call({
                method: "custom_crm_sync.api.sync.pull_all_customers",
                freeze: true,
                freeze_message: __("Pulling Customers from ERPNext..."),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __("Customer Sync Complete"),
                            message: __("Synced {0} customers to CRM Organizations.", [r.message.synced_count || 0]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        });

        frm.add_custom_button(__("Sync All Contacts Now"), function() {
            frappe.show_alert({
                message: __("Starting full contact sync from ERPNext..."),
                indicator: "blue"
            });
            frappe.call({
                method: "custom_crm_sync.api.sync.pull_all_contacts",
                freeze: true,
                freeze_message: __("Pulling Contacts from ERPNext..."),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __("Contact Sync Complete"),
                            message: __("Synced {0} contacts to CRM Contacts & Leads.", [r.message.synced_count || 0]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        });

        frm.add_custom_button(__("Sync All Quotations Now"), function() {
            frappe.show_alert({
                message: __("Starting full quotation sync from ERPNext..."),
                indicator: "blue"
            });
            frappe.call({
                method: "custom_crm_sync.api.sync.pull_all_quotations",
                freeze: true,
                freeze_message: __("Pulling Quotations from ERPNext..."),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __("Quotation Sync Complete"),
                            message: __("Synced {0} quotations.", [r.message.synced_count || 0]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        });

        frm.add_custom_button(__("Sync All Sales Orders Now"), function() {
            frappe.show_alert({
                message: __("Starting full sales order sync from ERPNext..."),
                indicator: "blue"
            });
            frappe.call({
                method: "custom_crm_sync.api.sync.pull_all_sales_orders",
                freeze: true,
                freeze_message: __("Pulling Sales Orders from ERPNext..."),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __("Sales Order Sync Complete"),
                            message: __("Synced {0} sales orders.", [r.message.synced_count || 0]),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        });
    }
});
