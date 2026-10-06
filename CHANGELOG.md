# Historique des versions

## 0.6.0 — octobre 2026

Refonte du fork pour en faire l'outil de référence de migration du code
source de modules Odoo, de 8.0 à 20.0 (priorité 17.0 → 20.0).

### Moteur
- Lecture / écriture des fichiers sans changer l'encodage, le BOM ni les fins
  de ligne ; écritures atomiques.
- `--dry-run` : prévisualisation sous forme de diff, sans rien écrire.
- Rapport par module `MIGRATION_REPORT.md` (risque, TODO `fichier:ligne`,
  transformations, fichiers modifiés) ou `--report-dir`.
- Scripts officiels d'Odoo (`odoo/upgrade_code`) lancés avec `--odoo-root` /
  `--odoo-python`, en n'écrivant que dans les modules migrés.
- Une étape en échec n'arrête plus la migration.
- `installable` laissé tel quel par défaut (`--set-installable` pour le forcer).
- Version du manifest : `X.0` / `X.0.a.b.c` → `<cible>.1.0.0`.
- `--version`.

### Analyse (zéro faux positif)
- Champs renommés / supprimés traités selon leur modèle (Python et XML,
  sous-vues x2many, héritage par délégation `_inherits`).
- Avec `--odoo-root` : ancres des vues héritées, XML ids, modèles, chemins
  `@api.depends` / `related=`, imports `odoo.addons.*` vérifiés contre
  l'Odoo cible ; dépendance manquante dans `depends` nommée.

### Règles
- 17.0 → 20.0 : modules, champs, modèles, vues, modules JS, API Python
  extraits des sources Odoo / Enterprise et d'OpenUpgrade, chacun avec sa
  source ; transformations dédiées (`ir.access`, `res.groups.privilege`,
  `odoo.registry` → `Registry`, imports `odoo.tools` déplacés,
  `report_file`, `slugify`, `is_storable`…).
- 8.0 → 17.0 : règles vérifiées et sourcées, conversion `attrs` / `states`
  réécrite, anciennes règles non prouvées retirées.
- Règles destructrices ou non prouvées de l'amont retirées.

### Outils de mainteneur (`tools/`)
- `extract/extract_changes.py` : régénération des règles par sous-commande.
- `bench/bench.py` : bancs d'essai avec installation réelle sur Odoo, boucle
  rapide `--retry-failed`.

## 0.5.x

Versions de l'outil amont
[OCA/odoo-module-migrator](https://github.com/OCA/odoo-module-migrator).
