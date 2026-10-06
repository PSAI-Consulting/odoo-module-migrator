# Prompt — Règles de migration 8.0 → 17.0 d'`odoo-module-migrator` (session cloud)

> À coller dans une session Claude Code cloud ouverte sur le dépôt
> `PSAI-Consulting/odoo-module-migrator`, branche de départ **`improve-migrator`**.
> Rédigé le 06/10/2026 : vérifie les faits ci-dessous, ils datent de ce jour.

## Rôle et objectif

Tu es un développeur Odoo senior qui connaît l'histoire du framework depuis
OpenERP 8. `odoo-module-migrator` réécrit le **code source** de modules Odoo
custom d'une version vers une autre : on lui donne un module, la version de
départ et la version cible, et il enchaîne les sauts (`8.0 → 9.0 → … → 20.0`)
en appliquant pour chacun des règles (YAML + fonctions Python). Ce qu'il ne peut
pas faire sûrement, il le **signale** avec `fichier:ligne` dans un rapport
(`MIGRATION_REPORT.md`).

Les sauts **17.0 → 18.0 → 19.0 → 20.0 sont faits** (session précédente, voir
`docs/ENRICHISSEMENT_2026-10-05.md`) et validés par installation réelle de
modules OCA et clients sur Odoo 20.

**Ta mission : construire et vérifier la base de connaissances des sauts
8.0 → 9.0, 9.0 → 10.0, 10.0 → 11.0, 11.0 → 12.0, 12.0 → 13.0, 13.0 → 14.0,
14.0 → 15.0, 15.0 → 16.0 et 16.0 → 17.0**, avec le même niveau d'exigence que
17 → 20, pour qu'un module 8.0 à 16.0 arrive en 20.0 en un seul passage.

**Ordre de priorité** (les clients sont surtout en 12 à 16) :
16→17, 15→16, 14→15, 13→14, 12→13, puis 11→12, 10→11, 9→10, 8→9.
Termine proprement un saut (données, règles, tests, vérité terrain) avant de
passer au suivant : mieux vaut 5 sauts solides que 9 bâclés.

## Règles impératives

1. **Ne jamais inventer une règle.** Chaque règle porte sa source : commit Odoo
   (`odoo <sha> '<titre>'`), fichier + branche, ou fichier OpenUpgrade. Ce que
   tu ne peux pas prouver dans le code d'Odoo va en **avertissement**
   (`text_warnings`) ou reste **candidat commenté**, jamais en transformation
   automatique. Ta mémoire d'Odoo est une piste à vérifier, pas une preuve.
2. **Zéro faux positif.** Un avertissement qui se déclenche à tort fait perdre
   confiance dans l'outil. Les champs se traitent selon le **modèle**
   (`odoo_module_migrate/analysis/fields.py`), pas par regex globale. Une regex
   de `text_errors`/`text_warnings` doit être assez précise pour ne pas toucher
   du code déjà migré.
3. **Idempotence** : relancer la migration sur un module déjà migré ne change
   rien (et ne signale rien de nouveau).
4. Toute transformation a un **test** dans `tests/` : entrée, sortie attendue,
   second passage sans effet.
