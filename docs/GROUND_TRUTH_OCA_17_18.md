# Vérité terrain OCA 17.0 → 18.0

Lignes identiques à la version migrée à la main par l'OCA (README, i18n,
static/description ignorés ; lignes vides et espaces de fin ignorés).

| Dépôt | Module | Avant | Après | Gain | Lignes |
|---|---|---:|---:|---:|---:|
| sale-workflow | partner_sale_pivot | 88.7% | 90.3% | +1.6% | 62 |
| sale-workflow | portal_sale_personal_data_only | 97.1% | 97.8% | +0.7% | 136 |
| sale-workflow | product_form_sale_link | 69.8% | 69.8% | +0.0% | 199 |
| sale-workflow | sale_advance_payment | 77.1% | 76.9% | -0.2% | 1073 |
| sale-workflow | sale_attached_product | 99.6% | 99.8% | +0.2% | 451 |
| sale-workflow | sale_automatic_workflow | 75.2% | 75.5% | +0.3% | 1610 |
| sale-workflow | sale_automatic_workflow_stock | 89.9% | 89.9% | +0.0% | 547 |
| sale-workflow | sale_block_no_stock | 97.7% | 97.7% | +0.0% | 858 |
| purchase-workflow | procurement_purchase_no_grouping | 98.5% | 98.5% | +0.0% | 413 |
| purchase-workflow | procurement_purchase_sale_no_grouping | 99.0% | 100.0% | +1.0% | 105 |
| purchase-workflow | product_supplier_code_purchase | 98.8% | 99.4% | +0.6% | 170 |
| purchase-workflow | product_supplierinfo_disable_autocreation | 98.8% | 99.2% | +0.4% | 251 |
| purchase-workflow | purchase_advance_payment | 89.9% | 89.8% | -0.1% | 1474 |
| purchase-workflow | purchase_all_shipments | 68.9% | 68.9% | +0.0% | 183 |
| purchase-workflow | purchase_allowed_product | 87.1% | 87.8% | +0.7% | 287 |
| purchase-workflow | purchase_blanket_order | 95.6% | 96.7% | +1.1% | 2302 |
| stock-logistics-workflow | delivery_procurement_group_carrier | 22.6% | 22.6% | +0.0% | 332 |
| stock-logistics-workflow | product_cost_price_avco_sync | 31.9% | 31.9% | +0.0% | 1979 |
| stock-logistics-workflow | purchase_stock_picking_invoice_link | 99.0% | 99.0% | +0.0% | 313 |
| stock-logistics-workflow | sale_order_global_stock_route | 89.4% | 89.9% | +0.5% | 189 |
| stock-logistics-workflow | sale_stock_restocking_fee_invoicing | 91.1% | 91.4% | +0.3% | 606 |
| stock-logistics-workflow | stock_account_product_run_fifo_hook | 84.6% | 84.6% | +0.0% | 415 |
| stock-logistics-workflow | stock_account_show_automatic_valuation | 63.3% | 65.0% | +1.7% | 60 |
| stock-logistics-workflow | stock_landed_costs_priority | 92.3% | 93.2% | +0.9% | 117 |
| partner-contact | account_partner_company_group | 96.6% | 96.6% | +0.0% | 58 |
| partner-contact | animal | 72.0% | 73.7% | +1.7% | 581 |
| partner-contact | base_country_state_translatable | 95.2% | 100.0% | +4.8% | 21 |
| partner-contact | base_location | 96.0% | 96.7% | +0.8% | 793 |
| partner-contact | base_location_geonames_import | 97.0% | 97.2% | +0.2% | 541 |
| partner-contact | base_location_nuts | 88.6% | 89.2% | +0.6% | 878 |
| partner-contact | base_partner_company_group | 94.9% | 95.8% | +0.8% | 118 |
| partner-contact | base_partner_sequence | 80.0% | 80.0% | +0.0% | 190 |
| account-invoicing | account_global_discount | 88.0% | 88.4% | +0.4% | 1177 |
| account-invoicing | account_invoice_auto_send_by_email | 80.1% | 80.1% | +0.0% | 206 |
| account-invoicing | account_invoice_crm_tag | 96.8% | 97.6% | +0.8% | 126 |
| account-invoicing | account_invoice_currency_by_partner | 98.7% | 99.3% | +0.7% | 152 |
| account-invoicing | account_invoice_date_due | 93.7% | 93.7% | +0.0% | 287 |
| account-invoicing | account_invoice_discount_display_amount | 91.9% | 92.2% | +0.2% | 434 |
| account-invoicing | account_invoice_fixed_discount | 80.6% | 81.1% | +0.5% | 371 |
| account-invoicing | account_invoice_pricelist | 36.0% | 36.0% | +0.0% | 694 |
| server-ux | announcement | 94.6% | 95.8% | +1.2% | 1116 |
| server-ux | barcode_action | 93.6% | 94.1% | +0.5% | 203 |
| server-ux | base_cancel_confirm | 83.3% | 83.3% | +0.0% | 324 |
| server-ux | base_export_manager | 90.6% | 92.0% | +1.4% | 650 |
| server-ux | base_import_security_group | 94.6% | 95.0% | +0.4% | 241 |
| server-ux | base_menu_visibility_restriction | 98.8% | 100.0% | +1.2% | 80 |
| server-ux | base_optional_quick_create | 87.7% | 87.7% | +0.0% | 179 |
| server-ux | base_revision | 90.6% | 90.9% | +0.4% | 254 |
| web | web_action_conditionable | 91.1% | 92.9% | +1.8% | 56 |
| web | web_calendar_slot_duration | 95.5% | 97.0% | +1.5% | 67 |
| web | web_chatter_position | 42.9% | 42.9% | +0.0% | 319 |
| web | web_company_color | 80.6% | 80.6% | +0.0% | 634 |
| web | web_dialog_size | 93.8% | 93.8% | +0.0% | 193 |
| web | web_editor_class_selector | 25.6% | 26.6% | +1.0% | 508 |
| web | web_environment_ribbon | 82.6% | 82.6% | +0.0% | 161 |
| web | web_favicon | 86.1% | 86.1% | +0.0% | 237 |
| l10n-france | account_statement_import_fr_cfonb | 76.7% | 77.0% | +0.3% | 317 |
| l10n-france | l10n_fr_account_invoice_facturx | 97.1% | 100.0% | +2.9% | 34 |
| l10n-france | l10n_fr_account_tax_unece | 97.9% | 98.9% | +1.1% | 95 |
| l10n-france | l10n_fr_chorus_account | 81.1% | 81.4% | +0.3% | 2924 |
| l10n-france | l10n_fr_chorus_facturx | 96.2% | 97.1% | +1.0% | 104 |
| l10n-france | l10n_fr_chorus_sale | 89.0% | 88.0% | -1.0% | 100 |
| l10n-france | l10n_fr_cog | 3.8% | 3.8% | +0.1% | 1536 |
| l10n-france | l10n_fr_das2 | 79.3% | 79.3% | +0.0% | 1489 |
| **moyenne** | 64 modules | 83.5% | 84.1% | +0.5% | |

