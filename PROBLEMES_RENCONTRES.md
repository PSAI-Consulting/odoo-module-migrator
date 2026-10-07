# Problèmes rencontrés — migration Stof 17.0 → 20.0

> Suivi mis à jour le 07/10/2026. Les descriptions ci-dessous sont conservées
> comme cas de reproduction. « Détection implémentée » signifie que le migrateur
> produit un TODO ; cela ne signifie pas que le module client a été corrigé.
> Les sources Stof n’ont pas été modifiées par ces travaux.
> Détails : [contrôles et limites](docs/CONTROLES_MIGRATION.md).


Problèmes relevés en utilisant l'outil (v0.6.0) sur les modules réels de Stof, branche `migration-v20`.
Commande utilisée :

```
odoo-module-migrate -d . -m <module> -i 17.0 -t 20.0 --no-commit -npc --odoo-root D:/Odoo/odoo/20.0 --odoo-python <venv 3.12>/python.exe --report-dir <hors dépôt>
```

Gravité : 🔴 produit du code faux ou qui plante · 🟠 manque une détection · 🟡 qualité / confort.

| # | Gravité | Problème | Module où vu |
|---|---|---|---|
| 1 | 🟡 | Accents écrits en `\u00e9` dans le code | `stof_partner_exchange` |
| 2 | 🟡 | Ligne vide en tête de fichier après retrait de `# -*- coding: utf-8 -*-` | `stof_partner_exchange`, `stof_customer_lead_time` |
| 3 | 🟠 | Dépendance manquante non détectée quand le champ ou le modèle est utilisé en **Python** | `stof_partner_exchange` |
| 4 | 🟠 | Changement de type d'un champ standard non signalé | `stof_customer_lead_time` |
| 5 | 🟡 | `ir.access.csv` ajouté en fin de `data` au lieu de la place de l'ancien CSV | `stof_partner_exchange` |
| 6 | 🟡 | Imports inutilisés retirés seulement par endroits | `stof_customer_lead_time` |
| 7 | 🟡 | Avertissements Odoo faciles à corriger laissés tels quels (`license`, `_description`) | `stof_partner_exchange` |
| 8 | 🟡 | `--context-path` rend l'outil très lent | `stof_partner_exchange` |
| 9 | 🟡 | Durée d'environ 2 à 4 min même pour un tout petit module | général |
| 10 | 🟡 | Avertissement « champs ajoutés automatiquement en invisible » trop bavard | `stof_partner_exchange` |
| 11 | 🟡 | Pas d'étape de formatage selon la config du projet (`ruff format`) | général |
| 12 | 🔴 | Ancre de vue validée à tort : `price_unit` est dans une `<column>` en 20 | `stof_wms_fields` |
| 13 | 🟠 | Suppression des catégories d'unités (19) non signalée : `uom.category_id`, `uom.uom_categ_*` | `stof_wms_fields` |
| 14 | 🟠 | Champs d'un autre module écrits en Python sans dépendance possible (dépendance circulaire) non signalés | `stof_wms_fields` |
| 15 | 🟠 | Précision décimale renommée non convertie : `digits='Product Unit of Measure'` → `'Product Unit'` | `stof_wms_fields` (36 occurrences dans 20 fichiers du dépôt) |
| 16 | 🔴 | Tous les contrôles abandonnés dès qu'une dépendance de la chaîne manque dans la cible (ici `stock_picking_batch`, fusionné dans `stock`) | `easi_filiere` |
| 17 | 🟠 | Ancres disparues en 20 non connues : `view_invoice_tree` sans `state` (→ `status_in_payment`), recherches de `account.move` sans `<group expand="0">` | `easi_filiere` |
| 18 | 🟡 | Traductions dans `l10n/` au lieu de `i18n/` (jamais chargées) non signalées | `easi_filiere` |
| 19 | 🟡 | `_(f"...")` (f-string dans une traduction) non signalé | `easi_filiere` |
| 20 | 🟠 | Champ ajouté par le module que la cible affiche déjà au même endroit (doublon) non signalé | `stof_sale` |
| 21 | 🟠 | `self._context` / `self._cr` / `self._uid` non convertis (dépréciés en 19) | `stof_product` |
| 22 | 🔴 | Méthode `search=`/`compute=`/`inverse=` d'un champ inexistante non signalée | `stof_product` |
| 23 | 🟠 | Surcharge accidentelle d'une méthode standard (même nom) non signalée | `stof_product` |
| 24 | 🟡 | `_` utilisé sans être importé non signalé | `stof_product` |
| 25 | 🟡 | Fichier déclaré deux fois dans `data` du manifest non signalé | `stof_product` |
| 26 | 🔴 | Ancre `<header>` disparue des formulaires produit en 20 classée 🟠 « [incomplete] » au lieu de 🔴 | `stof_product_composition` (version du 07/10) |
| 27 | 🟠 | `detailed_type` dans les expressions de vues (`invisible="detailed_type == 'service'"`) non converti ni signalé | `stof_product_composition` (version du 07/10) |
| 28 | 🟠 | Manifest avec commentaires « scaffold » non mis au modèle (« Manifest could not be inspected ») | `stof_product_composition` (version du 07/10) |