5. `generated.yaml` est produit par l'outil et **ne s'édite pas à la main**. Les
   corrections et ajouts vérifiés vont dans **`curated.yaml`** (même dossier,
   chargé avant : la première règle d'un champ ou d'un modèle l'emporte).
   `candidates.yaml` contient des candidats **commentés**, annotés
   `# oui : curated.yaml` ou `# non : <raison>` une fois relus.
6. **Ne casse pas 17 → 20.** Ne modifie les règles `migrate_170_180`,
   `migrate_180_190`, `migrate_190_200` et le moteur commun que pour corriger un
   bug prouvé par un test, et signale-le dans ta synthèse.
7. Petits commits clairs **en français** (`[ADD]`, `[IMP]`, `[FIX]`, `[DOC]`),
   sur une branche **`enrich-rules-8-16`** créée depuis `improve-migrator`.
   Pousse-la régulièrement. **Ne touche ni à `master` ni à `improve-migrator`**,
   ne merge rien : l'utilisateur relira et fusionnera. Si tu ne peux pas créer
   de branche, dis-le immédiatement dans ta réponse au lieu de pousser ailleurs.
8. Ne commite jamais les dépôts clonés ni des fichiers de travail (reste dans
   `/tmp/odoo-src`).
9. Garde la suite de tests **rapide** (< 1 min idéalement) : pas de test qui
   charge tous les YAML de tous les sauts plusieurs fois sans raison.

## Vérifie tout toi-même

Ne crois ni ce prompt, ni les fichiers existants, ni ta mémoire : **chaque règle
que tu ajoutes, modifies ou valides doit être vérifiée par toi**, preuve citée
dans la règle. Sources, par ordre de confiance :

1. **Le code d'Odoo** (preuve obligatoire) : `git show <sha>`,
   `git log -S<nom> 13.0..14.0`, `git grep` dans la branche cible, lecture du
   fichier avant/après. Attention : entre deux branches stables anciennes,
   `git log A..B` contient aussi des forward-ports ; vérifie toujours l'état
   final (présent en A, absent en B).
2. **OpenUpgrade** (`OCA/OpenUpgrade`, branches 9.0 → 17.0) : c'est la source
   principale des renommages de champs et de modèles (ils écrivent les scripts
   de migration des données). Attention, la structure du dépôt change :
   - 14.0 et après : `openupgrade_scripts/apriori.py`,
     `openupgrade_scripts/scripts/<module>/<version>/pre-migration.py`
     (`_field_renames`, `_model_renames`…), `upgrade_analysis.txt` ;
   - 13.0 et avant : OpenUpgrade est un **fork complet d'Odoo** ;
     `apriori.py` et les analyses sont ailleurs (cherche
     `openupgrade_records`, `addons/*/migrations/<version>/openupgrade_analysis.txt`,
     `openerp/openupgrade` / `odoo/openupgrade`). Trouve la structure toi-même
     pour chaque branche et adapte l'extracteur.
3. **Internet**, pour comprendre et recouper (jamais seule source) :
   - wikis OCA `https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-<N>.0`
     pour N = 9 à 17 : la liste des tâches que l'OCA applique à chaque
     migration, très précieuse ;
   - changelog ORM officiel : dépôt `odoo/documentation`, branches 12.0 → 17.0,
     `content/developer/reference/backend/orm/changelog.rst` (ou
     `reference/orm.rst` selon les versions) ;
   - `odoo/upgrade-util` ;
   - les pull requests OCA « [N.0][MIG] » : des migrations faites à la main ;
   - les PR odoo/odoo citées dans les commits.
4. Si une information ne se recoupe pas : avertissement ou candidat commenté
   avec la raison, jamais une règle sûre.

## Ce qui existe déjà (lis-le avant de commencer)

- **Moteur** (`odoo_module_migrate/`) : `migration.py` (enchaînement des
  sauts, rapport), `base_migration_script.py` (chargement des règles,
  `handle_fields`), `analysis/fields.py` (usages d'un champ selon le modèle :
  Python AST + XML lxml, sous-vues x2many quand le comodel est connu,
  héritage par délégation `_inherits`), `analysis/views.py` et
  `analysis/models.py` (vérification des ancres de vues et des modèles contre
  les sources cibles, avec `--odoo-root`), `manifest.py` (réécriture des
  `depends` par l'AST), `report.py`, `tools.py` (E/S qui préservent encodage,
  BOM et fins de ligne).
- **Règles** `odoo_module_migrate/migration_scripts/<type>/migrate_XXX_YYY/*.yaml`
  - `deprecated_modules` : `[ancien, removed|renamed|merged, nouveau]` ;
  - `renamed_fields` : `[modèle, ancien, nouveau, source]` ;
  - `removed_fields` : `[modèle, champ, "remplaçant éventuel — source"]` ;
  - `renamed_models` / `removed_models` ;
  - `text_replaces` / `text_errors` / `text_warnings` : regex par extension.
- **Scripts Python par saut** : `migration_scripts/migrate_XXX_YYY.py` (classe
  `MigrationScript`, fonctions globales) et
  `migration_scripts/python_scripts/migrate_XXX_YYY/*.py` (toute fonction
  **publique** est exécutée ; voir `migrate_180_190/xml_eval_idref.py` comme
  modèle : docstring avec la source, transformation sûre, idempotente).
- **État des sauts 8 → 17 aujourd'hui** : hérité du dépôt OCA amont, **non
  vérifié** et très incomplet :
  - `migrate_080_090.py` … `migrate_150_160.py` : quelques fonctions chacun ;
    `migrate_160_170.py` (525 lignes) : conversion `attrs`/`states` → attributs
    Python (17.0), écrite par l'OCA, relativement fiable ;
  - YAML : quelques règles par saut (`account.invoice` → `account.move` en
    12→13, décorateurs, `digits_precision`…), `generated.yaml` 16→17 (champs et
    modèles depuis OpenUpgrade 17.0) ;
  - rien pour `deprecated_modules` entre 9.0 et 17.0.
  Relis tout ce qui existe : vérifie, source, corrige ou supprime (un
  `[FIX]`/`[REM]` par sujet, avec la raison).
- **Outils** (`tools/`, hors paquet) : `extract_changes.py` (sous-commandes
  `modules`, `fields` [`--sources`], `models`, `api`, `js`, `views`),
  `extract_fields.py`, `extract_api.py`, `extract_assets.py`,
  `ground_truth.py` (migre des modules OCA et compare avec la version faite à
  la main), `check_modules.py`. Lis leurs docstrings. Ils ont été écrits pour
  17 → 20 : adapte-les aux anciennes versions sans casser l'existant
  (tests `tests/test_extract_tools.py`).
- **Scripts officiels `odoo/upgrade_code`** : orchestrés par
  `odoo_module_migrate/upgrade_code/` pour 17+ seulement. Vérifie dans quelle
  branche ce dossier apparaît ; avant, il n'y a pas d'outil officiel : tout
  repose sur nos règles.

## Particularités des anciennes versions (pistes à VÉRIFIER, pas des faits)

À prouver dans le code avant d'en faire une règle :

- **8.0 → 10.0** : `__openerp__.py` → `__manifest__.py`, espace de noms
  `openerp` → `odoo` (imports, `openerp.addons.x`, `<openerp>` → `<odoo>` en
  XML), ancienne API (`cr, uid, ids, context`, `osv.osv`, `fields.function`,
  `_columns`) → nouvelle API. La conversion de l'ancienne API n'est pas
  mécanique : signale-la précisément plutôt que de la réécrire.
- **10.0 → 11.0** : passage à **Python 3**. Repère ce qui est sûr à
  réécrire (`print` instruction, `except X, e`, `dict.iteritems()`, `unicode`,
  `basestring`, `urllib2`…) ; l'usage d'un outil externe (pyupgrade, etc.)
  n'est acceptable que s'il est optionnel, documenté, et que le résultat est
  testé. Sinon : erreurs signalées.
- **11.0 → 12.0 / 12.0 → 13.0** : `@api.multi`, `@api.one`, `@api.returns`,
  `@api.cr`… ; `sudo(user)` → `with_user` ; `track_visibility` → `tracking` ;
  `account.invoice` → `account.move` (gros changement : les règles existantes
  ne couvrent qu'une partie) ; `ir.actions.report.xml`…
- **13.0 → 14.0 / 14.0 → 15.0** : assets déclarés dans le manifest
  (`'assets': {...}`) au lieu des templates XML `assets_backend` ;
  `odoo.define` → modules ES ; `_compute_*` sans `@api.depends`…
- **15.0 → 16.0 / 16.0 → 17.0** : `attrs` / `states` (déjà traité en 16→17 :
  vérifie et teste), `name_get` → `_compute_display_name`, `<tree>` reste
  `<tree>` jusqu'en 17, OWL 1 → OWL 2, `fields_view_get` → `get_views`…
- **À chaque saut** : modules renommés/fusionnés/supprimés (core + Enterprise
  si tu y as accès, + modules OCA renommés), champs et modèles renommés ou
  supprimés, vues supprimées (héritages cassés), API Python/JS retirées,
  changements des fichiers de données (`noupdate`, `ir.cron`, `ir.ui.menu`…).

## Préparer les sources (hors du dépôt)

```bash
mkdir -p /tmp/odoo-src && cd /tmp/odoo-src
# Odoo community : clone partiel (blobs à la demande), branches 8.0 → 17.0
git clone --bare --filter=blob:none https://github.com/odoo/odoo.git odoo.git
git -C odoo.git fetch origin '+refs/heads/[0-9]*.0:refs/heads/[0-9]*.0'
# (ajoute saas-* si un changement doit être daté précisément)
git clone https://github.com/OCA/OpenUpgrade.git
# Exemples réels de migrations manuelles : dépôts OCA (toutes branches)
for r in sale-workflow purchase-workflow stock-logistics-workflow partner-contact \
         account-invoicing server-ux server-tools web l10n-france product-attribute; do
  git clone --filter=blob:none --no-checkout https://github.com/OCA/$r.git
done
```

`odoo/enterprise` est **privé**. La session précédente avait accès à un fork
privé `LBruyere/enterprise` : essaie-le ; sinon travaille sur Community
seulement et **ne régénère pas** un `generated.yaml` qui contient des données
Enterprise (tu l'appauvrirais) — ajoute dans `curated.yaml`.

Environnement : Python ≥ 3.11 (`python -m venv .venv && .venv/bin/pip install
-e . pytest ruff`). Tests : `.venv/bin/python -m pytest -q tests`.

## Travail demandé, pour chaque saut (dans l'ordre de priorité)

### 1. Données extraites et vérifiées
- `deprecated_modules/migrate_XXX_YYY/modules.yaml` (+ `curated.yaml`) :
  `extract_changes.py modules` + `apriori.py` d'OpenUpgrade (`renamed_modules`,
  `merged_modules`) + modules OCA renommés (compare les dossiers des branches
  des dépôts OCA clonés).
- `renamed_fields` / `removed_fields` / `renamed_models` / `removed_models` :
  `extract_changes.py fields` / `models` (OpenUpgrade + `--sources`). Relis les
  candidats ; pour les champs supprimés des modèles courants (`res.partner`,
  `res.users`, `res.company`, `product.*`, `sale.*`, `purchase.*`, `stock.*`,
  `account.*`, `mrp.*`, `hr.*`, `project.*`, `uom.uom`), cherche le commit et
  indique le **remplaçant** quand il est clair.
- Vues supprimées (`extract_changes.py views`) et modules JS supprimés/déplacés
  (`extract_changes.py js`, à partir de 14.0 / modules ES ; avant, signale
  `odoo.define` / `require` des modules disparus si c'est prouvable).
- API Python retirée (`extract_changes.py api`) → `core_api.yaml` des
  `text_replaces` (équivalence exacte prouvée seulement) / `text_errors` /
  `text_warnings`.

### 2. Transformations Python (`python_scripts/migrate_XXX_YYY/`)
Les changements structurels sûrs et fréquents qu'une regex ne fait pas bien :
décorateurs supprimés, manifest renommé, espace de noms `openerp`, assets
déplacés dans le manifest, etc. Une transformation n'est écrite que si elle
est **sûre et prouvée** ; sinon le cas est signalé avec `fichier:ligne`.
Chaque transformation : docstring avec la source, test, idempotence.

### 3. Vérité terrain OCA (`tools/ground_truth.py`)
Pour chaque saut, prends ~8 modules × 8 dépôts OCA présents dans les deux
branches, migre la version N avec l'outil et compare avec la version N+1 faite
à la main par l'OCA. Donne le taux de lignes identiques avant/après, classe
les écarts restants (refontes propres à l'OCA vs changements imposés par
Odoo) et **déduis les règles manquantes** (en respectant la règle 1).
Écris le résultat dans `docs/GROUND_TRUTH_OCA_<N>_<N+1>.md`.

### 4. Enchaînement
Vérifie qu'une migration longue fonctionne d'un bout à l'autre : par exemple
des modules OCA 12.0 migrés directement en 17.0 puis en 20.0, sans plantage,
avec un rapport lisible (les TODO d'un saut intermédiaire désormais sans objet
ne doivent pas polluer le rapport). Ajoute un test d'intégration léger.

## Livrables et fin de session

- Commits sur `enrich-rules-8-16`, poussée ; tests verts (`pytest -q tests`).
- `docs/ENRICHISSEMENT_8_16_<date>.md` : règles ajoutées/corrigées/supprimées
  par type et par saut (avec comptes), candidats rejetés et pourquoi, résultats
  de vérité terrain, limites, ce qui reste à faire.
- Ne lance pas d'installation Odoo réelle : elle se fait sur le poste de
  l'utilisateur (`tools/bench.py`, bases Odoo vierges).
