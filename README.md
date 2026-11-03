# Custom CRM Sync

Custom Frappe app providing bi-directional cross-site synchronization between Frappe CRM (`crm_site.pk`) and ERPNext (`erp_site.pk`).

## Features
- **ERPNext Items $\rightarrow$ CRM Products**: Realtime webhook & bulk pull of items and pricing.
- **CRM Deals $\rightarrow$ ERPNext Customers**: Automated customer creation on deal Won.
- **ERPNext Quotations $\rightarrow$ CRM Deals**: Realtime quotation status tracking on deal timeline.
- **ERPNext Sales Orders $\rightarrow$ CRM Deals**: Order confirmation & revenue tracking on deal timeline.
- **Audit Log**: Complete event history and retry mechanism via `Custom CRM Sync Log`.
