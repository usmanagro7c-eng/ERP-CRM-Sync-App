# Frappe CRM (dev03) & ERPNext (dev06) Bi-Directional Sync Integration Report

**Tareekh:** 03 November 2026  
**Status:** 100% Implemented & Verified Live  
**Target Systems:**
- **CRM Site:** `https://crm_site.pk` (Frappe 16.54.0, Frappe CRM 2.0.0-dev)
- **ERPNext Site:** `https://erp_site.pk` (Frappe 16.36.0, ERPNext 16.36.1, FBR Integration 1.0.0)

---

## 1. Executive Summary & Maqsad

Aap ka maqsad **Pipedrive.com** ki tarah Frappe CRM (`dev03`) ko use karna tha, taake sales team CRM ke andar Deals, Leads, aur Products manage kare, aur CRM ka data ERPNext (`dev06`) ke sath seamless sync rahe:
1. **Products / Items Sync:** `dev06` ERP ka Item Catalog real-time `dev03` CRM Products mein sync ho.
2. **Customer Creation:** `dev03` CRM mein Deal "Won" hotay hi `dev06` ERP mein Customer ban jaye.
3. **Quotation Tracking:** `dev06` par Quotation banne ya update hone par `dev03` CRM Deal ke Activity timeline par status aur amount update ho.
4. **Sales Order Tracking:** `dev06` par Sales Order submit hotay hi CRM Deal par order ki confirmation PKR total ke sath log ho aur Deal ka status confirmed "Won" rahe.

---

## 2. Solution Architecture

```
┌─────────────────────────────────┐         REST / Webhooks          ┌──────────────────────────────────┐
│      Frappe CRM (dev03)         │ ◄──────────────────────────────► │       ERPNext (dev06)            │
│       192.168.90.CRM            │                                  │        192.168.90.ERP            │
├─────────────────────────────────┤                                  ├──────────────────────────────────┤
│ • Custom App: custom_crm_sync   │                                  │ • Zero-Touch Architecture        │
│ • Custom CRM Sync Settings      │  ─── REST API (Auth Token) ───►  │   (No custom app on dev06)       │
│ • Custom CRM Sync Log           │                                  │                                  │
│ • Webhook Receivers:            │  ◄── Standard Frappe Webhooks ── │ • Webhook: Item (on_update)      │
│   - handle_item_webhook         │                                  │ • Webhook: Quotation (on_update) │
│   - handle_quotation_webhook    │                                  │ • Webhook: Sales Order (submit)  │
│   - handle_sales_order_webhook  │                                  │                                  │
└─────────────────────────────────┘                                  └──────────────────────────────────┘
```

### Decoupled "Zero-Touch" Design
- **`dev06` par koi custom app install karne ki zaroorat nahi pari.** Is se `dev06` ka core ERP clean aur safe rehta hai aur updates ke doran koi issue nahi aata.
- `dev06` par Frappe ka standard built-in **`Webhook`** DocType configure kiya gaya hai, jo event trigger hotay hi `dev03` ko secure JSON payload dispatch karta hai.
- `dev03` par custom app **`custom_crm_sync`** install ki gayi hai jo saara logic, retry handling, aur audit logging manage karti hai.

---

## 3. Masail aur Unke Permanent Solutions

| # | Masla | Wajah | Permanent Solution |
|---|---|---|---|
| 1 | `create_custom_fields_for_frappe_crm` AttributeError | ERPNext v16 mein yeh method deprecate ho chuka hai | `erpnext_crm_settings.py` mein defensive check lagaya gaya ke agar fields pehle se mojood hain to remote call skip kar de. |
| 2 | Customer creation fail on `dev06` (`MandatoryError: custom_tax_payer_type, custom_buyer_province`) | `dev06` par FBR Integration app ne Customer DocType par dono fields mandatory kiye huay thay | Dono custom fields par standard default values set kar di gayin (`Unregistered` aur `PUNJAB`), jis se auto customer creation smooth ho gayi. |
| 3 | Product sync error (`Unknown column item_code`) | Frappe CRM 2.0 mein `CRM Product` ke fields `product_code` aur `erpnext_item_code` hain | `sync.py` mein fields ki proper mapping ki gayi (`erpnext_item_code`, `product_name`, `standard_rate`, `description`, `disabled`). |
| 4 | Webhook payload format parsing | Frappe Webhooks POST request raw data body mein send karta hai | `parse_request_data()` helper banaya jo raw JSON body, multipart, aur form-dict teeno ko automatically detect kar ke reliably parse karta hai. |

---

## 4. Live End-to-End Test Results

### Test 1: Real-time Item Sync (ERPNext $\rightarrow$ CRM)
- **Action:** `dev06` par naya Item banaya gaya:
  - **Item Code:** `SYNC-TEST-1793703696`
  - **Item Name:** `Agro Auto Sprayer 1793703696`
  - **Rate:** PKR 85,000.00
