# Vérité terrain OCA 12.0 → 13.0

Date : 2026-10-06. 8 dépôts OCA × 8 modules, comparés à la version 13.0 migrée à la main
par l'OCA (tools/ground_truth.py). Avant : module 12.0 non migré ; Référence : improve-migrator ;
Branche : enrich-rules-8-16.

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | partner_contact_sale_info_propagation | 50.0% | 50.0% | 50.0% |
| sale-workflow | partner_prospect | 37.0% | 37.8% | 37.8% |
| sale-workflow | partner_sale_pivot | 44.0% | 44.0% | 44.0% |
| sale-workflow | portal_sale_personal_data_only | 44.6% | 44.6% | 44.6% |
| sale-workflow | product_form_sale_link | 27.1% | 27.1% | 27.1% |
| sale-workflow | product_supplierinfo_for_customer_sale | 26.7% | 26.8% | 26.8% |
| sale-workflow | sale_advance_payment | 89.1% | 89.0% | 89.3% |
| sale-workflow | sale_automatic_workflow | 31.7% | 31.8% | 31.8% |
| purchase-workflow | procurement_purchase_no_grouping | 26.2% | 26.2% | 26.2% |
| purchase-workflow | product_form_purchase_link | 27.3% | 27.3% | 27.3% |
| purchase-workflow | product_supplierinfo_qty_multiplier | 65.9% | 66.5% | 66.5% |
| purchase-workflow | purchase_allowed_product | 24.3% | 24.3% | 24.3% |
| purchase-workflow | purchase_analytic_global | 34.1% | 34.8% | 34.8% |
| purchase-workflow | purchase_blanket_order | 34.2% | 34.1% | 34.2% |
| purchase-workflow | purchase_commercial_partner | 13.8% | 13.8% | 13.8% |
| purchase-workflow | purchase_delivery_split_date | 34.4% | 34.7% | 34.7% |
| stock-logistics-workflow | product_cost_price_avco_sync | 10.7% | 10.7% | 10.7% |
| stock-logistics-workflow | product_supplierinfo_for_customer_picking | 28.9% | 28.9% | 28.9% |
| stock-logistics-workflow | sale_order_global_stock_route | 33.7% | 33.7% | 33.7% |
| stock-logistics-workflow | stock_landed_costs_currency | 33.3% | 33.3% | 33.3% |
| stock-logistics-workflow | stock_lot_scrap | 40.1% | 40.1% | 40.1% |
| stock-logistics-workflow | stock_move_line_auto_fill | 39.3% | 40.3% | 40.3% |
| stock-logistics-workflow | stock_move_quick_lot | 40.1% | 40.1% | 40.1% |
| stock-logistics-workflow | stock_no_negative | 50.4% | 50.6% | 50.6% |
| partner-contact | base_country_state_translatable | 57.1% | 61.9% | 61.9% |
| partner-contact | base_location | 45.7% | 50.1% | 50.2% |
| partner-contact | base_location_geonames_import | 44.5% | 44.4% | 44.5% |
| partner-contact | base_location_nuts | 45.9% | 46.1% | 46.1% |
| partner-contact | base_partner_sequence | 51.2% | 52.2% | 52.2% |
| partner-contact | base_vat_sanitized | 55.4% | 55.4% | 55.4% |
| partner-contact | partner_address_street3 | 48.3% | 48.5% | 48.5% |
| partner-contact | partner_address_two_lines | 97.6% | 97.6% | 97.6% |
| account-invoicing | account_billing | 19.6% | 20.0% | 20.0% |
| account-invoicing | account_global_discount | 11.0% | 11.0% | 11.2% |
| account-invoicing | account_invoice_alternate_payer | 2.7% | 2.7% | 2.6% |
| account-invoicing | account_invoice_blocking | 2.5% | 2.5% | 2.5% |
| account-invoicing | account_invoice_check_total | 18.7% | 18.8% | 19.6% |
| account-invoicing | account_invoice_date_due | 6.1% | 6.1% | 6.1% |
| account-invoicing | account_invoice_fiscal_position_update | 35.7% | 35.2% | 36.2% |
| account-invoicing | account_invoice_fixed_discount | 7.7% | 7.8% | 7.8% |
| server-ux | barcode_action | 41.1% | 41.1% | 41.1% |
| server-ux | base_duplicate_security_group | 75.5% | 76.0% | 76.0% |
| server-ux | base_export_manager | 40.6% | 41.4% | 41.4% |
| server-ux | base_import_security_group | 53.5% | 53.5% | 53.5% |
| server-ux | base_optional_quick_create | 64.4% | 65.0% | 65.0% |
| server-ux | base_search_custom_field_filter | 57.2% | 57.2% | 57.2% |
| server-ux | base_substate | 39.5% | 39.4% | 39.7% |
| server-ux | base_technical_features | 51.5% | 53.2% | 53.2% |
| web | web_action_conditionable | 44.2% | 44.2% | 44.2% |
| web | web_advanced_search | 55.6% | 55.6% | 55.6% |
| web | web_calendar_slot_duration | 78.4% | 80.4% | 80.4% |
| web | web_company_color | 32.6% | 33.0% | 33.0% |
| web | web_decimal_numpad_dot | 64.9% | 66.2% | 66.2% |
| web | web_dialog_size | 27.3% | 27.3% | 27.3% |
| web | web_disable_export_group | 12.3% | 12.3% | 12.3% |
| web | web_domain_field | 3.2% | 3.4% | 3.4% |
| l10n-france | account_bank_statement_import_fr_cfonb | 52.3% | 52.3% | 52.3% |
| l10n-france | account_banking_fr_lcr | 32.6% | 32.7% | 32.7% |
| l10n-france | l10n_fr_account_tax_unece | 8.6% | 8.6% | 8.6% |
| l10n-france | l10n_fr_department | 93.8% | 95.8% | 95.8% |
| l10n-france | l10n_fr_department_oversea | 98.6% | 99.3% | 99.3% |
| l10n-france | l10n_fr_intrastat_product | 31.2% | 31.1% | 31.2% |
| l10n-france | l10n_fr_intrastat_service | 22.4% | 22.6% | 22.7% |
| l10n-france | l10n_fr_siret | 96.0% | 95.5% | 95.5% |

**Moyenne** : avant 40.8 %, référence 41.2 %, branche 41.3 %.

## Écarts classés

- **Scores bas pour tous** (41 %) : l'OCA a reformaté son code en 13.0 (black, prettier,
  en-têtes `<?xml ... encoding="utf-8"?>`, manifestes) ; ces lignes ne sont pas des règles
  de migration Odoo.
- **account_invoice_alternate_payer** (2,7 % → 2,6 %, une ligne) : module réécrit par l'OCA ;
  la référence écrivait `self.move_type` (champ de 14.0) là où la branche garde `self.type`
  (correct en 13.0) et renomme `partner_bank_id` → `invoice_partner_bank_id`
  (OpenUpgrade 13.0). Pas une régression.
- **Corrigé après analyse** : `<field name="model">account.invoice</field>` n'était pas
  renommé (moteur commun) ; faux « champ supprimé » des modèles fusionnés.
- **Non automatisables** : `raise UserError(_(` (refonte des messages), réécritures
  fonctionnelles, formatage.
