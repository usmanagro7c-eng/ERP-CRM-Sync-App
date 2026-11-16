# Complete Setup Guide: Frappe CRM & ERPNext Bi-Directional Sync

Yeh guide aap ko step-by-step batati hai ke agar aap ko kisi bhi nayi site (ya Production environment) par Frappe CRM aur ERPNext ko aapas mein sync karna ho, to dono sites par kya kya steps karne hain.

---

## Site Roles Summary

| Role | Target Sites (Example) | Description |
|---|---|---|
| **ERP Site** | `https://dev06.agrovisions.pk` (ya aap ka ERP) | Product Catalog (Items), Customers, Contacts, Quotations, Sales Orders, FBR Invoicing |
| **CRM Site** | `https://dev03.agrovisions.pk` (ya aap ka CRM) | Pipedrive-like Pipeline, Leads (`CRM Lead`), Deals (`CRM Deal`), Organizations (`CRM Organization`), Contacts (`Contact`) |

**Repository:** [https://github.com/usmanagro7c-eng/ERP-CRM-Sync-App.git](https://github.com/usmanagro7c-eng/ERP-CRM-Sync-App.git)

---

# Hissa 1: ERPNext Site Setup (Zero-Touch)

ERPNext par koi custom app install karne ki zaroorat nahi hai. Sirf mandarja zail 3 steps karne hain:

### Step 1.1: API User & Keys Generate Karen
1. ERPNext Desk par **Administrator** se login karen.
2. Search bar (`Ctrl+K`) mein **User List** open karen aur naya user banayen (maslan: `crm-sync@agrovisions.pk` ya mojooda System Manager user).
3. **Roles** assign karen:
   - `System Manager` (Recommended)
   - `Sales User` aur `Sales Manager`
4. User save karne ke baad neechay scroll karen: **API Access** section mein **Generate Keys** par click karen.
5. Pop-up mein jo **API Key** aur **API Secret** mile, unhe mehfooz save kar lein.  
   *(Secret sirf aik dafa dikhta hai).*

---

### Step 1.2: Customer Mandatory Fields Check / Default Set Karen (Agar FBR app ho)
Agar ERP par FBR Integration ya koi aisi app installed hai jo Customer par fields mandatory karti hai:
1. Search bar mein **Custom Field List** open karen.
2. Filter lagayen: `DocType = Customer`.
3. Check karen agar koi custom field mandatory (`reqd = 1`) hai:
   - **`Customer-custom_tax_payer_type`:** Open karen aur **Default Value** mein `Unregistered` likh kar Save karen.
   - **`Customer-custom_buyer_province`:** Open karen aur **Default Value** mein `PUNJAB` (ya apna province) likh kar Save karen.
> Yeh step zaroori hai taake CRM se deal Won hotay waqt ERP customer auto-create hone par mandatory field missing (417 Expectation Failed) ka error na aaye.

---

### Step 1.3: Webhooks Configure Karen (5 Webhooks)
ERPNext Desk mein **Webhook List** open karen (URL: `/desk/webhook` ya `/app/webhook`). **Add Webhook** par click kar ke mandarja zail 5 webhooks banayen.

Har webhook mein:
- **Request Method:** `POST`
- **Request Structure:** `JSON`
- **Enabled:** Checked (Tick)
- **Webhook Headers:** Add Row $\rightarrow$ Key: `Content-Type`, Value: `application/json`
- **JSON Request Body (`webhook_json`):** Neechay diya gaya exact JSON paste karen.

---

#### Webhook 1: Item Sync (ERP $\rightarrow$ CRM Products)
- **Webhook Name:** `CRM Sync - Item`
- **DocType:** `Item`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_item_webhook`
- **Request Structure:** `JSON`
- **JSON Request Body:**
```json
{
  "item_code": "{{ doc.item_code }}",
  "item_name": "{{ doc.item_name }}",
  "standard_rate": {{ doc.standard_rate or 0.0 }},
  "disabled": {{ doc.disabled or 0 }},
  "description": "{{ (doc.description or '') | replace('\"', '\\\"') | replace('\n', ' ') }}",
  "image": "{{ doc.image or '' }}"
}
```

---

#### Webhook 2: Customer Sync (ERP $\rightarrow$ CRM Organization)
- **Webhook Name:** `CRM Sync - Customer`
- **DocType:** `Customer`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_customer_webhook`
- **Request Structure:** `JSON`
- **JSON Request Body:**
```json
{
  "customer_name": "{{ doc.customer_name }}",
  "name": "{{ doc.name }}",
  "customer_type": "{{ doc.customer_type or 'Company' }}",
  "customer_group": "{{ doc.customer_group or 'All Customer Groups' }}",
  "territory": "{{ doc.territory or 'Pakistan' }}",
  "default_currency": "{{ doc.default_currency or 'PKR' }}",
  "website": "{{ doc.website or '' }}"
}
```

---

#### Webhook 3: Contact Sync (ERP $\rightarrow$ CRM Contact & CRM Lead)
- **Webhook Name:** `CRM Sync - Contact`
- **DocType:** `Contact`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_contact_webhook`
- **Request Structure:** `JSON`
- **JSON Request Body:**
```json
{
  "name": "{{ doc.name }}",
  "first_name": "{{ doc.first_name or '' }}",
  "last_name": "{{ doc.last_name or '' }}",
  "full_name": "{{ doc.full_name or '' }}",
  "email_id": "{{ doc.email_id or '' }}",
  "mobile_no": "{{ doc.mobile_no or '' }}",
  "phone": "{{ doc.phone or '' }}",
  "company_name": "{{ doc.company_name or '' }}"
}
```

---

#### Webhook 4: Quotation Sync (ERP $\rightarrow$ CRM Deal & Log)
- **Webhook Name:** `CRM Sync - Quotation`
- **DocType:** `Quotation`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_quotation_webhook`
- **Request Structure:** `JSON`
- **JSON Request Body:**
```json
{
  "name": "{{ doc.name }}",
  "party_name": "{{ doc.party_name }}",
  "quotation_to": "{{ doc.quotation_to or 'Customer' }}",
  "crm_deal": "{{ doc.crm_deal or '' }}",
  "grand_total": {{ doc.grand_total or 0.0 }},
  "docstatus": {{ doc.docstatus or 0 }},
  "status": "{{ doc.status or 'Draft' }}",
  "transaction_date": "{{ doc.transaction_date or '' }}"
}
```

---

#### Webhook 5: Sales Order Sync (ERP $\rightarrow$ CRM Deal Won & Log)
- **Webhook Name:** `CRM Sync - Sales Order`
- **DocType:** `Sales Order`
- **Doc Event:** `on_submit`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_sales_order_webhook`
- **Request Structure:** `JSON`
- **JSON Request Body:**
```json
{
  "name": "{{ doc.name }}",
  "customer": "{{ doc.customer }}",
  "grand_total": {{ doc.grand_total or 0.0 }},
  "docstatus": {{ doc.docstatus or 0 }},
  "status": "{{ doc.status or 'Draft' }}",
  "transaction_date": "{{ doc.transaction_date or '' }}"
}
```

> **Wazahat (Tip):**
> 1. Agar aap Webhook form mein **JSON Request Body** ko bilkul **khaali (empty)** chhor dein, to Frappe automatically document ka mukammal data (`doc.as_dict()`) send karta hai.
> 2. Hamari app ke tamam API endpoints dono tarha ke payloads (chahe custom JSON Request Body ho ya complete document) ko automatically parse aur accept karte hain. Lekin upar diye gaye specific JSON bodies use karna recommended hai taake traffic clean aur fast rahe.

---

# Hissa 2: Frappe CRM Site Setup

### Step 2.1: App Deploy & Install Karen
1. CRM server ke terminal par jaayein:
```bash
cd ~/frappe-bench

# Agar GitHub se clone karna ho:
bench get-app https://github.com/usmanagro7c-eng/ERP-CRM-Sync-App.git custom_crm_sync

# Ya agar local folder copy kiya ho:
./env/bin/pip install -e apps/custom_crm_sync

# Site par install aur migrate karen
bench --site usman.local install-app custom_crm_sync
bench --site usman.local migrate
bench --site usman.local clear-cache

# Gunicorn workers reload karen
pkill -HUP -f 'gunicorn.*8000'
```

---

### Step 2.2: Standard `ERPNext CRM Settings` Configure Karen
Yeh core Frappe CRM ka setting doc hai jo Deal Won hone par ERP mein Customer create karta hai:
1. CRM Desk (`/desk`) open karen.
2. Search bar mein **ERPNext CRM Settings** kholen.
3. Mandarja zail fields set karen:
   - **Enabled:** Checked (Tick)
   - **Company in ERPNext site:** `AGROVISIONS` *(Apni ERP wali company ka exact naam)*
   - **Is ERPNext installed on a different site?:** Checked (Tick)
   - **ERPNext Site URL:** `https://erp_site.pk` *(Baghir aakhri `/` ke)*
   - **API Key:** Step 1.1 wali API Key
   - **API Secret:** Step 1.1 wala API Secret
   - **Create customer on status change:** Checked (Tick)
   - **Deal Status for Customer Creation:** `Won`
   - **Bidirectional Product Sync:** **OFF** *(Isko OFF rakhna hai)*
4. **Save** par click karen.

---

### Step 2.3: `Custom CRM Sync Settings` Configure Karen
Yeh custom sync app ka main control panel hai:
1. Search bar mein **Custom CRM Sync Settings** kholen (`/desk/custom-crm-sync/custom-crm-sync-settings/Custom CRM Sync Settings`).
2. Fields bharein:
   - **Enabled:** Checked
   - **ERPNext Site URL:** `https://erp_site.pk`
   - **API Key:** Step 1.1 wali Key
   - **API Secret:** Step 1.1 wala Secret
   - **Sync Rules:**
     - `Auto Sync Customers & Organizations`: Checked
     - `Auto Sync Contacts`: Checked
     - `Auto Sync Items to CRM Products`: Checked
     - `Auto Sync Quotations to Deals`: Checked
     - `Auto Sync Sales Orders to Deals`: Checked
3. **Save** karen.

#### Manual Sync Buttons (Top Bar):
Settings page ke top toolbar par mandarja zail 5 buttons dastiyab hain jin se aap kisi bhi waqt live data pull kar sakte hain:
- **`Sync All Items Now`**: ERPNext ke tamam items ko `CRM Product` mein sync karta hai.
- **`Sync All Customers Now`**: ERPNext ke tamam customers ko `CRM Organization` mein sync karta hai.
- **`Sync All Contacts Now`**: ERPNext ke tamam contacts ko `Contact` aur `CRM Lead` mein sync karta hai.
- **`Sync All Quotations Now`**: ERPNext ki quotations ko CRM Deals ke saath sync karta hai aur logs banata hai.
- **`Sync All Sales Orders Now`**: ERPNext ke sales orders ko CRM Deals ke saath sync karta hai aur logs banata hai.

#### Status Timestamps:
Settings page par automatically last sync time record hota hai:
- `Last Item Sync Time`
- `Last Customer Sync Time`
- `Last Contact Sync Time`
- `Last Quotation Sync Time`
- `Last Sales Order Sync Time`

---

# Hissa 3: Testing & Verification Checklist

Dono sites set hone ke baad workflow test karen:

### Checklist:
1. **Item Sync Test:**
   - ERPNext par naya item banayein ya "Sync All Items Now" click karen.
   - CRM Desk par **CRM Product** list refresh karen, items show honge.
2. **Customer & Organization Sync Test (Bi-Directional):**
   - **CRM $\rightarrow$ ERP:** CRM mein nayi Deal banayein aur status **"Won"** karen $\rightarrow$ ERPNext par Customer foran create ho jayega.
   - **ERP $\rightarrow$ CRM:** ERPNext par naya Customer banayein $\rightarrow$ Webhook ke zariye CRM mein **CRM Organization** create ho jayegi.
3. **Contact Sync Test:**
   - ERPNext par naya Contact add karen (e.g. linked to Customer).
   - CRM desk par **Contact** list aur **CRM Lead** list refresh karen, contact automatically synced milega.
4. **Quotation Tracking Test:**
   - ERPNext par Customer ki Quotation save karen (Draft ya Submitted).
   - CRM Deal open karen $\rightarrow$ Activity tab par comment nazar aayega with Quotation ID and Grand Total.
   - Custom CRM Sync Log mein **Quotation Sync** ka record `Success` ke saath banega.
5. **Sales Order Test:**
   - ERPNext par Sales Order bana kar Submit karen.
   - CRM Deal Activity par confirmation comment aayega, Deal **Won** mark hogi, aur Annual Revenue update ho jayega.
   - Custom CRM Sync Log mein **Sales Order Sync** ka record `Success` ke saath banega.

---

# Hissa 4: Custom CRM Sync Log & Troubleshooting

CRM Desk par **Custom CRM Sync Log** (`/desk/custom-crm-sync/custom-crm-sync-log`) kholen.

### Supported Event Types:
Aap list view mein filter kar sakte hain:
- `Item Sync`
- `Customer Sync`
- `Contact Sync`
- `Quotation Sync`
- `Sales Order Sync`

### Status Filters:
- `Success`
- `Error`

Har log entry ko click karke aap:
- Full **Payload (JSON)** dekh sakte hain.
- Agar koi error aaye to **Error Message** aur Python ka mukammal **Traceback** foran check kar sakte hain.

### Troubleshooting Matrix:

| Masla | Kahan Check Karen | Hal |
|---|---|---|
| Deal Won karne par Customer nahi bana | `dev03`: Desk $\rightarrow$ **Error Log** | Check karen ERP user ke paas Customer create karne ki permission hai ya nahi, aur mandatory fields (`custom_tax_payer_type`, `custom_buyer_province`) mein defaults set hain ya nahi. |
| ERP ka Item / Customer / Order CRM mein nahi dikha | `dev06`: Desk $\rightarrow$ **Webhook Request Log** | Response code check karen. Agar 200 hai to webhook kamyab hai. Agar 500 ya 401/417 ho to request URL aur API credentials check karen. |
| Contact CRM Lead mein show nahi ho raha | `dev03`: Desk $\rightarrow$ **Custom CRM Sync Log** | Filter lagayen `Event Type = Contact Sync`. Check karen status `Success` hai ya nahi. |
| Quotation ya Sales Order ka deal link nahi mila | `dev03`: Desk $\rightarrow$ **Custom CRM Sync Log** | Check karen Customer ka naam CRM Deal ki `organization` ya `erpnext_customer` field se match karta hai ya nahi. |
