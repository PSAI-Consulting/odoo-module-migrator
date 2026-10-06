# Vérité terrain OCA 13.0 → 14.0

Date : 2026-10-06. 8 dépôts OCA × 8 modules, comparés à la version 14.0 migrée à la main
par l'OCA (tools/ground_truth.py). Avant : module 13.0 non migré ; Référence : improve-migrator ;
Branche : enrich-rules-8-16 (avant les règles action_done / post).

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | partner_prospect | 94.9% | 95.5% | 95.5% |
| sale-workflow | portal_sale_personal_data_only | 16.0% | 16.6% | 16.6% |
| sale-workflow | product_form_sale_link | 96.7% | 96.7% | 96.7% |
| sale-workflow | product_supplierinfo_for_customer_elaboration | 99.3% | 100.0% | 100.0% |
| sale-workflow | product_supplierinfo_for_customer_sale | 63.9% | 63.9% | 63.9% |
| sale-workflow | sale_advance_payment | 65.1% | 65.1% | 65.1% |
| sale-workflow | sale_automatic_workflow | 72.9% | 74.2% | 74.2% |
| sale-workflow | sale_automatic_workflow_delivery_state | 80.0% | 84.0% | 84.0% |
| purchase-workflow | procurement_purchase_no_grouping | 88.4% | 88.4% | 88.4% |
| purchase-workflow | product_form_purchase_link | 70.3% | 70.3% | 70.3% |
| purchase-workflow | purchase_allowed_product | 73.4% | 73.4% | 73.4% |
| purchase-workflow | purchase_analytic_global | 99.2% | 100.0% | 100.0% |
| purchase-workflow | purchase_blanket_order | 95.4% | 95.7% | 95.7% |
| purchase-workflow | purchase_commercial_partner | 96.8% | 98.4% | 98.4% |
| purchase-workflow | purchase_delivery_split_date | 51.3% | 51.3% | 51.3% |
| purchase-workflow | purchase_deposit | 87.9% | 87.9% | 87.9% |
| stock-logistics-workflow | delivery_package_default_shipping_weight | 82.9% | 82.9% | 82.9% |
| stock-logistics-workflow | delivery_total_weight_from_packaging | 83.5% | 83.5% | 83.5% |
| stock-logistics-workflow | procurement_auto_create_group_carrier | 95.4% | 95.4% | 95.4% |
| stock-logistics-workflow | product_cost_price_avco_sync | 89.2% | 89.2% | 89.2% |
| stock-logistics-workflow | product_supplierinfo_for_customer_picking | 32.1% | 32.1% | 32.1% |
| stock-logistics-workflow | purchase_stock_picking_invoice_link | 85.0% | 85.0% | 85.0% |
| stock-logistics-workflow | sale_line_returned_qty | 98.0% | 98.7% | 98.7% |
| stock-logistics-workflow | sale_line_returned_qty_mrp | 68.5% | 68.5% | 68.5% |
| partner-contact | base_country_state_translatable | 81.0% | 81.0% | 81.0% |
| partner-contact | base_location | 73.7% | 74.8% | 74.8% |
| partner-contact | base_location_geonames_import | 96.4% | 96.4% | 96.4% |
| partner-contact | base_location_nuts | 55.0% | 54.9% | 54.9% |
| partner-contact | base_partner_sequence | 99.3% | 99.3% | 99.3% |
| partner-contact | partner_address_street3 | 21.8% | 22.1% | 22.1% |
| partner-contact | partner_affiliate | 73.8% | 73.8% | 73.8% |
| partner-contact | partner_capital | 94.4% | 94.4% | 94.4% |
| account-invoicing | account_billing | 90.9% | 92.2% | 92.5% |
| account-invoicing | account_global_discount | 86.2% | 94.7% | 94.7% |
| account-invoicing | account_invoice_alternate_payer | 81.9% | 75.7% | 75.7% |
| account-invoicing | account_invoice_base_invoicing_mode | 28.3% | 28.3% | 28.3% |
| account-invoicing | account_invoice_blocking | 90.2% | 90.2% | 90.2% |
| account-invoicing | account_invoice_check_picking_date | 88.9% | 89.6% | 89.6% |
| account-invoicing | account_invoice_check_total | 82.2% | 89.1% | 89.1% |
| account-invoicing | account_invoice_date_due | 66.1% | 66.1% | 66.1% |
| server-ux | barcode_action | 79.7% | 82.3% | 84.8% |
| server-ux | base_action_visibility_restriction | 97.6% | 98.2% | 98.2% |
| server-ux | base_archive_date | 99.1% | 100.0% | 100.0% |
| server-ux | base_custom_filter | 73.4% | 73.4% | 73.4% |
| server-ux | base_export_manager | 95.5% | 95.7% | 95.7% |
| server-ux | base_import_security_group | 53.6% | 54.2% | 54.2% |
| server-ux | base_menu_visibility_restriction | 97.9% | 99.0% | 99.0% |
| server-ux | base_optional_quick_create | 79.5% | 80.3% | 80.3% |
| web | web_action_conditionable | 93.9% | 93.9% | 93.9% |
| web | web_advanced_search | 11.1% | 11.1% | 11.1% |
| web | web_calendar_slot_duration | 91.8% | 93.9% | 93.9% |
| web | web_company_color | 81.7% | 81.7% | 81.7% |
| web | web_decimal_numpad_dot | 93.2% | 94.5% | 94.5% |
| web | web_dialog_size | 86.2% | 86.8% | 86.8% |
| web | web_disable_export_group | 47.8% | 49.1% | 49.1% |
| web | web_domain_field | 99.1% | 99.1% | 99.1% |
| l10n-france | account_banking_fr_lcr | 96.8% | 96.8% | 96.8% |
| l10n-france | l10n_fr_account_tax_unece | 82.2% | 82.2% | 82.2% |
| l10n-france | l10n_fr_department | 14.1% | 13.9% | 13.9% |
| l10n-france | l10n_fr_department_oversea | 55.4% | 55.4% | 55.4% |
| l10n-france | l10n_fr_intrastat_product | 18.6% | 19.0% | 19.0% |
| l10n-france | l10n_fr_intrastat_service | 72.0% | 74.2% | 74.2% |
| l10n-france | l10n_fr_siret | 2.8% | 2.8% | 2.8% |
| l10n-france | l10n_fr_state | 20.4% | 20.4% | 20.4% |

**Moyenne** : avant 74.1 %, référence 74.6 %, branche 74.7 %. Aucun module en recul.

## Écarts classés

- Règles ajoutées après analyse : picking.action_done() -> _action_done() (odoo 0c6488a95aa5),
  payment.post() -> action_post() (odoo caeb782841fc), sur les variables qui désignent
  clairement un picking / un paiement ; avertissement sinon.
- Convertisseur <report> / <act_window> refait (module du modèle, binding des rapports).
- Non automatisables : assertEquals (dépréciation Python, pas Odoo), en-têtes / licences et
  évolutions fonctionnelles des modules OCA.
