# Lot B — règles curated 16.0 à 20.0

## Périmètre et sources

Le travail a été réalisé dans le worktree
`D:\Odoo\local-addons\odoo-module-migrator-lotb`, sur la branche
`codex/curated-rules-16-20`, à partir de `09b6c04`. Le worktree témoin
`D:\Odoo\local-addons\odoo-module-migrator-lotb-before` est resté détaché sur
ce commit pour le benchmark. Aucun dépôt source ni worktree Odoo/OCA
supplémentaire n'a été nécessaire.

Les règles générées ont été recalculées avec Odoo, Enterprise, Design Themes et
OpenUpgrade. Les dépôts OCA ont été consultés comme preuves et utilisés pour le
benchmark. Ils ne sont pas agrégés comme un unique inventaire de modules : une
branche OCA récente incomplète ferait passer à tort tout module non encore porté
pour un module supprimé. Les déplacements OCA viennent donc d'OpenUpgrade
`apriori.py`, qui est la source déterministe prévue par l'extracteur.

## Inventaire avant / après

Les nombres ci-dessous sont ceux du validateur. `curated` signifie règle v2
active ; toutes les nouvelles règles ont `confidence: verified` et aucune règle
`unknown` n'a été ajoutée.

| Étape | Catégorie | Avant | Après |
|---|---|---:|---:|
| 16→17 | modules generated / curated | 99 / 7 | 99 / 9 |
| 16→17 | modèles supprimés generated / curated | 50 / 0 | 73 / 1 |
| 16→17 | champs supprimés generated / curated | 767 / 11 | 512 / 11 |
| 16→17 | champs renommés generated / curated | 15 / 38 | 1 / 38 |
| 16→17 | types / propriétés curated | 0 / 0 | 49 / 2 |
| 16→17 | erreurs texte curated / generated | 9 / 2538 | 21 / 2538 |
| 17→18 | modules generated / curated | 103 / 19 | 101 / 22 |
| 17→18 | modèles supprimés generated / curated | 26 / 0 | 75 / 2 |
| 17→18 | champs supprimés generated / curated | 197 / 63 | 577 / 63 |
| 17→18 | champs renommés generated / curated | 15 / 38 | 2 / 38 |
| 17→18 | types / propriétés curated | 0 / 0 | 25 / 4 |
| 17→18 | erreurs texte curated / generated | 7 / 850 | 17 / 854 |
| 18→19 | modules generated / curated | 127 / 3 | 124 / 5 |
| 18→19 | modèles supprimés generated / curated | 51 / 0 | 178 / 3 |
| 18→19 | champs supprimés generated / curated | 379 / 114 | 715 / 114 |
| 18→19 | champs renommés generated / curated | 26 / 56 | 19 / 56 |
| 18→19 | types / propriétés curated | 0 / 0 | 32 / 11 |
| 18→19 | erreurs texte curated / generated | 10 / 2278 | 27 / 2278 |
| 19→20 | modules generated / curated | 137 / 10 | 128 / 11 |
| 19→20 | modèles supprimés generated / curated | 155 / 36 | 155 / 36 |
| 19→20 | champs supprimés generated / curated | 1131 / 140 | 1132 / 140 |
| 19→20 | champs renommés generated / curated | 4 / 98 | 4 / 98 |
| 19→20 | types / propriétés curated | 1 / 1 | 83 / 17 |
| 19→20 | erreurs texte curated / generated | 20 / 2446 | 31 / 2444 |

Les grands écarts des listes generated viennent d'un nouvel instantané des
sources et de l'analyse `--sources` : modèles/champs hérités sont désormais
attribués plus complètement, les faux renommages heuristiques ont été déplacés
vers les candidates, et les fichiers JS/vues ont été réémis dans l'ordre
déterministe courant. Les baisses de modules 17→20 viennent de règles désormais
masquées par les corrections curated et de modules de transition disparus des
branches courantes. Le 16→17 est identique après correction du chemin du dépôt
OpenUpgrade.

## Règles vérifiées ajoutées

- 222 changements de type ou de propriété ont été promus après vérification de
  la transition exacte entre le parent et le commit : 49/2 en 16→17, 25/4 en
  17→18, 32/11 en 18→19 et 82/16 nouvelles règles en 19→20. Chaque entrée cite
  dépôt, SHA, titre, fichier et lignes avant/après dans les huit fichiers
  `field_types/*/curated_metadata.yaml` et
  `field_properties/*/curated_metadata.yaml`. La preuve historique de
  `sale.order.line.customer_lead` a également été corrigée vers
  `6ac707ad6d7e`.
