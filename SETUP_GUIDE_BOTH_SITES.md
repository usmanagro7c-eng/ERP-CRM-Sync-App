# Complete Setup Guide: Frappe CRM & ERPNext Bi-Directional Sync

Yeh guide aap ko step-by-step batati hai ke agar aap ko kisi bhi nayi site (ya Production environment) par Frappe CRM aur ERPNext ko aapas mein sync karna ho, to dono sites par kya kya steps karne hain.

---

## Site Roles Summary

| Role | Domain / Site | Description |
|---|---|---|
| **ERP Site** | `https://erp_site.pk` (ya aap ka ERP) | Product Catalog, Customers, Quotations, Sales Orders, FBR Invoicing |
| **CRM Site** | `https://crm_site.pk` (ya aap ka CRM) | Pipedrive-like Pipeline, Leads, Deals, Organizations, Contacts |

---

# Hissa 1: ERPNext Site Setup (Zero-Touch - dev06)

ERPNext par koi custom code install karne ki zaroorat nahi hai. Sirf 3 steps karne hain:

### Step 1.1: API User & Keys Generate Karen
1. ERPNext Desk par **Administrator** se login karen.
2. Search bar (Ctrl+K) mein **User List** open karen aur naya user banayen (maslan: `crm-sync@agrovisions.pk` ya mojooda System Manager user).
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
> Yeh step zaroori hai taake CRM se customer auto-create hotay waqt koi mandatory field missing ka error na aaye.

---

### Step 1.3: Webhooks Configure Karen (3 Webhooks)
ERPNext Desk mein **Webhook List** open karen (URL: `/desk/webhook` ya `/app/webhook`). **Add Webhook** par click kar ke mandarja zail 3 webhooks banayen:

#### Webhook 1: Item Sync (ERP $\rightarrow$ CRM Products)
- **DocType:** `Item`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_item_webhook`
- **Request Method:** `POST`
- **Request Structure:** `JSON`
- **Webhook Headers:** Add Row $\rightarrow$ Key: `Content-Type`, Value: `application/json`
- **JSON Request Body (`webhook_json`):**
```json
{
  "item_code": "{{ doc.item_code }}",
  "item_name": "{{ doc.item_name }}",
  "standard_rate": {{ doc.standard_rate or 0 }},
  "disabled": {{ doc.disabled or 0 }}
}
```

#### Webhook 2: Quotation Sync (ERP $\rightarrow$ CRM Deal Timeline)
- **DocType:** `Quotation`
- **Doc Event:** `on_update`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_quotation_webhook`
- **Request Method:** `POST`
- **Request Structure:** `JSON`
- **Webhook Headers:** Add Row $\rightarrow$ Key: `Content-Type`, Value: `application/json`
- **JSON Request Body (`webhook_json`):**
```json
{
  "name": "{{ doc.name }}",
  "party_name": "{{ doc.party_name }}",
  "crm_deal": "{{ doc.crm_deal or '' }}",
  "grand_total": {{ doc.grand_total or 0 }},
  "docstatus": {{ doc.docstatus or 0 }},
  "status": "{{ doc.status }}"
}
```

#### Webhook 3: Sales Order Sync (ERP $\rightarrow$ CRM Deal Won & Timeline)
- **DocType:** `Sales Order`
- **Doc Event:** `on_submit`
- **Request URL:** `https://crm_site.pk/api/method/custom_crm_sync.api.sync.handle_sales_order_webhook`
- **Request Method:** `POST`
- **Request Structure:** `JSON`
- **Webhook Headers:** Add Row $\rightarrow$ Key: `Content-Type`, Value: `application/json`
- **JSON Request Body (`webhook_json`):**
```json
{
  "name": "{{ doc.name }}",
  "customer": "{{ doc.customer }}",
  "grand_total": {{ doc.grand_total or 0 }},
  "docstatus": {{ doc.docstatus or 0 }},
  "status": "{{ doc.status }}"
}
```

