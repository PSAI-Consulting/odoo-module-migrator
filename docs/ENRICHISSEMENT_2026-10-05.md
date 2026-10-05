# Enrichissement des règles 17.0 → 20.0 (session du 05/10/2026)

Branche `enrich-rules` (depuis `improve-migrator`). Toutes les règles ajoutées
citent leur preuve dans le code d'Odoo (commit `odoo <sha>` / `enterprise <sha>`,
ou fichier + branche) ; ce qui n'a pas pu être prouvé est resté **candidat
commenté** ou **avertissement**, jamais transformation automatique.

## Sources utilisées

| Source | Contenu |
|---|---|
| `odoo/odoo` (git, depuis 2023-09) | 17.0, 18.0, 19.0, 20.0 (+ saas-17.2 → saas-19.4) |
| `LBruyere/enterprise` (fork privé d'`odoo/enterprise`) | 17.0, 18.0, 19.0, 20.0 depuis 2023-09 (`odoo/enterprise` lui-même n'est pas accessible à la session) |
| `OCA/OpenUpgrade` | 18.0, 19.0 (`apriori.py`, `pre-migration.py`, analyses) ; 20.0 vide |
| Dépôts OCA | sale-workflow, purchase-workflow, stock-logistics-workflow, partner-contact, account-invoicing, server-ux, web, l10n-france |

Les sources Odoo 20 utilisent la syntaxe Python 3.12 : les extractions ont été
lancées avec Python 3.13 (et `tools/extract_fields.py` a désormais un repli
regex quand `ast` ne peut pas lire un fichier).

## Règles ajoutées, par type et par saut

| Type | 17→18 | 18→19 | 19→20 |
|---|---:|---:|---:|
| `renamed_fields` (curated, vérifiés) | – | – | **93** (+3 existants) |
| `removed_fields` (curated : remplaçant indiqué) | 22 | 40 | 140 |
| `renamed_models` (curated) | – | – | 4 |
| `removed_models` | – | – | 155 générés + 36 messages curated |
| `deprecated_modules` (curated) | 19 | 3 | 9 |
| `text_replaces` (équivalence exacte prouvée) | 1 | – | 6 |
| `text_errors` | – | 1 | 10 |
| `text_warnings` | 2 | – | 1 |

### Champs 19.0 → 20.0 (`renamed_fields/migrate_190_200`)

Les **213 candidats** de `candidates.yaml` sont tous annotés `# oui : curated.yaml`
ou `# non : <raison>` (82 oui, 131 non). Chaque renommage accepté a été vérifié
**modèle par modèle** : champs parsés avant / après le commit, et dans la
branche 20.0 (ancien nom absent, nouveau présent, même type / comodel), puis
étendu aux autres modèles du même commit. Principaux :

- `odoo 3852885f37aa '[IMP] uom: rename logistic fields'` : `product_uom(_id)` →
  `uom_id` sur **21 modèles** (stock.move, stock.move.line, stock.quant,
  purchase.order.line, mrp.production, mrp.bom(.line), repair.order…) et
  `mrp.production.schedule` (Enterprise). `sale.order.line` et
  `account.move.line` gardent `product_uom_id` (vérifié).
- `odoo d37cf89a6ff1` : `hr.leave.type` fusionné dans `hr.work.entry.type`
  (29 champs sur 35 repris) → `holiday_status_id` → `work_entry_type_id` sur
  10 modèles.
- `location_final_id` → `forecasted_location_id`, `contract_type_id` →
  `employee_type_id` (hr.contract.type renommé hr.employee.type),
  `starred` → `is_bookmarked`, `acc_type` → `account_type`,
  `l10n_co_dian_*` → `l10n_co_edi_*`, codes des prestataires de paie →
  `hr.employee.external_code`…

**Trou corrigé** : l'extracteur retirait les candidats de la liste des champs
supprimés ; les candidats **rejetés** n'étaient donc signalés nulle part. Ils
sont dans `removed_fields/migrate_190_200/curated.yaml`, avec le champ
successeur quand il en est un (comodel, valeurs ou unité changés) — sans
renommage automatique.

### Candidats rejetés (raisons)

