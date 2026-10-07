# odoo-module-migrator

Migre le **code source** de modules Odoo personnalisés d'une version à une
autre, de **8.0 à 20.0**, en une seule commande.

On lui donne un dossier de modules, la version de départ et la version
cible. Il enchaîne les sauts de version (`17.0 → 18.0 → 19.0 → 20.0`) et :

- **réécrit** ce qui peut l'être sûrement : champs et modèles renommés,
  dépendances de modules renommés ou fusionnés, imports déplacés, API
  remplacées, vues (`tree` → `list`, `attrs` → `invisible`…), sécurité
  (`ir.access` en 20.0), version du manifest… ;
- lance les **scripts officiels d'Odoo** (`odoo/upgrade_code`) intégrés pour
  les cibles 18, 19 et 20, ou ceux des sources cibles fournies ;
- **signale** tout le reste dans un rapport par module, avec `fichier:ligne`,
  la cause et le remplaçant quand il existe : ce qu'il faut corriger à la main.

Chaque règle provient du code d'Odoo (commit cité) ou d'OpenUpgrade : aucune
règle n'est devinée, et l'outil ne contient rien de propre à un client.

## Installation

Python 3.12 ou plus récent (requis par les scripts officiels intégrés).

```bash
git clone https://github.com/PSAI-Consulting/odoo-module-migrator.git
cd odoo-module-migrator
python -m venv .venv                 # Python 3.12+ ; Windows : py -3.12 -m venv .venv
.venv/Scripts/pip install -e .        # Windows  (Linux / macOS : .venv/bin/pip)
```

La commande `odoo-module-migrate` est alors disponible dans le venv.

## Démarrage rapide

Commande complète recommandée sous PowerShell :

```bash
.\.venv\Scripts\python.exe -m odoo_module_migrate `
    --directory "D:\Odoo\local-addons\Stof\stof" `
    --modules "stof_partner_backorder_strategy" `
    --init-version-name 17.0 `
    --target-version-name 20.0 `
    --default-website "https://www.easi-soft.fr" `
    --format `
    --report-dir "D:\Odoo\local-addons\Stof\migration-reports" `
    --no-commit `
    --no-pre-commit
```

Remplacez seulement le nom passé à `--modules`. Cette commande utilise les
sources Community et les scripts officiels embarqués, cherche les dépendances
custom dans le dossier donné à `--directory`, normalise le manifeste, retire
les imports inutilisés et écrit le rapport hors du module.

Pour prévisualiser exactement la même migration sans modifier les sources,
ajoutez `--dry-run`.

Exemple portable minimal :

```bash
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit
```

Déroulement conseillé :

```bash
# 1. Prévisualiser
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit --dry-run

# 2. Retirer --dry-run pour appliquer, puis lire MIGRATION_REPORT.md
```

Les scripts officiels et les références Odoo Community 18, 19 et 20 sont
embarqués et utilisés par défaut, sans serveur Odoo ni téléchargement au moment
de la migration. La première utilisation prépare un cache local.

`--odoo-root` permet de choisir d'autres sources cibles. `--addons-path` ajoute
notamment les sources Enterprise et `--context-path` les autres modules métier.
`--no-upgrade-code` limite l'exécution aux règles du migrateur.

Le modèle de manifeste et le nettoyage des imports inutilisés sont appliqués
par défaut aux modules hors OCA. `--format` ajoute le formatage Ruff du projet.
Options : `--default-website URL`, `--keep-unused-imports`, `--no-manifest-format`.

## Documentation

| Document | Contenu |
|---|---|
| [docs/COMMANDES.md](docs/COMMANDES.md) | Toutes les commandes et options, avec des exemples |
| [docs/FONCTIONNEMENT.md](docs/FONCTIONNEMENT.md) | Comment l'outil travaille, organisation des règles, ajouter une règle |
| [docs/CONTROLES_MIGRATION.md](docs/CONTROLES_MIGRATION.md) | Contrôles Python/XML, cache, formatage et limites de l'analyse |
| [tools/README.md](tools/README.md) | Outils de mainteneur : régénérer les règles, bancs d'essai sur Odoo |
| [CHANGELOG.md](CHANGELOG.md) | Historique des versions |

## Organisation du dépôt

```
odoo_module_migrate/          le paquet installé (la commande odoo-module-migrate)
├── migration_scripts/        les règles, par type et par saut de version
├── analysis/                 analyse des champs, vues, modèles, imports
└── upgrade_code/             orchestration des scripts officiels d'Odoo
tools/                        outils de mainteneur (non installés)
├── extract/                  régénérer les règles depuis les sources Odoo
└── bench/                    bancs d'essai : migrer et installer sur Odoo
tests/                        tests (pytest)
docs/                         documentation
```

## Tests

```bash
.venv/Scripts/pip install -r test_requirements.txt
.venv/Scripts/python -m pytest -q tests
```

## Origine et licence

Fork de [OCA/odoo-module-migrator](https://github.com/OCA/odoo-module-migrator)
(GRAP, Sylvain Le Gal et contributeurs OCA), maintenu par PSAI Consulting.
Licence AGPL-3.0 ou ultérieure.