---

# Hissa 2: Frappe CRM Site Setup (dev03)

### Step 2.1: App Deploy & Install Karen
1. App ka source code aap ke folder mein mojood hai:
   `D:\Comapny Projects\Custom CRM Sync`
2. Is folder ko CRM server par copy karen:
   `/home/usman/frappe-bench/apps/custom_crm_sync`
3. CRM server ke terminal par yay commands run karen:
```bash
cd ~/frappe-bench

# Pip environment mein install karen
./env/bin/pip install -e apps/custom_crm_sync

# Site par install aur migrate karen
bench --site usman.local install-app custom_crm_sync
bench --site usman.local migrate

# Workers ko reload karen
pkill -HUP -f 'gunicorn -b 127.0.0.1:8000'
```

---

### Step 2.2: Standard `ERPNext CRM Settings` Configure Karen
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
   - **Bidirectional Product Sync:** **OFF** *(Isko OFF rakhna hai, kyunke alag VMs par core sync allow nahi karta)*
4. **Save** par click karen.

---

### Step 2.3: `Custom CRM Sync Settings` Configure Karen
1. Search bar mein **Custom CRM Sync Settings** kholen.
2. Fields bharein:
   - **Enabled:** Checked
   - **ERPNext Site URL:** `https://erp_site.pk`
   - **API Key:** Step 1.1 wali Key
   - **API Secret:** Step 1.1 wala Secret
   - **Sync Items from ERPNext:** Checked
   - **Sync Quotations:** Checked
   - **Sync Sales Orders:** Checked
   - **Auto Sync Catalog Items (Hourly):** Checked
3. **Save** karen.
4. Top-right par mojood **"Sync All Items Now"** button par click karen.
   - Message aayega: `Items successfully synced: X`
   - Tamam ERP items `dev03` ke **CRM Product** list mein foran aa jayengay.

---

# Hissa 3: Testing & Verification Checklist

Dono sites set hone ke baad workflow test karen:

### Checklist:
1. **Item Sync Test:**
   - ERPNext par naya item banayein.
   - CRM desk par **CRM Product** list refresh karen, naya item mojood hona chahiye.
2. **Deal to Customer Test:**
   - CRM mein naye customer ki Lead/Deal banayein.
   - Deal ko **"Won"** mark karen.
   - ERPNext ke Customer List mein check karen, usi naam ka Customer ban chuka hoga.
   - CRM Deal page par **"Create Quotation"** aur **"View Customer"** buttons active ho jayengay.
3. **Quotation Tracking Test:**
   - ERPNext par usi Customer ki Quotation save karen (Draft).
   - CRM Deal open karen $\rightarrow$ Activity tab par comment nazar aayega ke Quotation ban chuki hai with Total PKR amount.
4. **Sales Order Test:**
   - ERPNext par Sales Order bana kar Submit karen.
   - CRM Deal Activity par confirmation comment aayega aur Deal ka Annual Revenue update ho jayega.

---

# Hissa 4: Troubleshooting & Logs

| Masla | Kahan Check Karen | Hal |
|---|---|---|
| Deal Won karne par Customer nahi bana | `dev03`: Desk $\rightarrow$ **Error Log** | Check karen ERP user ke paas Customer create karne ki permission hai ya nahi, aur mandatory fields mein defaults mojood hain ya nahi. |
| ERP ka Item ya Order CRM mein nahi dikha | `dev06`: Desk $\rightarrow$ **Webhook Request Log** | Response code check karen. Agar 200 hai to sync kamyab hai. Agar 500 ya 401 ho to URL aur API token check karen. |
| Sync history aur audit trail dekhna | `dev03`: Desk $\rightarrow$ **Custom CRM Sync Log** | Har transaction (Item, Customer, Quotation, Sales Order) ka status, request payload aur error yahan record hota hai. |