| Raison | Exemples |
|---|---|
| comodel différent | `account.account.group_id` → `parent_id` (account.group → account.account), `hr.applicant.user_id` → `recruiter_id` (res.users → hr.employee), `sdd_mandate_id` → `mandate_id` |
| valeurs de sélection changées | `timesheet_invoice_type` → `billable_type`, `maintenance.request.kanban_state` → `state`, `attendance_overtime_validation` |
| échelle / unité changée | `deductible_amount` (défaut 100) → `deductible_percentage` (défaut 1.0), `postpone_max_days` |
| sens différent ou élargi | `translated_product_name` → `label`, `l10n_my_invoice_need_edi`, options IoT regroupées en `use_iot_box` |
| nouveau champ absent du modèle en 20.0 | `res.company.*_code` → `external_code` (seulement sur hr.employee), `account.payment.end_to_end_uuid` |
| plusieurs champs pour un | `actual_lastcall` / `last_executed_carryover_date` → `last_accrual` |
| sans rapport | champs ajoutés par hasard dans le même commit |

### Modèles 19.0 → 20.0

- `tools/extract_changes.py models` (nouveau) sur odoo + enterprise :
  155 modèles supprimés (`removed_models/migrate_190_200/generated.yaml`).
- Renommages automatiques (même module, renommage annoncé par le commit) :
  `hr.contract.type` → `hr.employee.type`, `hr.payroll.dashboard.warning` →
  `hr.payroll.warning`, `voip.country.code.mixin` → `voip.phone.country.mixin`,
  `ai.topic` → `ai.skill`.
- Modèles déplacés dans un **autre module** (le préfixe des xmlids
  `module.model_x` changerait) : signalés avec leur successeur, pas renommés
  (`website.base.unit` → `product.base.unit`, `sdd.mandate` →
  `account.direct.debit.mandate`, `l10n_co_dian.*` → `l10n_co_edi.*`…).
- Messages vérifiés : `ir.model.access` / `ir.rule` → `ir.access`,
  `hr.leave.type` → `hr.work.entry.type`, `account.group` →
  `account.account.parent_id`, `res.bank` → `res.partner.bank`,
  `stock.scrap` → mouvements de stock. `mail.tracking.value` n'est pas
  supprimé (déplacé dans `mail_tracking`).
- `base_migration_script` : pour les modèles aussi, la première règle chargée
  (`curated.yaml`) l'emporte désormais sur `generated.yaml`.

### Modules

- 17→18 : 15 entrées de l'`apriori.py` 18.0 d'OpenUpgrade absentes de
  `modules.yaml` ; renommages OCA vérifiés dans les branches
  (`account_banking_fr_lcr` → `account_payment_fr_lcr`,
  `product_supplierinfo_for_customer_picking` → `product_customerinfo_picking`) ;
  fusions Enterprise (`l10n_br_edi_sale_services`, `l10n_mx_edi_stock_extended_31`).
- 18→19 : fusions Enterprise (`l10n_be_hr_contract_salary_mobility_budget`,
  `l10n_in_reports_gstr_spreadsheet`, `l10n_us_hr_payroll_state_calculation`).
- 19→20 : modules marqués `removed` alors que le commit les fusionne :
  `website_sale_comparison_wishlist` → `website_sale`, `pos_self_order_adyen` →
  `pos_adyen`, `pos_self_order_stripe` / `pos_restaurant_stripe` → `pos_stripe`,
  `hr_work_entry_holidays` → `hr_holidays`, `quality_mrp_workorder_iot` →
  `mrp_iot`, `l10n_br_*_fiscal_reform`, `l10n_be_hr_payroll_dimona_auto`.
  Cible finale quand le module visé est lui-même fusionné dans le même saut.

### API Python

- 19→20, remplacements exacts (code 19.0 supprimé en 20.0 cité) :
  `_filter_access_rules(_python)()` → `_filtered_access()`,
  `check_access_rule()` → `check_access()` (odoo 0915e817f41),
  `group_operator=` → `aggregator=` (odoo 080bbf6153a),
  `odoo.tools.test_reports` → `odoo.tests.reports`, `odoo.tests.common.Form`
  → `odoo.tests.Form`.
