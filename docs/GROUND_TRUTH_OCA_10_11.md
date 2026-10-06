# Vérité terrain OCA 10.0 → 11.0

Date : 2026-10-06. 8 dépôts OCA (53 modules communs), comparés à la version 11.0 migrée à la main
par l'OCA (tools/ground_truth.py). Avant : module 10.0 non migré ; Référence : improve-migrator ;
Branche : enrich-rules-8-16.

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | product_supplierinfo_for_customer_sale | 39.4% | 39.7% | 39.7% |
| sale-workflow | sale_automatic_workflow | 92.4% | 93.3% | 93.3% |
| sale-workflow | sale_automatic_workflow_payment_mode | 59.9% | 58.8% | 58.8% |
| sale-workflow | sale_blanket_order | 24.5% | 24.6% | 24.6% |
| sale-workflow | sale_commercial_partner | 36.4% | 36.9% | 36.9% |
| sale-workflow | sale_exception | 53.2% | 56.0% | 56.0% |
| sale-workflow | sale_fixed_discount | 56.9% | 58.1% | 58.1% |
| sale-workflow | sale_force_invoiced | 83.2% | 86.6% | 86.6% |
| purchase-workflow | procurement_purchase_no_grouping | 40.4% | 41.9% | 41.9% |
| purchase-workflow | product_supplierinfo_discount | 74.5% | 76.8% | 76.8% |
| purchase-workflow | purchase_allowed_product | 84.5% | 88.6% | 88.6% |
| purchase-workflow | purchase_date_planned_manual | 55.9% | 56.7% | 56.7% |
| purchase-workflow | purchase_delivery_split_date | 80.6% | 84.6% | 84.6% |
| purchase-workflow | purchase_discount | 62.5% | 60.8% | 60.8% |
| purchase-workflow | purchase_landed_cost | 90.5% | 90.8% | 90.8% |
| purchase-workflow | purchase_location_by_line | 88.4% | 89.3% | 89.3% |
| stock-logistics-workflow | product_expiry_simple | 27.7% | 27.9% | 27.9% |
| stock-logistics-workflow | stock_lot_scrap | 85.6% | 88.3% | 89.6% |
| stock-logistics-workflow | stock_no_negative | 35.6% | 36.1% | 36.4% |
| stock-logistics-workflow | stock_pack_operation_auto_fill | 9.0% | 9.0% | 9.2% |
| stock-logistics-workflow | stock_picking_back2draft | 93.5% | 99.1% | 99.1% |
| stock-logistics-workflow | stock_picking_backorder_strategy | 78.1% | 78.9% | 78.9% |
| stock-logistics-workflow | stock_picking_customer_ref | 97.8% | 94.1% | 94.1% |
| stock-logistics-workflow | stock_picking_filter_lot | 31.8% | 33.0% | 33.0% |
| partner-contact | base_country_state_translatable | 58.1% | 70.4% | 70.4% |
| partner-contact | base_location | 27.1% | 27.5% | 27.5% |
| partner-contact | base_location_geonames_import | 65.1% | 66.3% | 66.3% |
| partner-contact | base_location_nuts | 96.3% | 97.2% | 97.2% |
| partner-contact | base_partner_merge | 65.4% | 66.0% | 66.0% |
| partner-contact | base_partner_sequence | 82.5% | 82.2% | 82.2% |
| partner-contact | base_vat_sanitized | 67.9% | 73.6% | 73.6% |
| partner-contact | partner_academic_title | 25.0% | 25.7% | 25.7% |
| account-invoicing | account_invoice_blocking | 30.9% | 41.9% | 41.9% |
| account-invoicing | account_invoice_change_currency | 17.2% | 17.5% | 17.5% |
| account-invoicing | account_invoice_check_total | 39.8% | 40.2% | 40.2% |
| account-invoicing | account_invoice_fiscal_position_update | 89.4% | 90.4% | 90.4% |
| account-invoicing | account_invoice_fixed_discount | 88.8% | 91.5% | 91.5% |
| account-invoicing | account_invoice_force_number | 96.0% | 97.0% | 97.0% |
| account-invoicing | account_invoice_line_description | 86.7% | 90.6% | 90.6% |
| account-invoicing | account_invoice_line_sequence | 84.9% | 88.8% | 88.8% |
| web | web_access_rule_buttons | 2.5% | 2.5% | 2.5% |
| web | web_action_conditionable | 14.6% | 14.6% | 14.6% |
| web | web_decimal_numpad_dot | 67.6% | 66.2% | 66.2% |
| web | web_dialog_size | 58.7% | 58.7% | 58.7% |
| web | web_drop_target | 82.7% | 85.2% | 85.2% |
| web | web_editor_background_color | 92.2% | 92.3% | 92.3% |
| web | web_environment_ribbon | 65.6% | 66.7% | 66.7% |
| web | web_export_view | 51.2% | 51.2% | 51.2% |
| l10n-france | l10n_fr_department | 86.6% | 89.0% | 89.0% |
| l10n-france | l10n_fr_department_oversea | 40.5% | 42.7% | 42.7% |
| l10n-france | l10n_fr_intrastat_product | 77.5% | 78.0% | 78.0% |
| l10n-france | l10n_fr_siret | 69.3% | 72.5% | 72.5% |
| l10n-france | l10n_fr_state | 83.3% | 87.5% | 87.5% |

**Moyenne** : avant 62.2 %, référence 63.8 %, branche 63.9 %. Aucun module en recul.

## Écarts classés

- Les pistes sont surtout des en-têtes (copyright, licence) et du formatage réécrits par l'OCA
  en 11.0 (passage à Python 3, pylint-odoo), sans règle de migration Odoo associée.
- `<data>` conservé par l'OCA dans `<odoo>` : choix de style, `<odoo><data>` et `<odoo>` sont
  équivalents.
