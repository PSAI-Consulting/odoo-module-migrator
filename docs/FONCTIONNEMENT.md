# Fonctionnement — odoo-module-migrator

Ce document explique comment l'outil migre un module, comment les règles
sont organisées et comment en ajouter une.

## Principes

1. **Aucune règle devinée.** Chaque règle cite sa source : commit Odoo
   (`odoo <sha> '<titre>'`), fichier d'une branche, ou OpenUpgrade. Ce qui ne
   peut pas être prouvé reste un avertissement, jamais une réécriture.
2. **Zéro faux positif.** Un champ n'est renommé ou signalé que là où son
   modèle est certain (analyse Python et XML, pas une recherche de texte).
3. **Idempotence.** Relancer sur un module déjà migré ne change rien.
4. **Rien de propre à un client.** Les modules des clients servent de bancs
   d'essai ; les règles ne viennent que d'Odoo.
5. **Format conservé.** Encodage, BOM et fins de ligne de chaque fichier sont
   préservés.

## Déroulement d'une migration

Pour chaque module, et pour chaque saut de version (`17.0 → 18.0`, puis
`18.0 → 19.0`…) :

1. **Règles du saut** (`migration_scripts/`) : renommages de fichiers,
   remplacements de texte, dépendances du manifest, scripts Python, puis
   champs et modèles selon leur modèle.
2. **Scripts officiels d'Odoo** (`odoo/upgrade_code`, avec `--odoo-root`) :
   lancés par le Python de l'Odoo cible ; ils n'écrivent que dans les
   modules migrés.
3. **Vérifications contre l'Odoo cible** (avec `--odoo-root`) : ancres des
   vues héritées, XML ids, modèles, chemins `@api.depends` / `related=`,
   imports `odoo.addons.*`.
4. **Rapport** `MIGRATION_REPORT.md` : TODO (`fichier:ligne`), transformations,
   fichiers modifiés.

Une étape qui échoue est journalisée et n'arrête pas les suivantes.

## Organisation du code

```
odoo_module_migrate/
├── __main__.py            ligne de commande
├── migration.py           enchaînement des modules et des étapes
├── module_migration.py    migration d'un module
├── base_migration_script.py   chargement et application des règles
├── manifest.py            lecture / réécriture du manifest (AST)
├── report.py              rapport par module et récapitulatif
├── tools.py               lecture / écriture des fichiers (format conservé)
├── analysis/              où un champ, une vue, un modèle, un import est utilisé
├── upgrade_code/          scripts officiels d'Odoo (runner + préparation)
└── migration_scripts/     les règles (voir ci-dessous)
```

## Les règles

Elles sont rangées **par type, puis par saut** :
`migration_scripts/<type>/migrate_<de>_<vers>/*.yaml`
(ex. `renamed_fields/migrate_190_200/curated.yaml`).
Le dossier `migrate_allways` s'applique à toutes les migrations.

| Type | Format d'une règle | Effet |
|---|---|---|
| `deprecated_modules` | `[module, removed\|renamed\|merged, nouveau]` | réécrit ou signale les `depends` |
| `renamed_fields` | `[modèle, ancien, nouveau, source]` | renomme là où le modèle est certain |
| `removed_fields` | `[modèle, champ, "remplaçant — source"]` | signale ; retire l'affichage `<field/>` des vues du modèle |
| `renamed_models` | `[ancien, nouveau, source]` | renomme le modèle |
| `removed_models` | `[modèle, "message — source"]` | signale |
| `text_replaces` | `{extension: {regex: remplacement}}` | remplace (seulement si l'équivalence est prouvée) |
| `text_errors` | `{extension: {regex: message}}` | signale une erreur 🔴 |
| `text_warnings` | `{extension: {regex: message}}` | signale un point à vérifier 🟠 |

Exemple :

```yaml
# renamed_fields/migrate_190_200/curated.yaml
- ["res.partner.bank", "acc_number", "account_number", "odoo 113d77eb35aa '[IMP] *: Improve UX of bank accounts'"]
```

### Trois fichiers par dossier

| Fichier | Origine | Règle |
|---|---|---|
| `generated.yaml` | produit par `tools/extract/extract_changes.py` | **ne pas éditer à la main** |
| `curated.yaml` | vérifié à la main | prioritaire : chargé avant, la première règle d'un champ l'emporte |
| `candidates.yaml` | candidats **commentés**, à relire | jamais appliqués |

Pour **annuler** un renommage de `generated.yaml` (ex. une colonne renommée
par OpenUpgrade alors que le champ existe toujours), écrire dans
`curated.yaml` le même nom en ancien et en nouveau, ou `null` :

```yaml
- ["stock.move", "location_dest_id", null, "toujours défini en 18.0"]
```

### Scripts Python

Pour ce qu'une regex ne fait pas sûrement :
`migration_scripts/python_scripts/migrate_<de>_<vers>/<nom>.py`.
**Toute fonction publique** (sans `_` au début) du fichier est exécutée, avec
les arguments nommés `logger`, `module_path`, `module_name`,
`manifest_path`, `migration_steps`, `tools`.

```python
def convert_something(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        new = text.replace("old_api(", "new_api(")
        if new != text:
            tools._write_content(path, new)
            logger.info("old_api replaced by new_api (odoo <sha>) in %s" % path)
```

Utilisez toujours `tools._read_content` / `tools._write_content` (format
conservé). Ce qui ne peut pas être converti sûrement est signalé avec
`logger.warning("... File %s:%s" % (path, line))` : la ligne apparaît dans
le rapport.

## Ajouter une règle

1. **Prouver** le changement dans le code d'Odoo :
   `git log -S<nom> 19.0..20.0`, `git show <sha>`, vérifier l'état dans la
   branche cible.
2. **Choisir le type** : renommage sûr → `renamed_*` ou `text_replaces` ;
   suppression → `removed_*` (avec le remplaçant) ; doute → `text_warnings`.
3. **L'écrire** dans le `curated.yaml` (ou un YAML thématique) du bon saut,
   avec la source.
4. **Tester** dans `tests/` : entrée, sortie attendue, second passage sans
   effet. Les fichiers YAML sont validés automatiquement
   (`tests/test_rules_yaml.py`).
5. **Lancer** `python -m pytest -q tests`.

## Pour une nouvelle version d'Odoo (21.0…)

1. Ajouter la version dans `odoo_module_migrate/config.py`.
2. Régénérer les données avec `tools/extract/extract_changes.py` (une
   sous-commande par type, voir [COMMANDES.md](COMMANDES.md#6-outils-de-mainteneur)).
3. Relire les `candidates.yaml`, compléter les `curated.yaml`.
4. Valider sur un banc (`tools/bench/bench.py`) : migration puis installation
   réelle sur une base Odoo vierge.