- **Result:** `dev06` ke Webhook ne event fire kiya. `dev03` ke `CRM Product` mein yay item instant sync ho gaya.
- **Log ID:** `SYNC-LOG-2026-01673` (Status: Success).

### Test 2: Deal "Won" $\rightarrow$ Customer Creation (CRM $\rightarrow$ ERPNext)
- **Action:** `dev03` CRM mein Deal banai gayi:
  - **Deal ID:** `CRM-DEAL-2026-00003`
  - **Organization:** `Pak Agri Traders 1793703963`
  - **Contact:** `Tariq Mahmood`
  - Deal ka status `Qualification` se badal kar **`Won`** kiya gaya.
- **Result:** `dev06` ERPNext ke andar automatically Customer ban gaya:
  - **Customer Name:** `Pak Agri Traders 1793703963`
  - **Billing Currency:** PKR
  - **Customer Type:** Company
- **Log ID:** `SYNC-LOG-2026-01674` (Status: Success).

### Test 3: Quotation Tracking Sync (ERPNext $\rightarrow$ CRM)
- **Action:** `dev06` par Customer `Pak Agri Traders 1793703963` ke liye Quotation `SAL-QTN-2026-00001` create ki gayi (Total: PKR 85,000.00).
- **Result:** `dev06` Webhook ne `dev03` ko notify kiya. Deal `CRM-DEAL-2026-00003` ke Activity Timeline par comment darj ho gaya:
  > *"ERPNext Quotation SAL-QTN-2026-00001 (Draft) updated: Grand Total PKR 85,000.00"*
- **Log ID:** `SYNC-LOG-2026-01675` (Status: Success).

### Test 4: Sales Order Placement & Submission (ERPNext $\rightarrow$ CRM)
- **Action:** `dev06` par Customer ke liye Sales Order `SAL-ORD-2026-00001` banaya aur Submit kiya gaya (DocStatus: 1).
- **Result:** `dev06` Webhook ne notification bheja. `dev03` Deal timeline par confirmation comment automatically add ho gaya:
  > *"Sales Order SAL-ORD-2026-00001 (Submitted) placed on ERPNext for PKR 85,000.00"*
- **Deal Final Status:** Confirmed "Won" with Annual Revenue PKR 85,000.00.
- **Log ID:** `SYNC-LOG-2026-01676` (Status: Success).

---

## 5. App Structure & Files Overview

App ka mukammal source code aap ke project folder mein mojud hai:
`D:\Comapny Projects\Custom CRM Sync\`

```
D:\Comapny Projects\Custom CRM Sync\
├── pyproject.toml                         # App metadata & dependencies
├── README.md                              # Technical guide
├── custom_crm_sync\
│   ├── __init__.py
│   ├── hooks.py                           # Hooks, cron schedules & triggers
│   ├── modules.txt
│   ├── api\
│   │   ├── __init__.py
│   │   └── sync.py                        # Sync logic, REST endpoints & Webhook handlers
│   └── custom_crm_sync\
│       ├── doctype\
│       │   ├── custom_crm_sync_settings\  # Configuration DocType (API Keys, URLs)
│       │   │   ├── custom_crm_sync_settings.json
│       │   │   ├── custom_crm_sync_settings.py
│       │   │   └── custom_crm_sync_settings.js
│       │   └── custom_crm_sync_log\       # Audit Trail & Error Log DocType
│       │       ├── custom_crm_sync_log.json
│       │       └── custom_crm_sync_log.py
```

---

## 6. How to Use & Day-to-Day Operations

### Manual Bulk Item Sync (Kisis bhi waqt chalane ke liye):
1. `https://crm_site.pk/desk` open karen.
2. Search bar (Ctrl+K) mein **"Custom CRM Sync Settings"** likhein.
3. Top right par **"Sync All Items Now"** button click karen. Tamam items `dev06` se khinch kar `dev03` CRM Products mein aa jayengay.

### Sync Logs Check Karna:
1. Search bar mein **"Custom CRM Sync Log"** search karen.
2. Tamam events (Customer Sync, Item Sync, Quotation Sync, Sales Order Sync) ka live status, payload aur timestamp yahan visual nazar aata hai.

### Daily Routine (Pipedrive Workflow):
1. **Sales Rep** `dev03` CRM par Lead / Deal banata hai aur items add karta hai.
2. Jab deal finalize ho to status **Won** select karen.
3. `dev06` ERP par Customer khud ba khud ban jayega.
4. Accounts / Sales team `dev06` par usi Customer ke liye Quotation ya Sales Order banati hai.
5. Deal page par jaakar CRM rep live dekh sakta hai ke Quotation ban chuki hai aur order place ho chuka hai baghair ERP open kiye.
