# Outils de mainteneur

Ces outils servent à **faire évoluer** odoo-module-migrator. Ils ne sont pas
installés avec la commande `odoo-module-migrate` et ne sont pas nécessaires
pour migrer des modules.

| Dossier | À quoi ça sert |
|---|---|
| [`extract/`](extract) | Régénérer les règles depuis les sources git d'Odoo et d'OpenUpgrade (à chaque nouvelle version d'Odoo) |
| [`bench/`](bench) | Bancs d'essai : migrer des modules réels puis les installer sur une base Odoo vierge, pour mesurer et trouver ce qui manque |

## extract/

Point d'entrée unique : `extract_changes.py <sous-commande>`
(`modules`, `fields`, `models`, `api`, `js`, `views`, `model-modules`,
`tools-exports`). Les autres fichiers sont ses modules internes.

## bench/

| Fichier | Rôle |
|---|---|
| `bench.py` | banc complet (export, migration, contrôles, installation, `RESULTS.md`) ou boucle rapide sur les échecs (`--retry-failed`) |
| `bench_install.py` | installation par lots sur des copies d'une base vierge (bases `migrator_bench_*` uniquement) |
| `check_modules.py` | contrôles statiques d'un dossier de modules |
| `ground_truth.py` | compare la migration de l'outil à la migration faite à la main par l'OCA |
| `benches/example_oca_17_20.yaml` | exemple de banc ; vos bancs (`benches/*.yaml`) restent en local, ignorés par git |

Exemples et options : [docs/COMMANDES.md](../docs/COMMANDES.md#6-outils-de-mainteneur).

## docs_pdf.py

Regénère le PDF d'un document : `python tools/docs_pdf.py docs/COMMANDES.md`
(nécessite `pip install markdown` et Chrome ou Edge).
