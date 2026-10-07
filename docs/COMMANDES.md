# Guide des commandes — odoo-module-migrator

Ce guide explique comment migrer des modules Odoo avec `odoo-module-migrate`,
de l'installation à la lecture du rapport. La dernière partie présente les
outils de mainteneur (régénérer les règles, bancs d'essai).

---

## 1. Installer

Il faut Python 3.12 ou plus récent et git.

```bash
git clone https://github.com/PSAI-Consulting/odoo-module-migrator.git
cd odoo-module-migrator
python -m venv .venv
.venv/Scripts/pip install -e .
```

Sous Linux / macOS, remplacez `.venv/Scripts/` par `.venv/bin/`.

Vérifier :

```bash
odoo-module-migrate --version
```

Les scripts officiels Community 18/19/20 sont embarqués et actifs par défaut.
Le manifeste suit le modèle commun et les imports inutilisés sont nettoyés
(hors `__init__.py` et modules OCA). Options utiles :

- `--format` : formater les fichiers Python modifiés selon la configuration Ruff du projet.
- `--default-website URL` : compléter un site absent, sans remplacer un site existant.
- `--keep-unused-imports` : conserver les imports inutilisés.
- `--no-manifest-format` : conserver la mise en forme du manifeste.
- `--no-upgrade-code` : utiliser uniquement les règles internes.

Voir [les contrôles et limites](CONTROLES_MIGRATION.md).

---

## 2. Migrer un module : les trois étapes

### Étape 1 — Prévisualiser (rien n'est écrit)

```bash
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --dry-run
```

L'outil migre une copie temporaire et affiche les différences (format
`diff`). Vos fichiers ne sont pas modifiés.

### Étape 2 — Migrer

Travaillez sur une **branche git** ou une **copie** du dossier : l'outil
modifie les fichiers sur place.

```bash
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit
```

Version recommandée, avec les sources de l'Odoo cible :

```bash
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit \
    --odoo-root D:/Odoo/odoo/20.0 \
    --odoo-python D:/Odoo/venv20/Scripts/python.exe
```

Avec `--odoo-root`, l'outil :

- lance les **scripts officiels d'Odoo** (`odoo/upgrade_code` : `ir.access`,
  OWL 3, contraintes SQL…) ;
- vérifie que chaque **vue héritée** trouve ses ancres dans l'Odoo cible ;
- vérifie que les **modèles** hérités ou référencés existent encore ;
- vérifie les chemins `@api.depends` / `related=` et les imports
  `odoo.addons.*`.

`--odoo-python` est le Python capable d'importer l'Odoo cible (Odoo 20 :
Python 3.12 ou plus). Les dossiers `enterprise/20.0` et `design-themes/20.0`
voisins de `--odoo-root` sont trouvés automatiquement (sinon : `--addons-path`).

### Étape 3 — Lire le rapport

Chaque module migré contient un fichier **`MIGRATION_REPORT.md`** :