- 19→20, erreurs : `check_access_rights()`, `create_unique_index()`,
  `split_for_in_conditions()`, `check_method_name()`, `ustr()`, `flatten()`,
  `load_manifest()`, `manage_changes()`, `pg_varchar()` ; avertissement
  `ReadonlyDict`.
- 17→18 : `x.user_has_groups(spec)` → `x.env.user.has_groups(spec)` pour les
  receveurs autres que `self` (même algorithme 17.0 / 18.0) ; avertissement
  `'type': 'product'` (type de produit supprimé, `is_storable`).
- 18→19 : erreur `odoo.fields.first`.

### Champs supprimés : remplaçant indiqué (17→18, 18→19, 19→20)

Commit de suppression retrouvé (`git log -S`) et lu pour chaque champ :
`account.move.to_check` → `checked` (logique inversée), `period_lock_date` →
`sale_lock_date` / `purchase_lock_date`, `detailed_type` → `type` +
`is_storable`, `res.partner.mobile` → `phone`, `stock.move.group_id` →
`reference_ids` (stock.reference), `product_packaging_id` → unités de mesure,
`uom_po_id` → `product.supplierinfo.product_uom_id`, `route_id` → `route_ids`,
options de vente → sections optionnelles, `account.move.checked` →
`review_state`, `company_type` → `is_company`, `company_name` → `parent_name`…

## Outils

| Commande | Rôle |
|---|---|
| `extract_changes.py fields --sources` | compare aussi les sources quand OpenUpgrade a des données (Enterprise, champs sans migration de données) et fusionne sans doublon |
| `extract_changes.py models` | modèles supprimés / candidats au renommage par comparaison des `_name` |
| `extract_changes.py js` | modules JS `@module/chemin` supprimés (`text_errors`) ou déplacés dans le même module, mêmes exports (`text_replaces` des imports et des assets du manifest) ; déplacement vers un autre module : erreur avec le nouvel emplacement |
| `extract_changes.py views` | vues (`ir.ui.view`, `template`) supprimées de modules toujours présents → `text_errors` sur `inherit_id` / `ref` / `t-call` / `env.ref` |
| `tools/ground_truth.py` | migre des modules OCA et compare avec la version faite à la main |

Corrections : repli regex pour les fichiers Odoo 20 illisibles par `ast` sous
Python 3.11 (des modèles comme `mrp.bom` paraissaient supprimés) ; un seul
`git show` par commit (les extractions ne finissaient pas) ; dans
`analysis/fields.py`, les enfants d'un `<field position="after|before|replace">`
sont des champs du modèle de la vue (ils n'étaient ni renommés ni signalés).

## Vérité terrain OCA 17→18

`docs/GROUND_TRUTH_OCA_17_18.md` : 64 modules (8 dépôts × 8) ; 83,5 % de lignes
identiques à la version OCA avant migration, 84,1 % après. Les écarts restants
sont surtout des refontes propres à l'OCA (tests réécrits, reformatage,
`/** @odoo-module **/` retiré, `_() % {...}` → arguments nommés), pas des
changements imposés par Odoo. Piste prouvée et ajoutée : `'type': 'product'`.

## Limites

- `generated.yaml` n'a pas été régénéré (17→18, 18→19, 19→20 champs) : les
  corrections sont dans `curated.yaml`.
- Fork Enterprise : copie de `odoo/enterprise` à jour au 05/10/2026 (dernier
  commit 20.0 : 81b967b831f) ; commits antérieurs à 2023-09 non disponibles.
- 18 champs supprimés 19→20 n'ont pas de commit de suppression retrouvé
  (source = chemin du fichier) ; vérifiés absents de 20.0.
- Renommages de modèles inter-modules : seulement signalés (les xmlids
  `module.model_x` ne sont pas réécrits par `handle_renamed_models`).

## Reste à faire

- Relire `renamed_models/migrate_190_200/candidates.yaml` à chaque mise à jour
  de 20.0, et `removed_fields/migrate_190_200/generated.yaml` : 261 champs des
  modèles courants citent leur commit, une partie mérite un remplaçant.
- Sauts 8 → 17 (hors périmètre de cette session).