---

## 1. 🟡 Accents écrits en `\u00e9`

> **État du migrateur (07/10/2026)** : ✅ Fait — nettoyage Unicode après les scripts officiels, valeur Python inchangée.

Le script officiel `upgrade_code/18.1-00-sql-constraint.py` réécrit les messages des contraintes avec des échappements Unicode.

```python
# Avant (17.0)
_sql_constraints = [('code_uniq', 'unique(code)', 'Le code secteur existe déjà')]
# Après l'outil
_code_uniq = models.Constraint('unique(code)', "Le code secteur existe d\u00e9j\u00e0")
```

- C'est valide en Python, mais illisible, et le diff est pollué.
- **Correction proposée** : après les scripts `upgrade_code`, remettre les caractères dans les fichiers modifiés, en remplaçant `\uXXXX` par le caractère, seulement à l'intérieur des littéraux de chaîne (ast/tokenize).

## 2. 🟡 Ligne vide en tête de fichier

> **État du migrateur (07/10/2026)** : ✅ Fait — lignes initiales retirées et fin de ligne finale ajoutée, hors OCA.

La règle qui retire `# -*- coding: utf-8 -*-` laisse la ligne vide qui suivait. Le fichier commence alors par une ligne vide, avant les imports (`__init__.py`, `models/__init__.py`, `models/*.py`).

- **Correction proposée** : retirer aussi les lignes vides qui suivent l'en-tête supprimé.

## 3. 🟠 Dépendance manquante non détectée en Python

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — fournisseurs des modèles/champs Python et dépendances circulaires ; analyse statique, sans ajout automatique de dépendances.

`stof_partner_exchange` (`depends: ['base']`) contient, dans `create()` :

```python
if not contact.id_numbers and contact.ref:                       # champ de partner_identification (OCA)
    categ = self.env['res.partner.id_category'].search(...)       # modèle de partner_identification
```

- L'outil a bien signalé le menu `contacts.res_partner_menu_config`, qui est une référence XML. Mais il n'a rien vu côté Python.
- Résultat en 20 : `AttributeError: 'res.partner' object has no attribute 'id_numbers'` à **chaque création de partenaire**.
- PyCharm (plugin Odoo) le voit : « Cannot resolve symbol 'res.partner.id_category' ».
- **Correction proposée** : relever en Python les `self.env['<modèle>']` et les accès `record.<champ>` (au moins `self.<champ>` et les variables de boucle sur `self`). Vérifier que le modèle ou le champ est défini par le module ou l'une de ses dépendances (transitives). Sinon, émettre un 🔴 « ajouter <module> à depends », en nommant le module qui le définit (index `model-modules` déjà disponible).

## 4. 🟠 Changement de type d'un champ standard non signalé

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — règles de changement de type extensibles ; customer_lead Float → Integer couvert. Conversion de données laissée à la revue.

`sale.order.line.customer_lead` : `Float` en 17.0, `Integer` en 20.0. `stof_customer_lead_time` y additionne un délai partenaire `Float`, qui est désormais tronqué. L'outil n'a rien signalé. Confirmé lors de la migration du module (06/10) : rapport à 0 TODO.

- **Correction proposée** : extraire, entre les deux versions, les champs dont le **type** change. Une nouvelle sous-commande `extract_changes.py field-types` ferait l'affaire. Signaler en 🟠 chaque module qui surcharge le champ, le calcule (`_compute_<champ>`) ou l'affecte.

