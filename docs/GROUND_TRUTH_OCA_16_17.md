# Vérité terrain OCA 16.0 → 17.0

Date : 2026-10-06. 8 dépôts OCA × 8 modules (sale-workflow, purchase-workflow,
stock-logistics-workflow, partner-contact, account-invoicing, server-ux, web, l10n-france),
comparés ligne à ligne à la version 17.0 migrée à la main par l'OCA (tools/ground_truth.py ;
README, i18n, static/description ignorés).

- **Avant** : module 16.0 non migré ;
- **Référence** : branche improve-migrator (avant ce travail) ;
- **Branche** : enrich-rules-8-16.

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | partner_contact_sale_info_propagation | 39.4% | 40.0% | 40.0% |
| sale-workflow | partner_sale_pivot | 98.4% | 100.0% | 100.0% |
| sale-workflow | portal_sale_personal_data_only | 94.2% | 95.0% | 98.5% |
| sale-workflow | product_form_sale_link | 95.3% | 77.9% | 96.0% |
| sale-workflow | product_supplierinfo_for_customer_sale | 84.2% | 84.2% | 84.2% |
| sale-workflow | sale_advance_payment | 70.6% | 66.0% | 70.6% |
| sale-workflow | sale_attached_product | 98.4% | 98.7% | 98.7% |
| sale-workflow | sale_auto_remove_zero_quantity_lines | 82.1% | 82.7% | 82.7% |
| purchase-workflow | procurement_purchase_no_grouping | 96.1% | 96.4% | 96.4% |
| purchase-workflow | product_supplier_code_purchase | 97.6% | 98.2% | 98.2% |
| purchase-workflow | product_supplierinfo_disable_autocreation | 94.2% | 94.2% | 94.2% |
| purchase-workflow | purchase_advance_payment | 79.4% | 75.4% | 79.4% |
| purchase-workflow | purchase_all_shipments | 83.7% | 70.6% | 85.0% |
| purchase-workflow | purchase_allowed_product | 88.6% | 85.2% | 88.9% |
| purchase-workflow | purchase_blanket_order | 96.7% | 83.7% | 97.1% |
| purchase-workflow | purchase_cancel_reason | 97.3% | 92.3% | 98.5% |
| stock-logistics-workflow | delivery_procurement_group_carrier | 23.9% | 23.9% | 23.9% |
| stock-logistics-workflow | product_cost_price_avco_sync | 98.2% | 98.3% | 98.3% |
| stock-logistics-workflow | purchase_stock_picking_invoice_link | 88.1% | 88.4% | 88.4% |
| stock-logistics-workflow | sale_order_global_stock_route | 95.5% | 96.0% | 96.0% |
| stock-logistics-workflow | sale_stock_restocking_fee_invoicing | 96.4% | 92.7% | 96.9% |
| stock-logistics-workflow | stock_account_product_run_fifo_hook | 86.5% | 86.3% | 86.3% |
| stock-logistics-workflow | stock_auto_move | 95.3% | 95.4% | 95.4% |
| stock-logistics-workflow | stock_landed_costs_priority | 99.1% | 100.0% | 100.0% |
| partner-contact | account_partner_company_group | 94.7% | 96.5% | 96.5% |
| partner-contact | animal | 99.3% | 77.2% | 99.5% |
| partner-contact | base_country_state_translatable | 95.2% | 100.0% | 100.0% |
| partner-contact | base_location | 94.6% | 91.5% | 94.7% |
| partner-contact | base_location_geonames_import | 93.3% | 93.3% | 93.3% |
| partner-contact | base_location_nuts | 98.7% | 98.7% | 98.7% |
| partner-contact | base_partner_company_group | 77.8% | 65.8% | 79.5% |
| partner-contact | base_partner_sequence | 62.7% | 63.1% | 63.1% |
| account-invoicing | account_global_discount | 91.7% | 83.5% | 92.0% |
| account-invoicing | account_invoice_block_payment | 87.6% | 80.9% | 88.8% |
| account-invoicing | account_invoice_blocking | 97.5% | 97.5% | 97.5% |
| account-invoicing | account_invoice_crm_tag | 98.4% | 90.5% | 99.2% |
| account-invoicing | account_invoice_customer_no_autofollow | 92.4% | 92.7% | 92.7% |
| account-invoicing | account_invoice_date_due | 95.1% | 89.5% | 96.1% |
| account-invoicing | account_invoice_discount_display_amount | 99.8% | 100.0% | 100.0% |
| account-invoicing | account_invoice_fixed_discount | 91.6% | 91.6% | 91.6% |
| server-ux | announcement | 86.7% | 78.2% | 86.8% |
| server-ux | barcode_action | 89.3% | 78.5% | 90.2% |
| server-ux | base_cancel_confirm | 95.4% | 91.4% | 96.7% |
| server-ux | base_export_manager | 96.6% | 90.6% | 96.1% |
| server-ux | base_import_security_group | 56.3% | 56.6% | 56.6% |
| server-ux | base_menu_visibility_restriction | 80.4% | 81.4% | 81.4% |
| server-ux | base_optional_quick_create | 71.7% | 72.3% | 72.3% |
| server-ux | base_revision | 98.8% | 98.0% | 98.0% |
| web | web_action_conditionable | 79.6% | 83.3% | 83.3% |
| web | web_calendar_slot_duration | 54.9% | 58.8% | 58.8% |
| web | web_chatter_position | 18.2% | 19.3% | 19.3% |
| web | web_company_color | 78.6% | 79.6% | 80.4% |
| web | web_dialog_size | 34.5% | 34.8% | 34.8% |
| web | web_editor_class_selector | 83.2% | 83.8% | 83.8% |
| web | web_environment_ribbon | 42.7% | 42.7% | 42.7% |
| web | web_field_tooltip | 58.2% | 51.7% | 58.7% |
| l10n-france | account_banking_fr_lcr | 90.9% | 90.9% | 91.7% |
| l10n-france | account_statement_import_fr_cfonb | 97.2% | 97.6% | 97.6% |
| l10n-france | l10n_fr_account_invoice_facturx | 97.1% | 100.0% | 100.0% |
| l10n-france | l10n_fr_account_tax_unece | 9.2% | 9.4% | 9.7% |
| l10n-france | l10n_fr_chorus_account | 83.2% | 77.1% | 83.5% |
| l10n-france | l10n_fr_chorus_facturx | 53.5% | 53.5% | 53.5% |
| l10n-france | l10n_fr_chorus_sale | 91.0% | 78.0% | 92.0% |
| l10n-france | l10n_fr_cog | 99.5% | 99.6% | 100.0% |

**Moyenne** : avant 82.8 %, référence 80.3 %, branche 83.5 %. Aucun module en recul par rapport à la référence.

## Écarts classés

- **Formatage des vues** (cause principale des reculs de la référence) : la conversion
  `attrs` / `states` resérialisait tout le fichier XML ; elle modifie désormais les seules
  balises concernées (animal 77,2 % → 99,5 %, purchase_blanket_order 83,7 % → 97,1 %).
- **Règles ajoutées après analyse** : hooks d'installation avec `env` (odoo b4a7996e9676),
  `api.Environment.manage()` retiré (odoo 6c6ca1662662), `name_get` et `states=` signalés,
  `<template>` traités (OCA/server-ux base_cancel_confirm).
- **Non automatisables** (restent à la main) : réglages `o_setting_box` → `<setting>` /
  `<block>` (refonte de structure), `name_get` → `_compute_display_name`, `states=` des champs
  Python → expressions dans les vues, réécritures JS (OWL), évolutions fonctionnelles des
  modules OCA (delivery_procurement_group_carrier, web_chatter_position...).
