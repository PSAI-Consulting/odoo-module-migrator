# Vérité terrain OCA 14.0 → 15.0

Date : 2026-10-06. 8 dépôts OCA × 8 modules, comparés à la version 15.0 migrée à la main
par l'OCA (tools/ground_truth.py). Avant : module 14.0 non migré ; Référence : improve-migrator ;
Branche : enrich-rules-8-16 (avant la règle SavepointCase).

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | portal_sale_personal_data_only | 78.3% | 79.0% | 79.0% |
| sale-workflow | pricelist_cache | 89.7% | 94.7% | 94.7% |
| sale-workflow | product_form_sale_link | 96.7% | 96.7% | 96.7% |
| sale-workflow | product_supplierinfo_for_customer_elaboration | 56.8% | 56.8% | 56.8% |
| sale-workflow | product_supplierinfo_for_customer_sale | 67.4% | 67.4% | 67.4% |
| sale-workflow | sale_advance_payment | 85.9% | 85.9% | 85.9% |
| sale-workflow | sale_automatic_workflow | 76.6% | 78.0% | 78.0% |
| sale-workflow | sale_automatic_workflow_job | 66.0% | 66.2% | 66.2% |
| purchase-workflow | procurement_purchase_no_grouping | 96.7% | 96.7% | 96.7% |
| purchase-workflow | product_form_purchase_link | 70.3% | 70.3% | 70.3% |
| purchase-workflow | product_supplier_code_purchase | 84.6% | 85.1% | 85.1% |
| purchase-workflow | purchase_advance_payment | 95.2% | 95.2% | 95.2% |
| purchase-workflow | purchase_allowed_product | 74.8% | 74.8% | 74.8% |
| purchase-workflow | purchase_analytic_global | 73.6% | 73.6% | 73.6% |
| purchase-workflow | purchase_blanket_order | 97.4% | 97.4% | 97.4% |
| purchase-workflow | purchase_cancel_confirm | 97.3% | 98.6% | 98.6% |
| stock-logistics-workflow | delivery_procurement_group_carrier | 21.9% | 22.3% | 22.3% |
| stock-logistics-workflow | product_cost_price_avco_sync | 92.8% | 92.8% | 92.8% |
| stock-logistics-workflow | product_supplierinfo_for_customer_picking | 49.6% | 50.0% | 50.0% |
| stock-logistics-workflow | purchase_stock_picking_invoice_link | 93.5% | 93.8% | 93.8% |
| stock-logistics-workflow | sale_line_returned_qty | 98.7% | 99.3% | 99.3% |
| stock-logistics-workflow | sale_line_returned_qty_mrp | 98.6% | 98.6% | 98.6% |
| stock-logistics-workflow | sale_order_global_stock_route | 80.1% | 80.7% | 80.7% |
| stock-logistics-workflow | stock_account_product_run_fifo_hook | 55.8% | 55.8% | 55.8% |
| partner-contact | animal | 76.1% | 76.8% | 76.8% |
| partner-contact | base_country_state_translatable | 95.2% | 95.2% | 95.2% |
| partner-contact | base_location | 94.4% | 94.5% | 94.5% |
| partner-contact | base_location_geonames_import | 91.2% | 91.2% | 91.2% |
| partner-contact | base_location_nuts | 63.8% | 63.9% | 63.9% |
| partner-contact | base_partner_sequence | 99.3% | 99.3% | 99.3% |
| partner-contact | partner_address_street3 | 96.0% | 96.5% | 96.5% |
| partner-contact | partner_affiliate | 99.4% | 100.0% | 100.0% |
| account-invoicing | account_global_discount | 83.4% | 83.4% | 83.4% |
| account-invoicing | account_invoice_alternate_payer | 91.3% | 97.7% | 97.7% |
| account-invoicing | account_invoice_block_payment | 96.3% | 97.5% | 97.5% |
| account-invoicing | account_invoice_blocking | 92.7% | 92.7% | 92.7% |
| account-invoicing | account_invoice_change_currency | 99.4% | 99.4% | 99.4% |
| account-invoicing | account_invoice_check_picking_date | 89.6% | 89.6% | 89.6% |
| account-invoicing | account_invoice_check_total | 92.9% | 93.5% | 93.5% |
| account-invoicing | account_invoice_date_due | 93.1% | 93.1% | 93.1% |
| server-ux | barcode_action | 84.0% | 84.4% | 84.4% |
| server-ux | base_archive_date | 95.5% | 96.4% | 96.4% |
| server-ux | base_cancel_confirm | 89.5% | 89.9% | 89.9% |
| server-ux | base_custom_filter | 99.0% | 99.2% | 99.2% |
| server-ux | base_export_manager | 91.5% | 91.5% | 91.5% |
| server-ux | base_import_security_group | 80.4% | 80.4% | 80.4% |
| server-ux | base_menu_visibility_restriction | 97.9% | 99.0% | 99.0% |
| server-ux | base_optional_quick_create | 97.4% | 98.3% | 98.3% |
| web | web_action_conditionable | 62.8% | 64.1% | 64.1% |
| web | web_advanced_search | 0.9% | 0.9% | 0.9% |
| web | web_calendar_slot_duration | 21.1% | 22.5% | 22.5% |
| web | web_company_color | 67.9% | 67.9% | 67.9% |
| web | web_copy_confirm | 79.7% | 80.2% | 80.2% |
| web | web_dialog_size | 37.3% | 37.3% | 37.3% |
| web | web_disable_export_group | 24.9% | 26.1% | 26.1% |
| web | web_domain_field | 55.3% | 55.3% | 55.3% |
| l10n-france | account_banking_fr_lcr | 84.0% | 84.0% | 84.0% |
| l10n-france | account_statement_import_fr_cfonb | 95.3% | 95.7% | 95.7% |
| l10n-france | l10n_fr_account_invoice_facturx | 88.2% | 91.2% | 91.2% |
| l10n-france | l10n_fr_account_tax_unece | 89.9% | 89.9% | 89.9% |
| l10n-france | l10n_fr_chorus_account | 49.6% | 49.7% | 49.7% |
| l10n-france | l10n_fr_chorus_facturx | 87.0% | 87.0% | 87.0% |
| l10n-france | l10n_fr_chorus_sale | 81.9% | 82.6% | 82.6% |
| l10n-france | l10n_fr_cog | 98.3% | 98.4% | 98.4% |

**Moyenne** : avant 79.9 %, référence 80.4 %, branche 80.4 %. Aucun module en recul.

## Écarts classés

- Règle ajoutée après analyse : SavepointCase -> TransactionCase (fusionnés en 15.0).
- Les modules échantillonnés touchent peu les API changées en 15.0 ; écarts restants :
  assets déclarés en XML (signalés, déplacement manuel vers la clé assets du manifeste),
  attrs conservés en 15.0 (pas de changement de syntaxe), évolutions fonctionnelles OCA.
