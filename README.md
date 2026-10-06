# odoo-module-migrator

Migre le **code source** de modules Odoo personnalisés d'une version à une
autre, de **8.0 à 20.0**, en une seule commande.

On lui donne un dossier de modules, la version de départ et la version
cible. Il enchaîne les sauts de version (`17.0 → 18.0 → 19.0 → 20.0`) et :

- **réécrit** ce qui peut l'être sûrement : champs et modèles renommés,
  dépendances de modules renommés ou fusionnés, imports déplacés, API
  remplacées, vues (`tree` → `list`, `attrs` → `invisible`…), sécurité
  (`ir.access` en 20.0), version du manifest… ;
- lance les **scripts officiels d'Odoo** (`odoo/upgrade_code`) quand les
  sources Odoo cibles sont fournies ;
- **signale** tout le reste dans un rapport par module, avec `fichier:ligne`,
  la cause et le remplaçant quand il existe : ce qu'il faut corriger à la main.

Chaque règle provient du code d'Odoo (commit cité) ou d'OpenUpgrade : aucune
règle n'est devinée, et l'outil ne contient rien de propre à un client.

## Installation

Python 3.11 ou plus récent.

```bash
git clone https://github.com/PSAI-Consulting/odoo-module-migrator.git
cd odoo-module-migrator
python -m venv .venv
.venv/Scripts/pip install -e .        # Windows  (Linux / macOS : .venv/bin/pip)
```

La commande `odoo-module-migrate` est alors disponible dans le venv.

## Démarrage rapide

```bash
# 1. Voir ce qui changerait, sans rien écrire
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --dry-run

# 2. Migrer (sur une branche git ou une copie du dossier)
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit \
    --odoo-root D:/Odoo/odoo/20.0 --odoo-python D:/Odoo/venv20/Scripts/python.exe

# 3. Lire mon_module/MIGRATION_REPORT.md et traiter les TODO
```

`--odoo-root` est facultatif mais recommandé : il active les scripts
officiels d'Odoo et la vérification des vues et des modèles contre l'Odoo
cible.

## Documentation

| Document | Contenu |
|---|---|
| [docs/COMMANDES.md](docs/COMMANDES.md) ([PDF](docs/COMMANDES.pdf)) | Toutes les commandes et options, avec des exemples |
| [docs/FONCTIONNEMENT.md](docs/FONCTIONNEMENT.md) | Comment l'outil travaille, organisation des règles, ajouter une règle |
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
