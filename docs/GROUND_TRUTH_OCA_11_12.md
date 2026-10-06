# Vérité terrain OCA 11.0 → 12.0

Date : 2026-10-06. 8 dépôts OCA (61 modules communs), comparés à la version 12.0 migrée à la main
par l'OCA (tools/ground_truth.py). Avant : module 11.0 non migré ; Référence : improve-migrator ;
Branche : enrich-rules-8-16 (avant la règle des identifiants uom).

| Dépôt | Module | Avant | Référence | Branche |
|---|---|---:|---:|---:|
| sale-workflow | partner_contact_sale_info_propagation | 89.3% | 89.9% | 89.9% |
| sale-workflow | partner_prospect | 91.7% | 92.3% | 92.3% |
| sale-workflow | product_supplierinfo_for_customer_sale | 69.0% | 69.4% | 69.4% |
| sale-workflow | sale_automatic_workflow | 75.8% | 75.7% | 75.7% |
| sale-workflow | sale_automatic_workflow_payment_mode | 83.1% | 84.9% | 84.9% |
| sale-workflow | sale_blanket_order | 81.1% | 81.0% | 81.2% |
| sale-workflow | sale_commercial_partner | 84.6% | 84.6% | 84.6% |
| sale-workflow | sale_disable_inventory_check | 26.6% | 27.1% | 27.1% |
| purchase-workflow | procurement_purchase_no_grouping | 43.5% | 43.5% | 43.5% |
| purchase-workflow | purchase_allowed_product | 89.7% | 89.7% | 89.7% |
| purchase-workflow | purchase_blanket_order | 96.7% | 96.7% | 96.8% |
| purchase-workflow | purchase_date_planned_manual | 92.2% | 92.6% | 93.0% |
| purchase-workflow | purchase_delivery_split_date | 59.6% | 59.6% | 59.6% |
| purchase-workflow | purchase_discount | 42.3% | 42.6% | 42.6% |
| purchase-workflow | purchase_exception | 55.4% | 55.4% | 55.4% |
| purchase-workflow | purchase_force_invoiced | 99.4% | 100.0% | 100.0% |
| stock-logistics-workflow | product_cost_price_avco_sync | 91.7% | 91.7% | 91.7% |
| stock-logistics-workflow | purchase_stock_picking_restrict_cancel | 35.0% | 36.2% | 36.2% |
| stock-logistics-workflow | stock_lot_scrap | 27.4% | 27.8% | 27.8% |
| stock-logistics-workflow | stock_move_quick_lot | 82.3% | 82.3% | 82.3% |
| stock-logistics-workflow | stock_no_negative | 70.1% | 70.1% | 70.1% |
| stock-logistics-workflow | stock_picking_auto_create_lot | 96.9% | 97.7% | 97.7% |
| stock-logistics-workflow | stock_picking_back2draft | 98.3% | 98.3% | 98.3% |
| stock-logistics-workflow | stock_picking_backorder_strategy | 92.4% | 92.4% | 92.4% |
| partner-contact | base_country_state_translatable | 71.4% | 76.2% | 76.2% |
| partner-contact | base_location | 11.2% | 11.2% | 11.2% |
| partner-contact | base_location_geonames_import | 46.3% | 46.6% | 46.6% |
| partner-contact | base_location_nuts | 94.9% | 94.9% | 94.9% |
| partner-contact | base_partner_sequence | 73.7% | 74.7% | 74.7% |
| partner-contact | base_vat_sanitized | 98.1% | 100.0% | 100.0% |
| partner-contact | partner_address_street3 | 98.9% | 99.4% | 99.4% |
| partner-contact | partner_affiliate | 74.2% | 76.7% | 76.7% |
| account-invoicing | account_global_discount | 86.4% | 93.8% | 93.8% |
| account-invoicing | account_invoice_alternate_payer | 90.1% | 90.1% | 90.1% |
| account-invoicing | account_invoice_anglo_saxon_no_cogs_deferral | 93.1% | 93.8% | 93.8% |
| account-invoicing | account_invoice_blocking | 93.6% | 93.6% | 93.6% |
| account-invoicing | account_invoice_change_currency | 93.5% | 93.5% | 93.5% |
| account-invoicing | account_invoice_check_total | 97.4% | 97.4% | 97.4% |
| account-invoicing | account_invoice_fiscal_position_update | 90.3% | 90.3% | 90.3% |
| account-invoicing | account_invoice_fixed_discount | 96.6% | 96.6% | 96.6% |
| server-ux | barcode_action | 86.1% | 86.6% | 86.6% |
| server-ux | base_export_manager | 85.6% | 85.3% | 85.3% |
| server-ux | base_import_security_group | 53.6% | 53.6% | 53.6% |
| server-ux | base_optional_quick_create | 70.4% | 70.4% | 70.4% |
| server-ux | base_technical_features | 97.8% | 95.2% | 95.2% |
| server-ux | base_tier_validation | 56.4% | 55.5% | 55.5% |
| server-ux | base_tier_validation_formula | 88.9% | 88.9% | 88.9% |
| server-ux | date_range | 42.7% | 43.1% | 43.1% |
| web | web_action_conditionable | 96.6% | 96.6% | 96.6% |
| web | web_advanced_search | 87.4% | 87.4% | 87.4% |
| web | web_decimal_numpad_dot | 97.2% | 100.0% | 100.0% |
| web | web_dialog_size | 85.9% | 85.9% | 85.9% |
| web | web_disable_export_group | 65.8% | 66.7% | 66.7% |
| web | web_drop_target | 94.3% | 94.3% | 94.3% |
| web | web_editor_background_color | 3.5% | 3.5% | 3.5% |
| web | web_environment_ribbon | 75.3% | 75.9% | 75.9% |
| l10n-france | l10n_fr_department | 32.7% | 32.6% | 32.6% |
| l10n-france | l10n_fr_department_oversea | 92.9% | 92.9% | 92.9% |
| l10n-france | l10n_fr_intrastat_product | 87.3% | 88.8% | 88.8% |
| l10n-france | l10n_fr_siret | 77.3% | 77.3% | 77.3% |
| l10n-france | l10n_fr_state | 40.3% | 40.3% | 40.3% |

**Moyenne** : avant 75.4 %, référence 75.9 %, branche 75.9 %. Aucun module en recul.

## Écarts classés

- **Corrigé après analyse** : le renommage product.uom -> uom.uom remplaçait aussi le nom de
  table 'product_uom', qui est surtout un nom de champ : 16 modules reculaient (moteur commun).
- **Règle ajoutée** : identifiants XML des unités de mesure product.* -> uom.* (24 identifiants).
- **Non automatisables** : en-têtes de copyright / licence, @api.multi (encore valide en 12.0),
  évolutions fonctionnelles des modules OCA.