## Lignes modifiées par l'OCA mais pas par le migrator (les plus fréquentes)

Pistes de règles manquantes, à prouver dans les sources d'Odoo avant d'en faire des règles.

| Occurrences | Ligne |
|---:|---|
| 14 | `}` |
| 10 | `<field` |
| 9 | `/** @odoo-module **/` |
| 8 | `>` |
| 8 | `_(` |
| 8 | `% {` |
| 7 | `</div>` |
| 6 | `)` |
| 6 | `</field>` |
| 6 | `from odoo.tests.common import TransactionCase` |
| 6 | `</record>` |
| 5 | `from odoo import _, api, fields, models` |
| 5 | `(` |
| 4 | `</button>` |
| 4 | `/>` |
| 4 | `</group>` |
| 3 | `"""` |
| 3 | `"type": "product",` |
| 3 | `def setUpClass(cls):` |
| 3 | `super().setUpClass()` |
| 3 | `@classmethod` |
| 3 | `[` |
| 3 | `<filter` |
| 3 | `<field name="arch" type="xml">` |
| 3 | `<separator />` |
| 3 | `<sheet>` |
| 3 | `<field name="name" />` |
| 3 | `</sheet>` |
| 3 | `]` |
| 3 | `0,` |
| 3 | `type="object"` |
| 3 | `<button` |
| 3 | `"partner": cpartner.display_name,` |
| 3 | `"obj_display_name": obj_display_name,` |
| 2 | `<field name="sale_lines_count" widget="statinfo" />` |
| 2 | `<field name="available_payment_method_line_ids" invisible="1" />` |
| 2 | `pay.available_payment_method_line_ids = (` |
| 2 | `_job_force_sync=True,` |
| 2 | `workflow_domain = [("workflow_process_id", "=", sale_workflow.id)]` |
| 2 | `can_write="true"` |
