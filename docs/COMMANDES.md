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

### Commande complète recommandée

Sous PowerShell, pour migrer un module Stof de 17.0 à 20.0 :

```powershell
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

Remplacez `stof_partner_backorder_strategy` par le module à migrer. Plusieurs
modules peuvent être séparés par des virgules. Cette commande :

- utilise les scripts officiels et les sources Community 20 embarqués ;
- lit les autres modules du dossier Stof pour résoudre les dépendances ;
- conserve un `website` existant et complète seulement ceux qui n'en ont pas ;
- normalise les manifestes et retire les imports F401 inutilisés ;
- applique Ruff aux fichiers Python effectivement modifiés ;
- écrit les rapports dans `D:\Odoo\local-addons\Stof\migration-reports` ;
- laisse la création du commit et l'exécution de pre-commit à l'utilisateur.

Les sources Enterprise ne sont pas incluses dans le paquet. Si le module en
dépend, ajoutez par exemple :

```powershell
    --addons-path "D:\Odoo\enterprise\20.0,D:\Odoo\design-themes\20.0"
```

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

Version avec une copie locale de l'Odoo cible, utile pour remplacer les
références Community embarquées :

```bash
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit \
    --odoo-root D:/Odoo/odoo/20.0 \
    --odoo-python D:/Odoo/venv20/Scripts/python.exe
```

Avec ou sans `--odoo-root`, l'outil :

- lance les **scripts officiels d'Odoo** (`odoo/upgrade_code` : `ir.access`,
  OWL 3, contraintes SQL…) ;
- vérifie que chaque **vue héritée** trouve ses ancres dans l'Odoo cible ;
- vérifie que les **modèles** hérités ou référencés existent encore ;
- vérifie les chemins `@api.depends` / `related=` et les imports
  `odoo.addons.*`.

Sans `--odoo-root`, le Python courant et les archives Community embarquées
sont utilisés. Avec `--odoo-root`, `--odoo-python` choisit le Python du lanceur
officiel ; par défaut, l'outil utilise le Python courant s'il est compatible.
Les dossiers `enterprise/20.0` et `design-themes/20.0` voisins des sources
locales sont trouvés automatiquement. Sinon, utilisez `--addons-path`.

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
    --context-path ./autres_modules

# Références Enterprise en plus des références Community embarquées
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit \
    --addons-path D:/Odoo/enterprise/20.0,D:/Odoo/design-themes/20.0

# Conserver la présentation du manifeste et les imports inutilisés
odoo-module-migrate -d ./mes_modules -m mon_module -i 17.0 -t 20.0 --no-commit \
    --no-manifest-format --keep-unused-imports

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

### Scripts officiels et sources de référence (cibles 18.0 à 20.0)

| Option | Rôle |
|---|---|
| `--odoo-root` | Remplacer les sources Community embarquées par les sources de l'Odoo cible |
| `--odoo-python` | Python utilisé par le lanceur officiel avec `--odoo-root` |
| `--addons-path` | Addons de référence supplémentaires, séparés par des virgules, notamment Enterprise |
| `--context-path` | Autres dossiers de modules où chercher les dépendances (lecture seule) |
| `--no-upgrade-code` | Désactiver les scripts officiels et les contrôles contre les sources cibles |

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
| `--format` | Formater avec Ruff les fichiers Python modifiés, selon la configuration du projet |
| `--keep-unused-imports` | Désactiver le nettoyage F401 automatique hors `__init__.py` |
| `--no-manifest-format` | Conserver la présentation d'origine du manifeste |
| `--default-website URL` | Compléter le site uniquement lorsqu'il est absent ; ne remplace jamais une valeur existante |
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

**Faut-il installer Odoo pour utiliser les scripts officiels ?**
Non pour les versions cibles 18, 19 et 20 : les scripts et références Community
sont embarqués. Python 3.12+ suffit. Fournissez `--addons-path` si l'analyse doit
aussi voir Enterprise ou d'autres sources de référence.

**Pourquoi l'outil ne transforme-t-il pas tous les `invisible` en
`column_invisible` ?** Les deux attributs n'ont pas la même portée :
`invisible` peut dépendre de la ligne, tandis que `column_invisible` masque une
colonne entière sans le contexte de chaque ligne. Seules les conversions dont
le contexte est prouvé sont appliquées.

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
| `field-types` | changements de type des champs entre deux versions |
| `decimal-precisions` | inventaires des précisions décimales des deux versions |

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
