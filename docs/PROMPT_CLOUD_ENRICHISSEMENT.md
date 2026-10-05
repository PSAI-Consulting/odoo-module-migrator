# Prompt — Enrichir et fiabiliser les règles d'`odoo-module-migrator` (session cloud)

> À coller dans une session Claude Code cloud ouverte sur le dépôt
> `PSAI-Consulting/odoo-module-migrator`, branche **`improve-migrator`**.
> Rédigé le 05/10/2026 : vérifie les faits ci-dessous, ils datent de ce jour.

## Rôle et objectif

Tu es un développeur Odoo senior. `odoo-module-migrator` réécrit le **code source**
de modules Odoo custom d'une version vers une autre : on lui donne un module, la
version de départ et la version cible, et il applique des règles (YAML + fonctions
Python) et les scripts officiels `odoo/upgrade_code` d'Odoo. Ce qu'il ne peut pas
faire sûrement, il le **signale** avec `fichier:ligne` dans un rapport.

**Ta mission dans cette session : enrichir et vérifier la base de connaissances
(les « fiches » de règles) pour 17.0 → 18.0 → 19.0 → 20.0**, priorité absolue
(migration d'un client de 17 vers 20). Les sauts 8 → 17 viendront dans une autre
session : n'y touche pas.

## Règles impératives

1. **Ne jamais inventer une règle.** Chaque règle porte sa source : commit Odoo
   (`odoo <sha> '<titre>'`), fichier et branche, ou fichier OpenUpgrade. Si tu
   ne peux pas le prouver dans le code d'Odoo, la règle va en **avertissement**
   (`text_warnings`) ou reste **candidate** (commentée), jamais en
   transformation automatique.
2. **Zéro faux positif.** Un avertissement qui se déclenche à tort fait perdre
   confiance dans l'outil. Les champs sont traités selon le **modèle**
   (`odoo_module_migrate/analysis/fields.py`), pas par regex globale.
3. **Idempotence** : relancer la migration sur un module déjà migré ne change rien.
4. Toute transformation a un **test** (entrée, sortie attendue, second passage
   sans effet) dans `tests/`.
5. `generated.yaml` est produit par l'outil et **ne s'édite pas à la main**. Les
   corrections et ajouts vérifiés vont dans **`curated.yaml`** (même dossier,
   prioritaire : chargé avant, la première règle d'un champ l'emporte).
   `candidates.yaml` contient des candidats **commentés**, à relire.
6. Petits commits clairs en français, sur une branche **`enrich-rules`** créée
   depuis `improve-migrator`. Pousse cette branche, **ne touche ni à `master` ni
   à `improve-migrator`**, ne merge rien : l'utilisateur relira.
7. Ne commite jamais les dépôts clonés ni de fichiers de travail (ils restent hors
   du dépôt, par exemple dans `/tmp/odoo-src`).

## Vérifie tout toi-même

Ne crois ni ce prompt, ni les fichiers existants, ni ta mémoire : **chaque règle
que tu ajoutes, modifies ou valides doit être vérifiée par toi**, et la preuve
citée dans la règle. Sources, par ordre de confiance :

1. **Le code d'Odoo** (preuve obligatoire) : dépôts git clonés ci-dessous,
   `git show <sha>`, `git log -S<nom> 19.0..20.0`, `git grep` dans la branche
   cible, lecture du fichier avant/après. Une règle sans preuve dans le code ne
   devient jamais une transformation automatique.
2. **OpenUpgrade** (`OCA/OpenUpgrade`, branches 18.0, 19.0, 20.0) :
   `openupgrade_scripts/apriori.py`, `scripts/*/pre-migration.py`
   (`_renamed_fields`, `_renamed_models`), `upgrade_analysis.txt`.
3. **Internet**, pour comprendre et recouper (jamais seule source) :
   - wikis OCA : https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-18.0
     (et `…-19.0`, `…-20.0` s'il existe) ;
   - changelog ORM officiel : dépôt `odoo/documentation`, branches 18.0 / 19.0 /
     20.0, `content/developer/reference/backend/orm/changelog.rst` ;
   - `odoo/upgrade-util` (fonctions `rename_field`, `rename_model`… utilisées par
     les scripts d'upgrade d'Odoo) ;
   - les pull requests OCA « [18.0][MIG] », « [19.0][MIG] », « [20.0][MIG] » : des
     migrations faites à la main, donc des exemples réels de ce qui change ;
   - les pull requests odoo/odoo citées dans les commits (`closes odoo/odoo#…`).
4. Si une information ne se recoupe pas, ou si tu as un doute : avertissement
   (« à vérifier ») ou candidat commenté avec la raison, jamais une règle sûre.

## Ce qui existe déjà (lis-le avant de commencer)

- `odoo_module_migrate/migration_scripts/<type>/migrate_XXX_YYY/*.yaml` : les
  règles, par type et par saut de version :
  - `deprecated_modules` : `[ancien, removed|renamed|merged, nouveau]` → réécriture
    des `depends` du manifest (`manifest.py`, par l'AST) ;
  - `renamed_fields` : `[modèle, ancien, nouveau, source]` → renommés là où le
    modèle est certain (XML : records, vues, xpath ; Python : classe
    `_name`/`_inherit`, `self.x`, `@api.depends`, `related=`, write/create/search) ;
  - `removed_fields` : `[modèle, champ, source]` → signalés (et l'affichage
    `<field name="x"/>` retiré des vues du modèle) ;
  - `renamed_models` / `removed_models` ; `text_replaces` / `text_errors` /
    `text_warnings` : regex par extension (`.py`, `.xml`, `.js`…).
- `odoo_module_migrate/migration_scripts/python_scripts/migrate_XXX_YYY/*.py` :
  transformations Python (toute fonction **publique** du fichier est exécutée).
- `tools/extract_changes.py` : régénère les données depuis les sources Odoo :
  `modules`, `fields`, `api` (lis sa docstring et celle de `tools/extract_fields.py`,
  `tools/extract_api.py`).
- `odoo_module_migrate/upgrade_code/` : orchestration des scripts officiels
  `odoo/upgrade_code` (ir.access, OWL 3, t-call, contraintes SQL…). Ne réécris
  pas ce qu'Odoo fournit déjà.
- État des données (05/10/2026) : 17→18, 18→19 : champs/modèles depuis
  OpenUpgrade (renommages = `_renamed_fields` des `pre-migration.py`, recoupés
  avec les sources). 19→20 : OpenUpgrade 20.0 est vide, données extraites des
  sources : 1131 champs supprimés vérifiés (héritage/mixins inclus), 4 renommages
  confirmés + 3 dans `curated.yaml`, **213 candidats à relire**.

## Préparer les sources (hors du dépôt)

```bash
mkdir -p /tmp/odoo-src && cd /tmp/odoo-src
# Odoo community : branches utiles, historique depuis fin 2023 (git log -S)
git init --bare odoo.git
git -C odoo.git fetch --shallow-since=2023-09-01 https://github.com/odoo/odoo.git \
    17.0:17.0 18.0:18.0 19.0:19.0 20.0:20.0 \
    saas-17.2:saas-17.2 saas-17.4:saas-17.4 saas-18.1:saas-18.1 saas-18.2:saas-18.2 \
    saas-18.3:saas-18.3 saas-18.4:saas-18.4 saas-19.1:saas-19.1 saas-19.2:saas-19.2 \
    saas-19.3:saas-19.3 saas-19.4:saas-19.4
git clone https://github.com/OCA/OpenUpgrade.git && git -C OpenUpgrade fetch origin 18.0 19.0 20.0
# Exemples réels de migrations manuelles : quelques dépôts OCA
for r in sale-workflow purchase-workflow stock-logistics-workflow partner-contact \
         account-invoicing server-ux web l10n-france; do
  git clone --filter=blob:none --no-checkout https://github.com/OCA/$r.git
done
```

`odoo/enterprise` est **privé** : sans accès, travaille sur Community seulement et
**ne régénère pas** les fichiers `generated.yaml` qui contiennent des données
Enterprise (tu les appauvrirais) : ajoute plutôt dans `curated.yaml`.

Environnement : Python ≥ 3.11, `python -m venv .venv && .venv/bin/pip install -e .
pytest ruff libcst`. Tests : `.venv/bin/python -m pytest -q tests`.

## Travail demandé (par ordre de valeur)

### 1. Les 213 candidats au renommage 19.0 → 20.0
Fichier `renamed_fields/migrate_190_200/candidates.yaml`. Pour chacun : `git show
<sha>` du commit cité, et vérifie dans `20.0` que le nouveau champ a le **même sens**
(même type, même comodel, même usage, l'ancien n'est plus utilisé).
- Vrai renommage → ligne dans `renamed_fields/migrate_190_200/curated.yaml` avec la
  source (et un commentaire si utile).
- Pas un renommage → laisse-le en candidat, en ajoutant `# non : <raison>`.
Commence par les modèles courants : `res.partner`, `res.users`, `res.company`,
`product.*`, `sale.*`, `purchase.*`, `stock.*`, `account.*`, `mrp.*`, `hr.employee`,
`project.*`, `uom.uom`.

### 2. Renommages Enterprise et hors OpenUpgrade en 17→18 et 18→19
OpenUpgrade ne couvre pas tout (Enterprise, champs sans migration de données).
Ajoute à `tools/extract_changes.py fields` une option `--sources` qui force la
comparaison des sources même quand OpenUpgrade a des données, et fusionne les
résultats (sans doublon). Relis les candidats obtenus comme au point 1.

### 3. Champs supprimés : indiquer le remplaçant
Pour les champs supprimés des modèles courants (liste du point 1) en 17→18, 18→19
et 19→20, regarde le commit : si un remplaçant est clair (ex. `stock.move.group_id`
→ `reference_ids`, `product.packaging` → unités de mesure, `res.partner.mobile` →
`phone`), ajoute une ligne `[modèle, champ, "<remplaçant> — <source>"]` dans
`removed_fields/migrate_XXX_YYY/curated.yaml` : le message du rapport devient
actionnable. Ne renomme pas automatiquement si la sémantique change.

### 4. Modules 17→18, 18→19, 19→20
Relis `deprecated_modules/migrate_*/modules.yaml` : les entrées `removed` dont le
commit montre une fusion ou un renommage (ex. `website_sale_comparison_wishlist`)
→ corrige dans `curated.yaml`. Vérifie aussi les modules OCA renommés en 19/20
(compare les dossiers des branches 18.0/19.0/20.0 des dépôts OCA clonés).

### 5. Modèles renommés / supprimés 19→20
OpenUpgrade 20.0 étant vide, compare les `_name` entre `19.0` et `20.0`
(`tools/extract_fields.py` a déjà le parseur) : ajoute une sous-commande ou une
option pour produire `renamed_models` / `removed_models` 19→20 (sources : commits).
Déjà connus : `ir.model.access` et `ir.rule` → `ir.access` ; `mail.tracking.value`
déplacé dans le module `mail_tracking` (pas supprimé) ; `res.bank` supprimé
(odoo 113d77eb35aa).

### 6. API Python, JS et vues
- `tools/extract_changes.py api` (méthodes de `BaseModel`, fonctions de
  `odoo.tools`/`api`/`fields`/`http`, modules Python disparus, messages
  `warnings.warn(...deprecated...)`) : relis les candidats 17→18, 18→19, 19→20 et
  complète `text_errors` / `text_warnings` / `text_replaces` (`core_api.yaml`).
  Un remplacement automatique seulement si l'équivalence est exacte et prouvée
  (ex. Odoo fait lui-même `attrs['aggregator'] = attrs.pop('group_operator')`).
- **JS** : ajoute une sous-commande `js` qui liste les modules JS
  (`@web/...`, `@mail/...`, fichiers `static/src/**/*.js`) présents en N et absents
  en N+1, et retrouve leur nouvel emplacement (même nom de fichier ailleurs) →
  règles `text_errors` / `text_replaces` `.js` pour les imports. OWL 3 (20.0) est
  déjà traité par le script officiel `owl3-migration.py` : ne le refais pas.
- **Vues** : ajoute une sous-commande `views` qui liste les `ir.ui.view` (xmlid)
  supprimés ou renommés entre deux branches → `text_errors` `.xml` sur
  `inherit_id ref="module.vue"` (complète la vérification des ancres, qui ne
  marche qu'avec `--odoo-root`).

### 7. (si le temps le permet) Vérité terrain OCA
Prends des modules OCA présents en 17.0 et 18.0 (dépôts clonés), lance le migrator
17.0 → 18.0 sur la version 17.0, compare avec la version 18.0 faite à la main par
l'OCA (taux de lignes identiques, écarts), et déduis les règles manquantes (en
respectant la règle 1). Fournis un petit script `tools/ground_truth.py` et un
tableau de résultats.

## Livrables et fin de session

- Commits sur `enrich-rules`, poussée ; tests verts (`pytest -q tests`).
- Un fichier `docs/ENRICHISSEMENT_<date>.md` qui résume : règles ajoutées par type
  et par saut (avec comptes), candidats rejetés et pourquoi, limites, ce qui
  reste à faire.
- Ne lance pas d'installation Odoo réelle : elle se fait sur le poste de
  l'utilisateur (`tools/bench.py`).
