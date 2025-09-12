# Migrateur de Modules Odoo

Outil de migration automatique des modules Odoo d'une version à l'autre, spécialisé pour la migration 16.0 → 18.0.

## 🎯 Fonctionnalités

- **Migration automatique** : attrs/states deprecated → invisible/readonly/required
- **Conversion tree → list** : Mise à jour des vues pour Odoo 17.0+
- **Détection modules OCA** : Option --no-oca-modules pour ignorer les modules communautaires
- **Génération documentation** : --oca-file-list pour créer OCA_MODULES.md
- **Préservation du formatage** : Maintient l'indentation originale des fichiers XML

## 🚀 Installation

```bash
cd odoo-module-migrator
python setup.py sdist
pip install ./dist/odoo_module_migrator-0.5.0.tar.gz
```

## 📖 Usage

### Migration complète d'un projet

```bash
# Migrer tous les modules 16.0 → 18.0 (sans commit)
odoo-module-migrate --init-version-name 16.0 --target-version-name 18.0 --no-commit

# Migrer en ignorant les modules OCA
odoo-module-migrate --init-version-name 16.0 --target-version-name 18.0 --no-commit --no-oca-modules
```

### Migration de modules spécifiques

```bash
# Migrer uniquement certains modules
odoo-module-migrate -i 16.0 -t 18.0 --no-commit --modules module1,module2,module3
```

### Génération documentation OCA

```bash
# Créer la liste des modules OCA dans OCA_MODULES.md
odoo-module-migrate --init-version-name 16.0 --oca-file-list
```

## ⚙️ Options principales

| Option                     | Description                                                               |
|----------------------------|---------------------------------------------------------------------------|
| `-i, --init-version-name`  | Version source (ex: 16.0)                                                 |
| `-t, --target-version-name` | Version cible (ex: 18.0)                                                  |
| `-m, --modules`            | Modules à migrer (séparés par virgule)                                    |
| `--no-commit`              | Ne pas créer de commits git                                               |
| `--no-oca-modules`         | Ignorer les modules OCA                                                   |
| `--oca-file-list`          | Générer OCA_MODULES.md                                                    |
| `-d, --directory`          | Répertoire cible (défaut: ./)                                             |
| `-ll, --log-level`         | Niveau de Log (défaut: INFO)                                              |
| `-lp, --log-path`          | Fichier de log (défaut: (vide))                                           |
| `-lpwo, --log-path-warninglevelonly`          | Fichier de log pour stocker WARNING et ERROR en markdown (défaut: (vide)) |

## 🔍 Types de logs

- **INFO** ✅ : Migration automatique appliquée
- **WARNING** ⚠️ : Vérification manuelle recommandée  
- **ERROR** ❌ : Action manuelle requise

## 🎯 Migration 16.0 → 18.0

Cette version est spécialement optimisée pour la migration vers Odoo 18.0 :

### ✅ Conversions automatiques

- `attrs="{'invisible': [('field', '=', 'value')]}"` → `invisible="field == 'value'"`
- `states="draft,done"` → `invisible="state not in ('draft','done')"`
- `<tree>` → `<list>` (vues)
- `tree_view_ref` → `list_view_ref`
- `invisible` → `column_invisible` (dans les arbres)
- Suppression `unaccent=False` parameter
- `kanban-box/card` → `card`
- `<div class="oe_chatter">` → `<chatter/>`

### 🤖 Détection intelligente

- Convertit les domaines Odoo en expressions Python
- Support des opérateurs : `=`, `!=`, `in`, `not in`, `>`, `>=`, `<`, `<=`
- Gestion des opérateurs logiques : `&` (and), `|` (or), `!` (not)

## 📜 Licence

AGPL-3.0

---

*Version optimisée pour la migration Odoo 16.0 → 18.0 | Maintient le formatage XML original*