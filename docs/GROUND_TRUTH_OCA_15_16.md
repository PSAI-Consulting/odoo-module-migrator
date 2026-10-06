# Vérité terrain OCA 15.0 → 16.0

Date : 2026-10-06. 8 dépôts OCA × 8 modules (sale-workflow, purchase-workflow,
stock-logistics-workflow, partner-contact, account-invoicing, server-ux, web, l10n-france),
comparés ligne à ligne à la version 16.0 migrée à la main par l'OCA (tools/ground_truth.py ;
README, i18n, static/description ignorés).

- **Avant** : module 15.0 non migré ;
- **Référence** : branche improve-migrator (avant ce travail) ;
- **Branche** : enrich-rules-8-16.

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | partner_contact_sale_info_propagation | 89.1% | 89.1% | 89.1% |
| sale-workflow | partner_sale_pivot | 96.8% | 98.4% | 98.4% |
| sale-workflow | portal_sale_personal_data_only | 99.3% | 100.0% | 100.0% |
| sale-workflow | pricelist_cache | 99.2% | 99.2% | 99.2% |
| sale-workflow | product_form_sale_link | 98.0% | 98.0% | 98.0% |
| sale-workflow | product_supplierinfo_for_customer_sale | 73.7% | 73.7% | 73.7% |
| sale-workflow | sale_advance_payment | 77.4% | 77.4% | 77.4% |
| sale-workflow | sale_attached_product | 99.6% | 99.8% | 99.8% |
| purchase-workflow | procurement_purchase_no_grouping | 94.5% | 94.7% | 94.7% |
| purchase-workflow | product_supplier_code_purchase | 92.4% | 93.0% | 93.6% |
| purchase-workflow | product_supplierinfo_qty_multiplier | 97.9% | 98.4% | 99.0% |
| purchase-workflow | purchase_advance_payment | 67.2% | 67.2% | 67.2% |
| purchase-workflow | purchase_allowed_product | 53.4% | 53.4% | 53.4% |
| purchase-workflow | purchase_analytic_global | 59.8% | 60.3% | 60.3% |
| purchase-workflow | purchase_blanket_order | 92.7% | 92.7% | 92.8% |
| purchase-workflow | purchase_default_terms_conditions | 97.9% | 97.9% | 97.9% |
| stock-logistics-workflow | delivery_procurement_group_carrier | 17.1% | 17.1% | 17.1% |
| stock-logistics-workflow | product_cost_price_avco_sync | 61.3% | 61.4% | 61.6% |
| stock-logistics-workflow | product_supplierinfo_for_customer_picking | 53.4% | 53.8% | 54.6% |
| stock-logistics-workflow | purchase_stock_picking_invoice_link | 91.5% | 91.5% | 91.5% |
| stock-logistics-workflow | sale_line_returned_qty | 98.0% | 98.7% | 98.7% |
| stock-logistics-workflow | sale_order_global_stock_route | 92.7% | 92.7% | 94.4% |
| stock-logistics-workflow | stock_account_product_run_fifo_hook | 95.6% | 95.6% | 95.6% |
| stock-logistics-workflow | stock_auto_move | 93.1% | 93.2% | 93.4% |
| partner-contact | account_partner_company_group | 98.2% | 100.0% | 100.0% |
| partner-contact | animal | 98.3% | 98.5% | 98.5% |
| partner-contact | base_country_state_translatable | 85.7% | 90.5% | 90.5% |
| partner-contact | base_location | 92.4% | 92.4% | 92.5% |
| partner-contact | base_location_geonames_import | 86.3% | 86.3% | 86.3% |
| partner-contact | base_location_nuts | 64.2% | 64.2% | 64.2% |
| partner-contact | base_partner_company_group | 88.8% | 89.7% | 89.7% |
| partner-contact | base_partner_sequence | 56.6% | 56.6% | 56.6% |
| account-invoicing | account_global_discount | 71.5% | 71.5% | 71.5% |
| account-invoicing | account_invoice_alternate_payer | 72.2% | 72.4% | 72.4% |
| account-invoicing | account_invoice_analytic_search | 22.8% | 23.2% | 23.2% |
| account-invoicing | account_invoice_block_payment | 98.8% | 100.0% | 100.0% |
| account-invoicing | account_invoice_blocking | 86.2% | 86.2% | 86.2% |
| account-invoicing | account_invoice_change_currency | 71.1% | 71.1% | 71.1% |
| account-invoicing | account_invoice_check_picking_date | 57.5% | 57.5% | 57.5% |
| account-invoicing | account_invoice_check_total | 72.2% | 72.2% | 72.2% |
| server-ux | announcement | 49.7% | 49.7% | 49.7% |
| server-ux | barcode_action | 70.2% | 70.2% | 70.2% |
| server-ux | base_cancel_confirm | 81.8% | 81.8% | 81.8% |
| server-ux | base_custom_filter | 75.9% | 75.9% | 75.9% |
| server-ux | base_export_manager | 83.1% | 83.1% | 83.1% |
| server-ux | base_import_security_group | 81.1% | 81.5% | 81.5% |
| server-ux | base_menu_visibility_restriction | 99.0% | 100.0% | 100.0% |
| server-ux | base_optional_quick_create | 99.1% | 100.0% | 100.0% |
| web | web_action_conditionable | 14.1% | 15.2% | 15.2% |
| web | web_advanced_search | 21.8% | 21.8% | 21.8% |
| web | web_calendar_slot_duration | 28.8% | 28.8% | 28.8% |
| web | web_chatter_position | 13.6% | 13.6% | 13.6% |
| web | web_company_color | 77.5% | 77.5% | 77.5% |
| web | web_copy_confirm | 59.6% | 60.2% | 60.2% |
| web | web_dialog_size | 49.2% | 49.2% | 49.2% |
| web | web_disable_export_group | 60.1% | 60.5% | 60.5% |
| l10n-france | account_banking_fr_lcr | 92.9% | 93.2% | 93.2% |
| l10n-france | account_statement_import_fr_cfonb | 95.3% | 95.3% | 95.7% |
| l10n-france | l10n_fr_account_invoice_facturx | 91.2% | 94.1% | 94.1% |
| l10n-france | l10n_fr_account_tax_unece | 98.1% | 98.4% | 98.4% |
| l10n-france | l10n_fr_chorus_account | 74.2% | 74.2% | 74.2% |
| l10n-france | l10n_fr_chorus_facturx | 95.1% | 96.1% | 96.1% |
| l10n-france | l10n_fr_chorus_sale | 32.9% | 32.9% | 32.9% |
| l10n-france | l10n_fr_cog | 99.9% | 100.0% | 100.0% |

**Moyenne** : avant 75.9 %, référence 76.3 %, branche 76.4 %. Aucun module en recul par rapport à la référence.

## Écarts classés

Gain faible : les modules échantillonnés touchent peu les API changées en 16.0. Les écarts
restants sont surtout la refonte analytique (`analytic_distribution`, signalée avec son
remplaçant, non automatisable), `account_type` (Selection), les vues de réglages et les
évolutions fonctionnelles des modules OCA.