| Partie | Contenu |
|---|---|
| Résumé | niveau de risque, nombre de TODO, dont erreurs, transformations, fichiers modifiés |
| TODO manuels | par fichier, avec `fichier:ligne` cliquable : 🔴 erreur (bloque l'installation), 🟠 à vérifier |
| Transformations appliquées | ce que l'outil a réécrit |
| Fichiers modifiés | ajoutés, modifiés, supprimés |

Traitez les 🔴 d'abord, puis installez le module sur une base de test.

---

## 3. Exemples courants

```bash
# Tous les modules d'un dossier
odoo-module-migrate -d ./mes_modules -i 16.0 -t 20.0 --no-commit

# Plusieurs modules précis
odoo-module-migrate -d ./mes_modules -m module_a,module_b -i 17.0 -t 18.0 --no-commit

# Rapports regroupés dans un dossier (un fichier par module + un sommaire)
odoo-module-migrate -d ./mes_modules -i 17.0 -t 20.0 --no-commit --report-dir ./rapports

# Les dépendances sont dans un autre dossier (lu seulement, jamais modifié)
odoo-module-migrate -d ./projet -m mon_module -i 17.0 -t 20.0 --no-commit \
    --odoo-root D:/Odoo/odoo/20.0 --odoo-python D:/Odoo/venv20/Scripts/python.exe \
    --context-path ./autres_modules

# Ignorer les modules OCA présents dans le dossier
odoo-module-migrate -d ./mes_modules -i 17.0 -t 20.0 --no-commit --no-oca-modules

# Journal complet dans un fichier
odoo-module-migrate -d ./mes_modules -i 17.0 -t 20.0 --no-commit --log-path migration.log
```

Relancer la migration sur un module déjà migré ne change rien
(l'outil est idempotent).

---

## 4. Toutes les options

### Indispensables

| Option | Rôle |
|---|---|
| `-i`, `--init-version-name` | Version de départ : `8.0` à `19.0` (obligatoire) |
| `-t`, `--target-version-name` | Version cible : `9.0` à `20.0` (défaut : la plus récente) |
| `-d`, `--directory` | Dossier contenant les modules (défaut : dossier courant) |
| `-m`, `--modules` | Modules à migrer, séparés par des virgules (défaut : tous) |

### Sécurité et contrôle

| Option | Rôle |
|---|---|
| `-n`, `--dry-run` | Prévisualiser : affiche les différences, n'écrit rien |
| `-nc`, `--no-commit` | Ne pas créer de commit git (recommandé : vous relisez avant de commiter) |
| `-npc`, `--no-pre-commit` | Ne pas lancer pre-commit après la migration |
| `-nrmf`, `--no-remove-migration-folder` | Garder les dossiers `migrations/` des modules (supprimés par défaut) |
| `--set-installable` | Forcer `'installable': True` (par défaut, un module désactivé exprès reste désactivé et c'est signalé) |

### Odoo cible (recommandé à partir de 18.0)

| Option | Rôle |
|---|---|
| `--odoo-root` | Sources de l'Odoo **cible** (ex. `D:/Odoo/odoo/20.0`) |
| `--odoo-python` | Python capable d'importer cet Odoo |
| `--addons-path` | Addons de référence, séparés par des virgules (défaut : `enterprise` et `design-themes` voisins) |
| `--context-path` | Autres dossiers de modules où chercher les dépendances (lecture seule) |

### Rapport et journal

| Option | Rôle |
|---|---|
| `--report-dir DOSSIER` | Écrire les rapports dans ce dossier (`<module>.md` + `README.md` récapitulatif) au lieu de `MIGRATION_REPORT.md` dans chaque module |
| `--no-report` | Pas de rapport |
| `-ll`, `--log-level` | `DEBUG`, `INFO` (défaut), `WARNING`, `ERROR`, `CRITICAL` |
| `-lp`, `--log-path FICHIER` | Écrire le journal dans un fichier |
| `-lpwo`, `--log-path-warninglevelonly FICHIER` | Écrire seulement les avertissements et erreurs (Markdown) |

### Divers

| Option | Rôle |
|---|---|
| `--no-oca-modules` | Ne pas migrer les modules OCA trouvés dans le dossier |
| `--oca-file-list` | Écrire `OCA_MODULES.md` : liste des modules OCA du projet |
| `-fp`, `--format-patch` | Récupérer le module depuis la branche de la version précédente du dépôt (`git format-patch`, un seul module) |
| `-rn`, `--remote-name` | Remote git utilisé par `--format-patch` (défaut : `origin`) |
| `--version` | Afficher la version de l'outil |
| `-h`, `--help` | Afficher l'aide |

---

## 5. Questions fréquentes

**Le module ne s'installe toujours pas après la migration.**
C'est normal pour une partie des modules : certaines évolutions d'Odoo ne
peuvent pas être réécrites automatiquement (une vue cible a disparu, un
modèle a été supprimé…). Elles sont toutes dans le rapport, avec
`fichier:ligne`. Commencez par les 🔴.

**Un TODO me paraît faux.**
Vérifiez dans les sources de l'Odoo cible. Si le TODO est vraiment faux,
c'est un bug de l'outil : signalez-le avec l'extrait de code concerné.

**Puis-je migrer de 12.0 directement en 20.0 ?**
Oui : l'outil enchaîne tous les sauts. Le rapport regroupe les TODO de
tous les sauts.

**Mes fichiers changent-ils d'encodage ou de fins de ligne ?**
Non : l'encodage, le BOM et les fins de ligne (CRLF / LF) de chaque fichier
sont conservés.

---

## 6. Outils de mainteneur

Ces outils servent à faire évoluer l'outil lui-même. Ils sont dans `tools/`
et ne sont pas installés avec la commande.

### Régénérer les règles depuis les sources Odoo

Une seule commande, `tools/extract/extract_changes.py`, avec une
sous-commande par type de règle. Elle lit des dépôts git **bare** d'Odoo
(aucun checkout) :

```bash
# Modules supprimés / renommés / fusionnés
python tools/extract/extract_changes.py modules --from 19.0 --to 20.0 \
    --repo D:/Odoo/.repos/odoo.git@addons --repo D:/Odoo/.repos/enterprise.git \
    --openupgrade D:/Odoo/local-addons/OdooOCA/OpenUpgrade \
    --output odoo_module_migrate/migration_scripts/deprecated_modules/migrate_190_200/modules.yaml
```

| Sous-commande | Produit |
|---|---|
| `modules` | modules supprimés, renommés, fusionnés |
| `fields` | champs renommés / supprimés (OpenUpgrade + sources, `--sources`) |
| `models` | modèles supprimés / renommés |
| `api` | API Python retirée (candidats à relire) |
| `js` | modules JS supprimés ou déplacés |
| `views` | vues supprimées (héritages cassés) |
| `model-modules` | module qui définit chaque modèle |
| `tools-exports` | noms que `from odoo.tools import X` ne fournit plus |

Détail des options : `python tools/extract/extract_changes.py <sous-commande> --help`.
Les fichiers produits s'appellent `generated.yaml` ; les corrections faites à
la main vont dans `curated.yaml` (voir [FONCTIONNEMENT.md](FONCTIONNEMENT.md)).

### Bancs d'essai : migrer puis installer sur une base Odoo vierge

Un banc est décrit par un fichier YAML (`tools/bench/benches/*.yaml`) :
versions, sources Odoo, modules à tester.

```bash
# Banc complet : export, migration, contrôles, installation, résultats
python tools/bench/bench.py tools/bench/benches/example_oca_17_20.yaml --work D:/tmp/bancs

# Boucle rapide : refaire seulement les modules en échec
python tools/bench/bench.py tools/bench/benches/example_oca_17_20.yaml --work D:/tmp/bancs --retry-failed

# Migration et contrôles seulement, sans base de données
python tools/bench/bench.py tools/bench/benches/example_oca_17_20.yaml --work D:/tmp/bancs --skip-install
```

Résultat : `<work>/<banc>/RESULTS.md` (un module par ligne : installé ou non,
première erreur, lien vers son rapport).

Les bases créées s'appellent toujours `migrator_bench_*` et sont supprimées
à la fin ; aucune autre base n'est touchée.

| Outil | Rôle |
|---|---|
| `bench/bench.py` | banc complet ou boucle rapide (`--retry-failed`) |
| `bench/bench_install.py` | installation par lots sur une copie de base vierge (utilisé par le banc) |
| `bench/check_modules.py` | contrôles statiques d'un dossier de modules |
| `bench/ground_truth.py` | compare la migration de l'outil à celle faite à la main par l'OCA |