## 5. 🟡 Position de `ir.access.csv` dans le manifest

> **État du migrateur (07/10/2026)** : ✅ Fait — le nouveau CSV retrouve la position de l’ancien dans data.

`security/ir.model.access.csv` était en tête de `data`. Le nouveau `security/ir.access.csv` est ajouté **à la fin**.

- Sans conséquence ici, mais l'usage est de charger la sécurité en premier, et le diff est moins lisible.
- **Correction proposée** : remplacer l'entrée à la même position.

## 6. 🟡 Imports inutilisés

> **État du migrateur (07/10/2026)** : ✅ Fait — nettoyage F401 par défaut avec Ruff, hors __init__.py et OCA ; option --keep-unused-imports.

L'import `api` inutilisé a disparu de `stof_partner_exchange/models/partner_sector.py` (sans doute au passage du script officiel des contraintes), mais pas de `stof_customer_lead_time/models/res_partner.py`, qui ne déclare qu'un champ. PyCharm le signale : « Unused import statement 'api' ».

- **Correction proposée** : une étape optionnelle qui retire les imports inutilisés (F401) dans les fichiers modifiés. Attention aux `__init__.py` : les `from . import x` sont voulus.

## 7. 🟡 Avertissements Odoo faciles à corriger

> **État du migrateur (07/10/2026)** : 🟡 Partiel — licence manquante ajoutée ; _description manquant signalé, description métier à renseigner.

Au chargement en 20, Odoo signale `Missing 'license' key in manifest` et `The model partner.sector has no _description`.

- **Correction proposée** :
  - ajouter `'license': 'LGPL-3'` quand la clé manque, car c'est la valeur qu'Odoo prend déjà par défaut ;
  - signaler en 🟠 les modèles `_name` sans `_description`.

## 8. 🟡 `--context-path` très lent

> **État du migrateur (07/10/2026)** : ✅ Optimisé — chemins dédoublonnés, dépendances utiles seulement pour upgrade_code, cache disque Python/XML.

Avec `--context-path .` (le dossier lui-même, qui contient environ 200 modules), la migration d'un module de 3 fichiers prend **18 min 24**, au lieu de 1 min 42 à 4 min sans l'option. Pendant environ 15 min, rien n'apparaît dans le journal (après « Checking the view anchors »).

- **Correction proposée** :
  - indexer le contexte une seule fois, avec un cache ;
  - ignorer `--context-path` quand il est égal à `-d` ;
  - afficher la progression.

## 9. 🟡 Durée par module

> **État du migrateur (07/10/2026)** : ✅ Optimisé — cache SQLite des résumés des sources et scripts officiels limités aux modules sélectionnés ; premier indexage encore nécessaire.

Pour un petit module, sans `--context-path` : règles environ 20 s, `upgrade_code` 1 min 30 à 2 min 40, contrôles contre l'Odoo cible environ 2 min. Pour 135 modules un par un, cela fait plusieurs heures.

- **Correction proposée** :
  - mettre en cache l'index de l'Odoo cible (vues, modèles, champs) sur disque, par version et commit ;
  - lancer `upgrade_code` seulement sur les fichiers du module (`--glob`).

## 10. 🟡 Avertissement « champs invisibles » trop bavard

> **État du migrateur (07/10/2026)** : ✅ Fait — avertissement limité aux champs référencés dans une expression de la vue ; aucune conversion globale invisible → column_invisible.

`[18] Fields that are required by Python expressions ... are now added automatically` sort sur chaque `<field invisible="1"/>`, même quand le champ n'est utilisé par aucune expression de la vue.

- **Correction proposée** : ne le signaler que si le champ invisible est référencé dans un attribut `invisible`/`readonly`/`required`/`context`/`domain` de la même vue. Sinon, le classer en simple info.

## 11. 🟡 Formatage selon la config du projet

> **État du migrateur (07/10/2026)** : ✅ Fait — --format, configuration Ruff du projet, fichiers modifiés uniquement ; corrections automatiques limitées à F401.

Après migration, le code ne respecte pas toujours la config `ruff` du projet (guillemets, longueur de ligne). Le dépôt Stof a un `.ruff.toml` avec `select = ["ALL"]`, et sa CI contrôle les fichiers modifiés.