- Modules : `account_sequence → account`,
  `l10n_latam_account_sequence → l10n_latam_invoice_document`,
  `account_payment_term → account`, `l10n_de_audit_trail → l10n_de`,
  `l10n_dk_audit_trail → l10n_dk`,
  `l10n_in_documents → l10n_in_reports`,
  `l10n_in_withholding_payment → l10n_in_reports` et
  `l10n_dk_oioubl → l10n_dk`. Les SHA, titres et lignes sont dans les quatre
  `curated_merges.yaml`.
- Modèles : `mailing.contact.subscription → mailing.subscription`,
  `mail.notification.web.push → mail.push`,
  `mail.partner.device → mail.push.device`,
  `hr.candidate.skill → hr.applicant.skill`,
  `procurement.group → stock.reference` et
  `stock.package_level → stock.package.history`. Les mappings de champs et
  validations sont dans les trois `curated_successors.yaml`.
- 50 suppressions exactes de méthodes surchargeables ont produit des erreurs
  ciblées et prouvées dans les quatre `curated_removed_methods.yaml`.
- Le moteur considère maintenant une suppression structurée à identité
  préservée comme masquée par son renommage effectif. Cela supprime six doubles
  diagnostics tout en gardant la recommandation structurée disponible.

## Hypothèses rejetées

- 92 candidats de type/propriété ont été rejetés : le commit trouvé ne réalisait
  pas la transition exacte entre son parent et lui-même, ou la définition était
  absente/ambiguë. Aucun n'a été activé.
- 21 candidats de méthodes n'ont pas donné de nouvelle règle : cas déjà couvert,
  absence de suppression exacte ou, pour `_read_group_get_annoted_groupby`,
  absence d'un commit local démontrant la suppression.
- Les cinq modules `hr_appraisal_contract`, `hr_contract_reports`,
  `hr_holidays_contract_gantt`, `project_enterprise_hr_contract` et
  `test_hr_contract_calendar` restent `removed`. Le commit global de refonte des
  contrats ne démontre pas un successeur unique et sûr pour chaque pont.
- Les candidats de renommage restent tous commentés. Les nouveaux candidats
  portent `# non : candidat heuristique nouveau, identité sémantique non
  démontrée`; les décisions historiques `# oui`/`# non` ont été conservées.

## Benchmark OCA 17.0 → 20.0

Le même `git archive` de huit modules provenant de `sale-workflow`,
`purchase-workflow`, `partner-contact` et `stock-logistics-workflow` a été migré
avant et après. Sept rapports sont identiques. Pour
`product_cost_price_avco_sync`, les TODO passent de 37 à 7, tandis que les cinq
erreurs restent identiques : 30 diagnostics de champs de
`stock.valuation.layer` disparaissent parce que le modèle lui-même est supprimé,
et seraient donc redondants. Un premier essai avait ajouté à tort un diagnostic
de dépendance OCA ; il a permis d'identifier puis de corriger la source
OpenUpgrade et n'apparaît plus dans le résultat final.

Le benchmark est statique (`--skip-install`) : 0/0 installation tentée. L'étape
`upgrade_code` ne peut pas être exécutée dans l'environnement partagé car le
module Python `babel` y manque ; export, migration et contrôles statiques sont
néanmoins terminés avec code retour 0.

## Validation

- Audit final : 0 erreur et 591 avertissements. Les avertissements restants sont
  529 `missing_target` dus au contrôle limité aux deux chemins demandés, plus 54
  conflits historiques antérieurs à 16.0, un step orphelin historique et trois
  règles curated anciennes non justifiées. Aucun conflit 16→20 n'est laissé par
  les successeurs ajoutés.
- La baseline change uniquement pour les quatre étapes touchées. Les compteurs
  `tools_import_error_patterns` passent de 1278 à 1290, 430 à 442, 1149 à 1166
  et 1243 à 1253, conformément aux méthodes supprimées ajoutées.
- Pytest : 920 tests passés, 1 ignoré, 6 `SyntaxWarning` historiques.
- Ruff sur tous les chemins demandés signale 197 défauts historiques, exactement
  comme le worktree témoin à `09b6c04`. Ruff ciblé sur chaque fichier Python
  ajouté ou modifié : zéro défaut.

## Garanties

Les fichiers generated ont été produits par les extracteurs, jamais édités à la
main. Les candidates sont entièrement commentées. Aucun push n'a été effectué.
`D:\Odoo\local-addons\Stof\stof`, le worktree principal et
`PROBLEMES_RENCONTRES.md` n'ont pas été modifiés ni inclus dans un commit.