- **Correction proposée** : option `--format`, qui lance `ruff format`, puis `ruff check --fix` sur les seuls fichiers modifiés, avec la config trouvée dans le projet.

## 12. 🔴 Ancre de vue validée à tort

> **État du migrateur (07/10/2026)** : ✅ Fait — évaluation du XPath complet sur une architecture reconstruite ; composition non prise en charge signalée comme incomplète.

`stof_wms_fields/views/sale_order.xml` (après la conversion `tree` → `list` faite par l'outil) :

```xml
<xpath expr="//form[1]/sheet[1]/notebook[1]/page[@name='order_lines']/field[@name='order_line']/list[1]/field[@name='price_unit']" position="before">
```

- Le contrôle des ancres n'a rien signalé, mais l'installation plante : « ne peut être localisé dans la vue parente ».
- En 20, `sale.view_order_form` enveloppe le champ dans une colonne : `<column name="price_unit"><field name="price_unit"/></column>`. `field[@name='price_unit']` n'est donc plus un enfant direct de `list`.
- **Correction proposée** :
  - évaluer l'xpath **exactement** (axes enfant `/` vs descendant `//`) sur l'arch combinée de la vue cible ;
  - ajouter une règle 20.0 : `list/field[@name='price_unit']` → `list/column[@name='price_unit']` (source : commentaire dans `sale/views/sale_order_views.xml` en 20.0).

## 13. 🟠 Catégories d'unités supprimées non signalées

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — XML ids uom.uom_categ_* et category_id lorsque le modèle uom.uom est résolu.

```python
uom_category = self.env.ref('uom.uom_categ_length')
line.product_uom_id.category_id.id == uom_category.id
```

- L'outil a bien renommé `product_uom` → `product_uom_id`, mais n'a rien dit sur `category_id` ni sur `uom.uom_categ_length`.
- En 20, il n'y a plus de modèle `uom.category` : les unités sont chaînées par `relative_uom_id`. Pour comparer deux unités, on utilise `uom._has_common_reference(other_uom)`.
- **Correction proposée** : un 🔴 pour tout `env.ref('uom.uom_categ_*')` et tout accès `.category_id` sur un `uom.uom`, avec la piste de remplacement `_has_common_reference(self.env.ref('uom.product_uom_meter'))`.

## 14. 🟠 Champ d'un autre module écrit sans dépendance possible

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — champs écrits, module fournisseur et cycle de dépendances signalés ; aucun lien circulaire ajouté.

- `stof_wms_fields` écrit `default_delivery_address_id` et `default_invoice_address_id` sur `res.partner`. Ces champs sont définis dans `easi_filiere`, qui dépend (indirectement) de `stof_wms_fields`.
- Ajouter la dépendance créerait une boucle.
- Sans `easi_filiere`, la création d'un partenaire plante (`AttributeError … default_delivery_address_id`). PyCharm le signale : « Unresolved attribute reference ».
- Solution retenue chez Stof : **déplacer le code dans le module qui définit les champs** (`easi_filiere`).
- **Correction proposée** : avec le problème 3, quand le module qui définit le champ dépend déjà du module courant, signaler en 🔴 « dépendance circulaire : déplacer ce code dans `<module>` », en nommant le module qui définit le champ.

## 15. 🟠 Précision décimale renommée

> **État du migrateur (07/10/2026)** : ✅ Fait — renommage digits ciblé et contrôle des précisions contre les sources cibles.

```python
wms_qty_asked = fields.Float(digits='Product Unit of Measure')   # 17.0
wms_qty_asked = fields.Float(digits='Product Unit')              # 19.0 et 20.0
```

- En 19, la précision `decimal_product_uom` a été déplacée de `product` vers `uom` et renommée « Product Unit » (commit Odoo `8fd73ea390ba` « [IMP] uom: unify rounding precision on all units of measure »). Vérifié : `uom/data/uom_data.xml` en 19.0 et 20.0.
- Avec l'ancien nom, **aucune erreur** : Odoo ne trouve pas la précision et applique sa valeur par défaut. PyCharm le voit (« Cannot resolve symbol 'Product Unit of Measure' »).
- **Correction proposée** : règle `text_replaces` pour le saut 18 → 19, `digits=['"]Product Unit of Measure['"]` → `digits="Product Unit"`, en Python et dans les attributs XML `digits`. Plus généralement : extraire les `decimal.precision` (nom + xmlid) de chaque version et signaler en 🔴 tout `digits='<nom>'` inconnu de la cible (sous-commande `extract_changes.py decimal-precisions`).

## 16. 🔴 Contrôles abandonnés quand une dépendance manque

> **État du migrateur (07/10/2026)** : ✅ Fait — contrôles maintenus sur les sources disponibles, dépendances fusionnées résolues, analyse incomplète visible dans le rapport.

Rapport d'`easi_filiere` : « Dependencies not found in the addons paths (stock_picking_batch): the anchors of the inherited views and the models used are not checked ». Le rapport affiche « risque faible, 0 erreur », alors que **3 vues sur 9 étaient cassées**.

- `stock_picking_batch` n'est pas absent par hasard : il est **fusionné dans `stock`** en 20. L'outil le sait déjà, puisqu'il réécrit les `depends` des modules fusionnés.
- **Correction proposée** :
  - pendant le contrôle, remplacer les modules fusionnés ou renommés par leur cible (`stock_picking_batch` → `stock`) ;
  - pour les modules vraiment introuvables (non migrés), vérifier quand même les ancres contre les vues disponibles, et afficher « risque inconnu » au lieu de « faible ».

## 17. 🟠 Ancres disparues en 20

> **État du migrateur (07/10/2026)** : ✅ Fait — ancres standard sale/account corrigées et contrôle générique des autres vues.

Vérifié en appliquant les héritages sur les vues 20 :
- `account.view_out_invoice_tree` (hérite de `view_invoice_tree`) : plus de `<field name="state">`. La colonne d'état est `status_in_payment`.
- `account.view_account_invoice_filter` et `account.view_account_move_filter` : `<group expand="0">` devient `<group>`. Un sélecteur `<group expand="0" position="inside">` ne trouve plus rien, il faut `<xpath expr="//search/group" position="inside">`.
- **Correction proposée** : ajouter ces deux réécritures aux règles 19 → 20. Plus généralement, extraire les attributs supprimés des nœuds souvent ciblés (`group expand`, `field state`) entre deux versions.

## 18. 🟡 Dossier de traductions mal nommé

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — .po hors i18n signalés, déplacement manuel.

`easi_filiere/l10n/fr.po` : Odoo ne charge que `i18n/*.po`, donc ces traductions n'ont jamais été appliquées.
- **Correction proposée** : signaler en 🟡 tout `.po` hors de `i18n/`, sans le déplacer automatiquement, car cela changerait les libellés affichés.

## 19. 🟡 f-string dans une traduction

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — f-strings passées à la traduction signalées (INT001), texte à corriger manuellement.

```python
move.message_post(body=_(f"Alerte : le délai de paiement est supérieur à {{max_due_date}} jours. ... {days - max_due_date} jour(s)."))
```

- La f-string est évaluée **avant** la traduction, donc le texte n'est jamais trouvé dans les `.po`. Ici, en plus, `{{max_due_date}}` s'affiche littéralement.
- **Correction proposée** : signaler en 🟠 `_(f"...")` (règle ruff `INT001`), et proposer `_("... %(max)s ...", max=...)`.

## 20. 🟠 Doublon avec un champ que la cible affiche déjà

> **État du migrateur (07/10/2026)** : 🟡 Partiel — doublon potentiel avec la vue cible signalé selon le conteneur ou une ancre disparue ; pas de comparaison historique source/cible ni suppression automatique.

- `stof_sale` ajoutait `commitment_date` (+ `expected_date`) en haut du formulaire de vente, avant `show_update_pricelist`, parce qu'en 17 Odoo ne l'affichait que dans l'onglet « Autres informations ».
- En 20, `sale.view_order_form` l'affiche au même endroit (`group[@name='order_details']`, `div[@name='commitment_date_div']`, `placeholder_field: expected_date`).
- L'outil a bien signalé l'ancre `show_update_pricelist` disparue (🔴), mais pas que la correction attendue est de **supprimer** le bloc.
- **Correction proposée** : quand une vue héritée ajoute un `<field name="X">` et que la vue parente **cible** contient déjà `X` (alors que celle de la **source** ne le contenait pas à cet endroit), signaler en 🟠 « champ déjà affiché par la cible : bloc probablement à supprimer ».

## 21. 🟠 `self._context` non converti

> **État du migrateur (07/10/2026)** : ✅ Fait — raccourcis d’environnement convertis sur les accès de modèles identifiés ; commentaires et chaînes préservés.

`stof_product/models/product_product.py` : `self._context.get('lot_id')` (×5). Il est déprécié depuis la 19, et doit devenir `self.env.context`. La règle est mécanique (`self._context` → `self.env.context`, `self._cr` → `self.env.cr`, `self._uid` → `self.env.uid`), et le wiki OCA 19.0 la cite.

## 22. 🔴 Méthode d'un champ inexistante

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — callbacks nommés compute/inverse/search et méthodes héritées indexées ; limites pour les méthodes dynamiques.

```python
virtual_free_qty = fields.Float(..., search='_search_virtual_free_qty')   # méthode absente du module
```

- Toute recherche sur le champ plante (`AttributeError`). C'était déjà le cas en 17.
- **Correction proposée** : pour chaque champ, vérifier que les noms donnés à `compute=`, `inverse=`, `search=` et `_compute_*` existent dans la classe ou dans ses parents de la cible. Sinon, émettre un 🔴.

## 23. 🟠 Surcharge accidentelle d'une méthode standard

> **État du migrateur (07/10/2026)** : 🟡 Partiel — heuristique sur _compute_*/_search_* sans super ni référence au champ ; pas de comparaison générale des signatures et corps.

- Le module définit `_search_free_qty`, croyant écrire la méthode de son champ. C'est en réalité **le nom de la méthode standard** de `stock` pour `free_qty`, qu'il remplace sans appeler `super()`.
- **Correction proposée** : signaler en 🟠 toute méthode qui porte le nom d'une méthode de la cible **sans appeler `super()`** et dont la signature ou le corps diffère fortement. Cas typique à reconnaître : `_search_<champ>` / `_compute_<champ>` qui ne cite pas `<champ>`.

## 24. 🟡 `_` utilisé sans import

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — _ global utilisé sans définition/import signalé.

`raise UserError(_('Invalid domain left operand %s', field))` alors que `_` n'est pas importé : le message d'erreur lui-même aurait levé `NameError`. Avec pyflakes (règle F821), la détection est triviale.

## 25. 🟡 Fichier déclaré deux fois dans le manifest

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — fichiers répétés signalés ; retrait manuel pour préserver les chargements intentionnels.

`views/product_brand.xml` apparaît deux fois dans `data`. Odoo l'indique (« imported twice ») et l'outil pourrait le dédoublonner.

## 26. 🔴 `<header>` disparu, signalé comme simple avertissement

> **État du migrateur (07/10/2026)** : ✅ Fait — pour les formulaires produit
> standard concernés, `<header position="before">` devient
> `<sheet position="before">`. Le contenu et le format du bloc sont conservés.

Version du 07/10 (embarquée, sans `--odoo-root`). Rapport de `stof_product_composition` :
`🟠 [view] [incomplete] <header> not found in the combined view product.product_normal_form_view`.

- En 20, `product.product_template_form_view` commence directement par `<sheet>`. En 17, il avait un `<header>`.
- Les deux vues `<header position="before">` **ne s'installent pas** : c'est un 🔴, pas un 🟠.
- Correction appliquée chez Stof : `<sheet position="before">`, ce qui place l'alerte au même endroit, en haut du formulaire.
- **Correction proposée** :
  - quand l'ancre existe dans la vue source (17) et pas dans la cible (20), afficher un 🔴 même si l'arbre d'héritage est « incomplet » ;
  - proposer `<sheet position="before">` comme remplacement de `<header position="before">` sur les formulaires sans `<header>`.

## 27. 🟠 `detailed_type` dans les expressions de vues

> **État du migrateur (07/10/2026)** : ✅ Fait — les expressions des vues
> `product.template` et `product.product` sont converties selon `service`,
> `product` et `consu`. Un `detailed_type` restant est signalé en erreur.

```xml
<button name="action_section" ... invisible="detailed_type == 'service'">
```

- `detailed_type` a été supprimé en 18 (remplacé par `type`, avec `is_storable`). L'outil le gère en Python (`type=product`), mais pas dans les **attributs de vues** (`invisible`, `readonly`, `required`, `column_invisible`, `domain`).
- À l'installation, l'expression référence un champ inexistant.
- **Correction proposée** : réécrire `detailed_type == 'service'` → `type == 'service'`, `detailed_type == 'product'` → `is_storable`, `detailed_type == 'consu'` → `type == 'consu' and not is_storable`. Sinon, signaler 🔴 tout `detailed_type` restant dans une expression XML.

## 28. 🟠 Manifest non mis au modèle

> **État du migrateur (07/10/2026)** : ✅ Fait — cas original reproduit. Les
> commentaires scaffold sont retirés, les commentaires métier restent attachés
> à leur clé et une éventuelle erreur de lecture indique désormais sa cause.

```python
    'description': """
        Champs
    """,
    # Categories can be used to filter modules in modules listing
```

- Rapport : « Manifest could not be inspected ». Le manifest garde ses commentaires « scaffold », ses guillemets simples et ses listes sur une ligne.
- Cause probable : les commentaires entre les clés, ou l'espace en fin de ligne dans la description.
- **Correction proposée** : parser avec `ast` (les commentaires sont ignorés) et réécrire selon le modèle. Les commentaires « scaffold » connus peuvent être supprimés sans risque.

---

# Ce que l'outil n'a pas vu, module par module

| Module | Non vu par l'outil | Problème n° |
|---|---|---|
| `stof_partner_exchange` | Dépendance `partner_identification` utilisée en Python (`id_numbers`, `res.partner.id_category`) | 3 |
| `stof_customer_lead_time` | `sale.order.line.customer_lead` Float → Integer ; `product.sale_delay` devenu propre à chaque société | 4, A16 |
| `stof_wms_fields` | Catégories d'unités supprimées (`category_id`, `uom.uom_categ_length`) | 13 |
| `stof_wms_fields` | Ancre `list/field[@name='price_unit']` validée à tort (désormais dans une `<column>`) | 12 |
| `stof_wms_fields` | Champs de `easi_filiere` écrits sans dépendance possible (boucle) | 14 |
| `stof_wms_fields` | `digits='Product Unit of Measure'` renommé en `'Product Unit'` | 15 |
| `easi_filiere` | 3 ancres de vues cassées en 20 (contrôles abandonnés à cause de `stock_picking_batch`) | 16, 17 |
| `easi_filiere` | Traductions dans `l10n/`, f-string dans `_()` | 18, 19 |
| `stof_sale` | `digits='Product Unit of Measure'` (encore) ; bloc « Date de livraison » en doublon avec la vue 20 | 15, 20 |
| `stof_product` | `digits` (encore), `self._context`, `_` non importé, méthode de recherche inexistante, surcharge accidentelle de `_search_free_qty`, fichier en double dans le manifest | 15, 21 à 25 |
| `stof_product_composition` | `<header>` disparu (signalé en 🟠 seulement), `detailed_type` dans les vues, manifest non mis au modèle | 26, 27, 28 |
| `stof_wms_fields` | Dépendance `stof_customer_lead_time` manquante (`move.partner_id.customer_lead`, champ ajouté sur `res.partner` par ce module) | 3 |

---

# Automatisations possibles

Ce qui a été fait **à la main** sur les modules Stof, et que l'outil pourrait faire seul.
Règle commune : **ne jamais changer le comportement, les identifiants XML ni les textes traduisibles**. Changer un texte source casse sa traduction dans les `.po`.

| # | Automatisation | Exemple (module) | Remarque | État |
|---|---|---|---|---|
| A1 | Ajouter dans `depends` les modules dont le code Python utilise un modèle ou un champ (voir problème 3) | `partner_identification` dans `stof_partner_exchange` | Signaler seulement si le module manquant est OCA / tiers non migré | Détection faite ; ajout automatique non appliqué (ambiguïtés/cycles). |
| A2 | Ajouter `'license': 'LGPL-3'` quand la clé manque | `stof_partner_exchange` | Valeur qu'Odoo prend déjà par défaut : aucun changement de comportement | ✅ Fait. |
| A3 | Ajouter un `_description` aux modèles `_name` qui n'en ont pas, en anglais (dérivé de `_name` : `partner.sector` → `"Partner Sector"`) | `stof_partner_exchange` | Supprime l'avertissement Odoo ; ne pas toucher aux `.po` | Signalement fait ; génération de description non appliquée. |
| A4 | Nettoyer le manifest : retirer les commentaires du modèle `scaffold` (« Categories can be used to filter… », « any module necessary… », « always loaded ») et la `description` vide | `stof_partner_exchange` | Purement cosmétique | ✅ Fait avec le modèle de manifeste. |
| A5 | Charger les fichiers `security/` en premier dans `data` | `stof_partner_exchange` | Usage standard Odoo | Non appliqué globalement : ordre conservé ; remplacement ACL à sa position initiale. |
| A6 | `super(MaClasse, self)` → `super()` | `stof_partner_exchange` | Python 3 | Non ajouté : modernisation indépendante de la migration. |
| A7 | Tuples de commandes x2many `(0, 0, vals)`, `(4, id)`, `(6, 0, ids)`… → `Command.create(vals)`, `Command.link(id)`, `Command.set(ids)` (+ import `from odoo.fields import Command`) | `stof_partner_exchange` | Lisibilité | Non ajouté : conversion sémantique nécessitant une analyse spécifique. |
| A8 | Renommer les variables qui masquent une fonction Python (`list`, `dict`, `id`, `type`…) | `stof_partner_exchange` (`for list in vals_list`) | Signalé par PyCharm (« Shadows built-in name ») ; renommage local à la fonction uniquement | Non ajouté : renommage à relire dans son contexte. |
| A9 | Retirer les imports inutilisés (`api`…) dans les fichiers modifiés, hors `__init__.py` | `stof_customer_lead_time` | Voir problème 6 | ✅ Fait par défaut, même hors fichiers précédemment modifiés. |
| A10 | Retirer les lignes vides en tête de fichier et ajouter la fin de ligne finale | tous | Voir problème 2 | ✅ Fait. |
| A11 | Remettre les accents des chaînes (`é` → `é`) | `stof_partner_exchange` | Voir problème 1 | ✅ Fait sans modifier les valeurs Python. |
| A12 | Ajouter l'en-tête `<?xml version="1.0" encoding="utf-8"?>` aux XML qui n'en ont pas, retirer les lignes vides en trop | `stof_partner_exchange` | Cosmétique | Non ajouté : cosmétique XML facultative. |
| A13 | Lancer `ruff format` puis `ruff check --fix` avec la config du projet, sur les seuls fichiers modifiés (option `--format`) | `stof_partner_exchange` | Voir problème 11. Ne **pas** ajouter d'en-tête de copyright (choix de l'équipe) | ✅ Fait ; F401 sûr puis formatage optionnel, pas de fix ALL. |
| A14 | Supprimer le code mort commenté (anciens champs en commentaire) | `stof_partner_exchange` | À proposer en option, pas par défaut | Non ajouté : suppression de commentaires laissée à la revue. |
| A16 | Champ devenu `company_dependent` dans la cible (ex. `product.sale_delay` en 20) : signaler en 🟠 les lectures `record.produit.<champ>` hors `with_company(...)` dans un calcul par ligne | `stof_customer_lead_time` | Le calcul standard d'Odoo 20 lit `product_id.with_company(line.company_id).sale_delay` | Détection ciblée sale_delay implémentée ; contrôle statique. |
| A17 | Quand un champ standard change de type (problème 4), proposer d'aligner le champ custom associé (ex. `res.partner.customer_lead` `Float` → `Integer`) et rappeler de vérifier les données | `stof_customer_lead_time` | Odoo convertit la colonne sur place (`ALTER … TYPE … USING`) | Changement standard signalé ; alignement custom et données à revoir manuellement. |
| A18 | Ne pas faire de `write()` dans une méthode `_compute_*` : proposer l'affectation `record.champ = valeur` | `stof_wms_fields` | Signalé en 🟠, correction manuelle | ✅ Signalement implémenté. |
| A20 | Appliquer le modèle de manifest de l'équipe (ordre des clés, `website` et `license` toujours présents, listes une valeur par ligne) | tous | Voir `_Modèle manifest` (Obsidian Stof) | ✅ Modèle intégré et générique ; ordre data conservé, site absent configurable. |
| A15 | Ne **pas** appliquer les nettoyages cosmétiques (A2 à A14) aux modules **OCA** : seulement les corrections nécessaires, pour garder le code proche de l'OCA | — | Détection déjà disponible (`--no-oca-modules`) | ✅ Fait : nettoyages ignorés pour les modules reconnus OCA. |
