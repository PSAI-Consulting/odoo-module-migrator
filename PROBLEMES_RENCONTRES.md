# Problèmes rencontrés — migration Stof 17.0 → 20.0

> Suivi mis à jour le 08/10/2026. Les descriptions ci-dessous sont conservées
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

> **État du migrateur (08/10/2026)** : ✅ Correction automatique — licence
> manquante ajoutée et `_description` généré en anglais depuis le `_name` pour
> les modules internes. Les modules OCA restent inchangés.

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

> **État du migrateur (08/10/2026)** : ✅ Correction automatique pour les
> interpolations simples (nom ou attribut), avec paramètres nommés extractibles.
> Les appels, indices, conversions et formats (`:.2f`) restent signalés INT001.

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

## 29. 🟠 Manifest lu pendant une étape intermédiaire

> **État du migrateur (07/10/2026)** : ✅ Fait — le retrait d'une entrée
> `data` par le convertisseur officiel utilise désormais les positions AST et
> laisse toujours une liste valide. Le manifeste final est ensuite relu et mis
> au modèle normalement.

- Module : `easi_oekotex`. Rapport : « Manifest could not be inspected (SyntaxError: closing parenthesis '}' does not match opening parenthesis '[' on line 26) ».
- Le manifest final est pourtant **valide** : l'erreur vient d'un état intermédiaire, après le retrait de la ligne `security/ir.model.access.csv` (scripts officiels `upgrade_code`).
- Conséquence : la mise au modèle (A20) est sautée et le rapport affiche un TODO trompeur.
- **Correction proposée** : relire le manifest à la fin du pipeline avant de conclure ; si la lecture réussit, appliquer le modèle et retirer le TODO. Vérifier aussi que le retrait d'une ligne de liste ne laisse pas le fichier invalide.

## 30. 🟡 Mise au modèle du manifest incomplète

> **État du migrateur (07/10/2026)** : ✅ Fait — les descriptions multilignes
> restent en triples guillemets et les clés optionnelles vides `summary`,
> `description`, `external_dependencies`, `demo` et `assets` sont retirées.

- Module : `easi_account_validation_automatic`.
- La `description` en bloc `"""…"""` est réécrite en chaîne avec `
` : `"
       Validation automatique…
    "`. Moins lisible.
- `"summary": ""` et `"external_dependencies": {}` vides sont gardés, alors que le modèle retire les clés vides.
- **Correction proposée** : garder les chaînes multilignes en `"""…"""` ; retirer les clés vides (`summary`, `description`, `external_dependencies`, `demo`, `assets`).

## 31. 🟠 Tâche planifiée qui appelle une méthode absente du module

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — les appels
> directs `model.<méthode>()` des `ir.cron` et `ir.actions.server` sont vérifiés
> contre le modèle et ses parents. Le rapport nomme les modules fournisseurs
> présents hors des dépendances.

- Module : `easi_account_validation_automatic`. La tâche appelle `model._cron_validate()`, mais le module définit `_cron_validate_invoices`.
- `_cron_validate` existe sur `account.move` seulement via `account_invoice_extract` (Enterprise, OCR), qui n'est pas une dépendance : la tâche lancerait l'OCR.
- Rapport : « Risque aucun », 0 TODO.
- **Correction proposée** : pour chaque `ir.cron` (et `ir.actions.server`) avec `model.<méthode>()`, vérifier que la méthode existe dans le module ou ses dépendances ; sinon TODO 🟠, en précisant le module hors dépendances qui la définit.

## 32. 🟠 Champ `res.partner.bank.acc_number` renommé en `account_number`

> **État du migrateur (07/10/2026)** : ✅ Fait — en complément de la règle
> modèle/champ existante, les commandes de création sous `bank_ids` et les
> expressions QWeb dont le récepteur désigne une banque sont converties. Les
> accès attributaires ou QWeb encore ambigus sont signalés en erreur ; les clés
> des flux externes restent inchangées.

- Vu en testant `easi_account_payment_term_bank` (le module lui-même ne l'utilise pas) : `Invalid field 'acc_number' in 'res.partner.bank'`.
- Renommé en saas-19.2, donc en 20. Utilisé par `edi_bi_generic_import` (Python, ×8) et `account_payment_partner` (OCA, rapport QWeb, ×3).
- **Correction proposée** : renommer `acc_number` → `account_number` en Python, XML et QWeb quand le modèle est `res.partner.bank` (ou `partner_bank_id.` / `bank_ids.`) ; sinon TODO 🔴.

## 33. 🟡 Menu parent disparu : signalé, mais sans piste de remplacement

> **État du migrateur (07/10/2026)** : ✅ Fait — les déplacements des anciens
> enfants standards sont utilisés comme preuves pour proposer les parents
> cibles encore présents. Plusieurs candidats sont affichés lorsque les enfants
> ont été répartis, sans remplacement automatique ambigu.

- Module : `psai_refund_type`. Rapport : 🔴 « XML id account.account_management_menu does not exist in the target Odoo ». Bien détecté.
- Il faut ensuite chercher à la main où sont passés les enfants du menu en 17 (`menu_product_product_categories` → `account.account_invoicing_menu`).
- **Correction proposée** : quand un `parent` de `menuitem` disparaît, lister les menus enfants de la 17 et leur nouveau parent en 20, et proposer ce parent dans le TODO.

## 34. 🔴 Unité des lignes renommée non détectée (`product_uom`)

> **État du migrateur (07/10/2026)** : ✅ Fait — le passage tardif utilise
> l'index des relations de la cible pour suivre les alias imbriqués
> (`order.order_line` → `line`) et applique les renommages successifs de chaque
> saut. Un champ résolu mais absent de la cible est aussi signalé en erreur.

- Module : `easi_purchase_minimum`. `uom_id=line.product_uom` sur `purchase.order.line` : rapport « Risque aucun », erreur à la confirmation de commande.
- En 20 : `sale.order.line.product_uom` → `product_uom_id`, `purchase.order.line.product_uom` → `uom_id`, `stock.move.product_uom` → `uom_id`. ~180 occurrences dans Stof.
- **Correction proposée** : renommer quand le modèle est connu (`line`, `order_line`, `move_ids`, vues de ces modèles) ; sinon TODO 🔴. Le contrôle des champs contre la cible aurait dû le voir : à vérifier pourquoi il ne l'a pas fait (variable de boucle `line` sur `order.order_line`).

## 35. 🔴 `_select_seller()` renvoie un dictionnaire

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — chaque appel
> dont le résultat n'est pas encore extrait via la clé `supplierinfo` est
> signalé en erreur, avec un recordset vide sûr comme valeur de repli. La
> transformation reste manuelle car le résultat peut être consommé de plusieurs
> façons ; le code déjà adapté n'est pas signalé.

- Module : `easi_purchase_minimum`. `seller.field_verify` → `AttributeError: 'dict' object has no attribute 'field_verify'`.
- Commit Odoo `ab29b56cb6be` : la ligne fournisseur est dans `["supplierinfo"]`, `{}` si aucune.
- **Correction proposée** : TODO 🔴 sur chaque `_select_seller(`, avec la conversion `x = ..._select_seller(...).get("supplierinfo", env["product.supplierinfo"])` quand le résultat est utilisé comme enregistrement.

## 36. 🟠 Libellé de ligne sans le nom du produit

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — usages Python
> résolus sur les lignes de vente, achat et facture, ainsi que les expressions
> QWeb dont le nom de variable désigne explicitement une ligne. Le rapport
> propose `product_id.display_name` sans modifier les textes traduisibles.

- Module : `easi_purchase_minimum`. Message d'erreur avec `line.name` → nom du produit vide, **sans erreur**.
- Commit Odoo `c5037bbe0789` : `name` des lignes de vente, d'achat et de facture ne contient plus le nom du produit.
- **Correction proposée** : TODO 🟠 sur `line.name` / `.order_line.name` / `invoice_line_ids.name` (Python et QWeb), en proposant `product_id.display_name`.

## 37. 🟡 Valeur par défaut changée (`min_qty` 0 → 1)

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — un appel à
> `_select_seller()` sans argument `quantity` est signalé avec l'impact du
> nouveau défaut de `product.supplierinfo.min_qty`. Le contrôle est lié au
> comportement affecté plutôt qu'à tous les changements de valeurs par défaut.

- Module : `easi_purchase_minimum`. `_select_seller()` sans `quantity` écarte les lignes fournisseur dont `min_qty` > 0 ; en 20, les nouvelles lignes ont `min_qty = 1`.
- **Correction proposée** : signaler les `_select_seller(` sans `quantity` (🟠), et plus généralement comparer les `default=` des champs standard entre source et cible.

## 38. 🔴 Faux positifs sur le champ `id`

> **État du migrateur (07/10/2026)** : ✅ Fait — les champs magiques communs
> sont intégrés à chaque modèle indexé et le diagnostic Python réutilise la
> même liste que le contrôle des chemins de champs.

- Module : `sale_order_block_duplicate_product`. 3 TODO 🔴 « Field product.product.id does not exist in the indexed target » (`line.product_id.id`, `self.id`).
- `id` (et les autres champs magiques : `display_name`, `create_date`, `write_date`, `create_uid`, `write_uid`) n'est pas dans l'index des champs. Le risque passe à « élevé » à tort.
- **Correction proposée** : ajouter les champs magiques de `BaseModel` à tous les modèles indexés.

## 39. 🟡 `_()` dans une expression génératrice ou une lambda

> **État du migrateur (07/10/2026)** : ✅ Fait — dans les méthodes de modèles,
> les appels `_()` situés dans un générateur, une compréhension ou une lambda
> deviennent `self.env._()` au saut 17→18. Les appels ordinaires, les classes
> non Odoo et les portées qui redéfinissent `self` sont conservés.

- Module : `sale_order_block_duplicate_product`. `", ".join(_("line %(sequence)s…") for line in lines)` : `_()` cherche `self` dans le cadre appelant pour trouver la langue ; dans une expression génératrice, il ne le trouve pas et le texte reste en anglais, sans erreur.
- **Correction proposée** : remplacer `_()` par `self.env._()` (Odoo 18+) dans les expressions génératrices, compréhensions et lambdas d'une méthode ; ou plus largement, partout où `self` est disponible.

## 40. 🔴 Plantage à l'écriture du rapport (`KeyError: 'inconnu'`)

> **État du migrateur (07/10/2026)** : ✅ Fait — le risque `inconnu` est
> ordonné explicitement dans le sommaire et une valeur inconnue future utilise
> un ordre de repli au lieu de faire échouer la commande.

- Module : `additional_salesperson`. Le rapport du module est écrit, puis `render_summary` plante : `order[r.risk]` ne connaît pas le risque « inconnu ». Code de sortie 1.
- **Correction proposée** : ajouter « inconnu » à `order` (ou `order.get(r.risk, 99)`).

## 41. 🟠 Manifest avec une virgule manquante : clé fantôme gardée

> **État du migrateur (07/10/2026)** : ✅ Fait — la version manquante est
> réellement insérée avec la version cible. Les clés inconnues et les clés
> composées de littéraux de chaînes adjacents sont signalées en erreur sans
> supprimer d'éventuelles métadonnées personnalisées.

- Module : `additional_salesperson`. `'category': 'Contact','Sales'` puis `'version': '0.1'` : Python lit `'Sales' 'version'` comme une seule clé `'Salesversion'`. Le module n'a donc **pas de version**.
- Le migrator a écrit `"Salesversion": "20.0.0.1"` en fin de manifest, sans `version`.
- **Correction proposée** : signaler en 🔴 toute clé de manifest inconnue d'Odoo ; si `version` manque, l'ajouter. Les chaînes collées (`'a' 'b'`) se repèrent avec `tokenize`.

## 42. 🟠 Surcharge d'une méthode qui n'existe nulle part

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — une méthode
> qui appelle son homonyme via `super()` est comparée aux parents indexés. Les
> renommages historiques vérifiés sont extensibles par règles ; le cas CRM
> propose `_prepare_customer_values` avec le commit Odoo source. Sinon, les
> noms proches sont présentés comme pistes seulement.

- Module : `additional_salesperson`. `crm.lead._create_lead_partner_data` n'existe plus depuis la 13 (remplacée par `_prepare_customer_values`) : la surcharge et son `super()` ne sont jamais appelés, sans erreur.
- **Correction proposée** : pour chaque méthode surchargée qui appelle `super()`, vérifier qu'elle existe dans un parent de la cible ; sinon TODO 🟠, avec la méthode au nom le plus proche.

## 43. 🟡 Faux positif sur un filtre remplacé par une vue fille

> **État du migrateur (07/10/2026)** : ✅ Fait — chaque sélecteur est aussi
> évalué sur l'architecture propre de la vue héritée et de ses ancêtres. Les
> vues sœurs restent utiles pour détecter les ajouts disponibles, mais leur
> remplacement d'une ancre ne produit plus de faux positif.

- Module : `additional_salesperson`. « filter[@name='my_sale_orders_filter'] not found in the combined view sale.view_sales_order_filter » : le filtre existe dans la vue de base ; seule la vue fille `sale_order_view_search_inherit_quotation` le remplace.
- **Correction proposée** : valider l'ancre sur la vue héritée **seule** (plus les vues dont le module dépend), pas sur la vue combinée avec toutes les vues filles.

## 44. 🟡 Faux positif : `default_get()` « sans méthode parente »

> **État du migrateur (07/10/2026)** : ✅ Corrigé — les méthodes publiques de
> base de l'ORM, dont `default_get`, sont héritées par tous les modèles indexés.
> Les méthodes des mixins d'addons restent obtenues depuis leurs sources.

- Module : `easi_document_on_line`. « document.widgets.default_get() calls super(), but no parent method with that name exists in the indexed target ».
- `default_get` est une méthode de `BaseModel` : le nouveau contrôle (n° 42) n'indexe pas les méthodes de `BaseModel` / `Model` / `TransientModel` / `AbstractModel`.
- **Correction proposée** : ajouter les méthodes de `odoo/orm/models.py` (et des mixins de base, `mail.thread`…) aux parents connus de chaque modèle.

## 45. 🟠 `documents.document` : les dossiers sont des documents depuis la 18

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — à partir de
> la 18, un `Many2one` ou `Many2many` vers `documents.document` sans domaine
> portant sur `type` est signalé. Les références au modèle supprimé
> `documents.folder` restent couvertes par le contrôle générique des modèles.

- Module : `easi_document_on_line`. Un `Many2one("documents.document")` propose aussi les dossiers en 20 (`type = 'folder'`), sans erreur.
- **Correction proposée** : TODO 🟠 sur les `Many2one` / `Many2many` vers `documents.document` sans domaine sur `type`, et sur les usages de `documents.folder` (supprimé).

## 46. 🟡 Champ lu sur un modèle dynamique (`self.env[active_model]`)

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — l'accès par
> attribut à un champ d'un recordset issu de `env[<expression dynamique>]` est
> signalé avec la forme `record["champ"]`. Une mise à jour `x2many += record`
> recommande une collecte des identifiants suivie d'un unique `Command.set`.
> Ces cas restent des avertissements car le modèle et le type du champ ne sont
> pas connaissables statiquement dans le cas général.

- Module : `easi_document_on_line`. `self.env[context["active_model"]].browse(...).document_ids` et `rec.document_ids += doc.file_id` : avertissements PyCharm (« Unresolved attribute reference for class 'BaseModel' », signature x2many).
- **Correction proposée** : sur un enregistrement issu de `self.env[<variable>]`, proposer `record["champ"]` ; remplacer `x2many += record` (dans une boucle, après `Command.clear()`) par un seul `[Command.set(ids)]`.

## 47. 🟡 Domaine « sans dossier » proposé sur un champ de stockage

> **État du migrateur (07/10/2026)** : ✅ Faux positif corrigé — le contrôle
> suit maintenant les champs réellement utilisés dans les architectures de
> vues, y compris le modèle des lignes d'une sous-vue `One2many`. Une relation
> de stockage absente des vues n'est plus traitée comme un sélecteur. Un domaine
> XML portant déjà sur `type` est également reconnu.

- Module : `easi_supplierinfo`. Les nouvelles règles (n° 45, 46) ont bien vu l'assistant. Mais le TODO « add a domain excluding folders » sort aussi sur `product.supplierinfo.document_ids`, un `Many2many` de stockage qui n'est pas affiché pour choisir (le choix se fait dans l'assistant).
- **Correction proposée** : ne signaler que les champs affichés dans une vue sans domaine, ou baisser en 🟡 quand le champ n'apparaît dans aucune vue.

## 48. 🟡 Assistant déclaré en `models.Model`

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — un modèle
> persistant explicitement nommé est signalé comme assistant probable lorsque
> plusieurs indices concordent : action formulaire `target="new"`, méthode
> `default_get()` et/ou `One2many` vers un modèle transitoire. Une simple action
> modale sur un modèle persistant ne suffit pas à produire l'avertissement.

- Module : `easi_supplierinfo`. `supplierinfo.document` (bouton `maj_line`, action `target="new"`, lignes en `TransientModel`) est un `models.Model` : une ligne reste en base à chaque ouverture.
- **Correction proposée** : signaler en 🟡 un `models.Model` utilisé seulement par une action `target="new"`, ou qui a des `One2many` vers des `TransientModel`.

## 49. 🔴 Manifest « illisible » : le n° 29 revient quand la sécurité passe en tête

> **État du migrateur (07/10/2026)** : ✅ Corrigé — la réécriture d'une liste
> multiligne accepte désormais qu'un script officiel ait ajouté le premier
> élément directement après `[`. `ir.access.csv` retrouve sa position d'origine
> et le modèle de manifest est ensuite appliqué sur le contenu final valide.

- Module : `easi_account`. « Manifest could not be inspected (SyntaxError: closing parenthesis '}' does not match opening parenthesis '[' on line 28) ». Manifest final valide, mais **non mis au modèle** (commentaires « scaffold », `summary` vide, listes sur une ligne).
- Cas : `security/ir.model.access.csv` était le **dernier** élément de `data` (sans virgule finale) ; après déplacement/conversion, l'état intermédiaire est invalide.
- **Correction proposée** : faire la conversion `ir.access` sur l'AST (ou relire le manifest après conversion) ; appliquer le modèle sur le manifest final.

## 50. 🟠 `precision_get('Product Unit of Measure')` non converti

> **État du migrateur (07/10/2026)** : ✅ Corrigé automatiquement — le renommage
> couvre maintenant `precision_get(...)`, `dp.get_precision(...)` et le champ
> `name` des enregistrements XML `decimal.precision`, sans modifier les textes
> homonymes d'autres modèles.

- Module : `easi_account`. La règle n° 15 convertit `digits='Product Unit of Measure'`, pas `precision_get('Product Unit of Measure')`. En 20, le nom n'existe plus : `precision_get` renvoie **2 par défaut**, sans erreur.
- **Correction proposée** : même renommage dans `precision_get(...)`, `dp.get_precision(...)` et `decimal.precision` en XML.

## 51. 🟡 Champ HTML complété par `+=` avec du texte

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — un `+=` sur
> un champ réellement indexé comme `fields.Html` avertit du comportement de
> `Markup` et recommande une construction unique avec échappement des valeurs.
> La balise incorrecte `</br>` est signalée séparément avec `<br>` / `<br/>`.

- Module : `easi_account`. `wiz.message_html += "</br> - %s" % ...` : la valeur lue est un `Markup`, le texte ajouté est **échappé**. Existait en 17.
- **Correction proposée** : signaler (🟡) les `+=` sur un champ `fields.Html` ; proposer de construire la chaîne puis d'affecter une fois. Signaler aussi la balise `</br>`.

## 52. 🔴 `product_uom` non vu dans une expression génératrice

> **État du migrateur (07/10/2026)** : ✅ Corrigé — les générateurs et
> compréhensions propagent maintenant le modèle de leur itérable, y compris via
> un alias de `self.filtered(...)`. `_origin` conserve également le modèle du
> record. Les deux accès du cas réel sont renommés en `uom_id`.

- Module : `easi_no_recompute_on_polines`. `rec.product_uom == rec._origin.product_uom for rec in draft_lines` (dans `purchase.order.line`, `draft_lines = self.filtered(...)`) : rapport « Risque aucun ».
- La règle du n° 34 ne suit pas le type de `rec` dans une expression génératrice ni à travers `self.filtered(...)`.
- **Correction proposée** : dans une classe `_inherit = "purchase.order.line"`, les variables issues de `self`, `self.filtered(...)`, `for x in self` (et les générateurs) sont du même modèle ; à défaut, signaler tout `.product_uom` dans un module qui dépend de `purchase`/`sale`/`stock`.

## 53. 🟡 Surcharge d'un calcul standard dont les dépendances ont changé

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — l'index cible
> conserve les dépendances de chaque méthode. Une surcharge `_compute_*` dont
> les `@api.depends` diffèrent de la méthode cible liste les dépendances
> manquantes et supplémentaires pour revue.

- Module : `easi_no_recompute_on_polines`. `_compute_price_unit_and_date_planned_and_name` dépend en 20 de `order_id.partner_id` (et gère `technical_price_unit`) : la surcharge bloque ce nouveau recalcul, sans erreur.
- **Correction proposée** : quand une méthode `_compute_*` surchargée a des `@api.depends` différents entre source et cible, TODO 🟡 avec la différence.

## 54. 🟡 En-têtes de licence / copyright gardés sur les modules internes

> **État du migrateur (07/10/2026)** : ✅ Corrigé — hors OCA, les en-têtes
> `Copyright`, `License`, `@author` et `Part of Odoo` sont retirés au début des
> fichiers Python et du manifest. Le contenu des modules OCA reste intact.

- Module : `easi_no_recompute_on_polines`. `# License AGPL-3.0 or later (...)` reste en tête de `__manifest__.py` et des `__init__.py`. Même cas avant : en-têtes Akretion (`easi_account_payment_term_bank`, `easi_account`), « Part of Odoo » (`easi_document_on_line`), « Copyright 2026 ST OF » (`sale_order_block_duplicate_product`), retirés à la main.
- Règle de l'équipe : pas d'en-tête de licence ni de copyright dans les modules internes (la licence est dans le manifest).
- **Correction proposée** : option (activée par défaut hors OCA) qui retire les commentaires `# Copyright …`, `# License …`, `# @author …`, `# Part of Odoo …` en tête des fichiers Python et du manifest. Jamais sur les modules OCA.

## 55. 🟡 Lignes vides en trop après le retrait d'un import

> **État du migrateur (07/10/2026)** : ✅ Corrigé — le nettoyage Ruff applique
> aussi les règles d'imports, puis un passage final retire les lignes vides en
> tête et limite les blocs vides consécutifs. Deux lignes restent entre imports
> et classe, conformément au format Python.

- Module : `easi_no_recompute_on_polines`. Après le retrait de `from itertools import groupby`, il reste 3 lignes vides entre l'en-tête et `from odoo import models` ; `ruff format` ne les réduit pas.
- **Correction proposée** : après le retrait d'imports inutilisés, réduire les lignes vides consécutives du bloc d'imports (au plus 1 entre deux groupes), ou lancer `ruff check --select I --fix` avant `ruff format`.

## 56. 🟠 `product_uom` non suivi sur la valeur de retour de `super()`

> **État du migrateur (07/10/2026)** : ✅ Corrigé — une valeur affectée depuis
> `super().<méthode>(...)` reçoit le modèle de `self` lorsqu'elle est ensuite
> itérée. Les relations imbriquées sont alors résolues normalement. Le cas réel
> produit six renommages sur six, sans supposer que tous les retours de `super()`
> sont des recordsets.

- Module : `stof_account_reversal`. 4 `sale_line.product_uom` renommés sur 6. Les 2 oubliés sont dans `_reverse_moves` : `retour = super()._reverse_moves(...)`, `for move in retour`, `for line in move.invoice_line_ids`, `for sale_line in line.sale_line_ids`.
- La règle n° 52 suit maintenant les générateurs, mais pas le type de la valeur renvoyée par `super()` (même modèle que `self` ici).
- **Correction proposée** : `x = super().<méthode>(...)` dans une classe `_inherit = M` → `x` est de type `M` quand la méthode standard renvoie `self`-like (ou par défaut) ; ou plus simple : dans un module qui dépend de `sale`, renommer `sale_line.product_uom` dès que la variable vient de `.sale_line_ids`.

## 57. 🟡 Calcul standard remplacé : un point d'extension existe en 20

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — l'index cible
> conserve les appels vers les hooks `_prepare_*`, `_affects_*` et
> `_get_*_domain`. Lorsqu'une surcharge remplace le standard sans `super()`, le
> rapport propose les hooks directs et ceux accessibles à un niveau. Pour ce
> module : `_prepare_qty_invoiced` et `_affects_qty_invoiced`.

- Module : `stof_account_reversal`. `_compute_qty_invoiced` réécrit en entier (copie du standard 17 + une condition). En 20, le standard passe par `_prepare_qty_invoiced()` et offre `_affects_qty_invoiced(invoice_line)`.
- Le TODO 🟠 sur les `@api.depends` (n° 53) est bien sorti, mais sans proposer le point d'extension.
- **Correction proposée** : quand une surcharge ne fait pas `super()` et que la cible a un « hook » documenté (`_affects_*`, `_prepare_*`, `_get_*_domain`…), le citer dans le TODO.

## 58. 🟡 Apostrophe doublée façon SQL dans une chaîne Python

> **État du migrateur (07/10/2026)** : ✅ Corrigé — la forme non ambiguë
> (deux littéraux `'…'` simples collés sans espace, lettre de part et d'autre)
> est réécrite en `'d\'entrée'` dans le manifest et le code Python, avant la
> normalisation : le manifest affiche bien « d'entrée » et non plus « dentrée ».
> Les autres jonctions (guillemets doubles, préfixes) restent signalées.

- Module : `edi_data_model`. `'méthodes d''entrée'`, `'l''envoi'` : Python colle les deux chaînes (« dentrée », « lenvoi »). Le migrator a bien gardé la valeur réelle en réécrivant les guillemets, mais sans le signaler.
- **Correction proposée** : avec `tokenize`, repérer deux chaînes collées dont la première se termine par une lettre et la seconde commence par une lettre (`'d''e'`) ; TODO 🟡 « apostrophe probablement perdue ».

## 59. 🟡 Droits sur des modèles abstraits

> **État du migrateur (07/10/2026)** : ✅ Détection implémentée — les fichiers
> `ir.model.access.csv` historiques et `ir.access.csv` Odoo 20 sont comparés à
> l'index des modèles. Une ligne visant un `AbstractModel` est signalée, avec
> prise en charge du nom technique et de l'XML ID `model_*`.

- Module : `edi_data_model`. `ir.access` sur `edi.model.input` et `edi.model.output`, qui sont des `AbstractModel` : sans effet.
- **Correction proposée** : signaler (🟡) les lignes de droits sur un `AbstractModel`.

## 60. 🟡 Séquence d'échappement invalide (`"\."`)

> **État du migrateur (07/10/2026)** : ✅ Corrigé — une chaîne sans
> préfixe dont toutes les séquences `\x` sont invalides devient brute (`r"…"`),
> après contrôle que la valeur est identique. Si elle mélange séquences valides
> et invalides, elle est signalée.

- Module : `edi_ftp_data_model`. `help="… ^commande.*\.txt$"` : `SyntaxWarning: invalid escape sequence '\.'` en Python 3.12 (erreur dans une future version).
- **Correction proposée** : passer en chaîne brute (`r"…"`) toute chaîne contenant une séquence invalide, sans autre `\` valide (`\n`, `\t`…) ; sinon TODO 🟡. Vérifiable avec `compile(..., warnings as errors)`.

## 61. 🟡 Clés vides gardées dans le manifest

> **État du migrateur (07/10/2026)** : ✅ Corrigé — `data` vide est
> retiré comme `demo`/`assets`, et les entrées vides d'un dictionnaire
> (`external_dependencies: {"python": []}`) sont retirées ; le dictionnaire
> disparaît s'il ne reste rien.

- Module : `edi_ftp_data_model`. `"external_dependencies": {"python": []}` et `"data": []` gardés (règle du modèle : clés vides absentes ; voir n° 30).
- **Correction proposée** : retirer aussi les dictionnaires dont toutes les listes sont vides.

## 62. 🟡 Paramètres de champ sans effet, avertis par Odoo 20

> **État du migrateur (07/10/2026)** : ✅ Détection — `tracking=`
> sur un modèle dont toute la lignée est connue de l'index et n'hérite pas de
> `mail.thread` est signalé. Un manifest sans `author` est complété avec
> `--default-author "…"` (jamais une valeur existante remplacée) ; sans cette
> option, il est seulement signalé.

- Vu au chargement : `account.payment.term.partner_bank_id: unknown parameter 'tracking'` (`easi_account_payment_term_bank`, modèle sans `mail.thread`) ; `Missing 'author' key` (`sale_order_block_duplicate_product`).
- **Correction proposée** : signaler `tracking=` sur un champ dont le modèle n'hérite pas de `mail.thread` ; ajouter `author` (valeur par défaut de l'équipe) quand il manque.

## 63. 🟡 Commentaire orphelin après le retrait d'une clé vide

> **État du migrateur (07/10/2026)** : ✅ Corrigé — les commentaires attachés
> à une clé retirée par la normalisation (au-dessus ou sur la même ligne) sont
> retirés avec elle et repris dans le journal ; les autres commentaires métier
> restent en place.

- Module : `edi_webservice_data_model`. `# se poser peut être la question de impacket plutôt que pysmb` était au-dessus de `external_dependencies` (vide) ; la clé est retirée, le commentaire reste seul avant `}`.
- **Correction proposée** : quand une clé est retirée, retirer aussi les commentaires qui lui sont attachés (lignes juste au-dessus).

## 64. 🟠 « Dépendance circulaire » : 1 TODO par ligne, sans plan de déplacement

> **État du migrateur (08/10/2026)** : ✅ Corrigé — le rapport regroupe les
> dépendances circulaires par méthode, liste les modèles/champs concernés et
> propose de garder un hook neutre dans la base puis de le surcharger dans le
> fournisseur ou dans un module de liaison.

- Module : `edi_worker`. 31 TODO 🔴 « circular dependency; move this code into edi_platform » (`self.env['edi.task']`, `edi.file`, `edi.configuration`, `file_mapping`). Le diagnostic est juste (PyCharm signale les mêmes symboles) : le code du mode local a été déplacé dans `edi_platform` / `edi_platform_transform`, avec des méthodes vides dans `edi_worker`.
- Mais 31 lignes pour 6 méthodes : difficile à lire.
- **Correction proposée** : regrouper par **méthode** (« `_send_local_files` utilise edi.task, edi.file → à déplacer dans edi_platform, qui étend déjà edi.worker.config ») ; dire si le module cible étend déjà le modèle ; proposer le squelette (méthode vide dans le module de base + surcharge dans le module cible).

## 66. 🔴 Bugs d'exécution non vus : `__last_update`, texte + octets

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée —
> `__last_update` n'est plus considéré comme un champ magique et ses emplois
> sous forme de chaîne sont signalés. Une concaténation texte + `.content`
> propose `.text` ou un décodage explicite.

- Module : `edi_worker`. `.sorted("__last_update")` (champ magique supprimé en 17) et `"…" + response.content` (`bytes`, `requests`) : vus par PyCharm, pas par le migrator.
- **Correction proposée** : remplacer `__last_update` par `write_date` (ou `id`) partout (domaines, `sorted`, `mapped`, vues) ; signaler `str + response.content`.

## 65. 🟡 Calcul qui vide un champ saisi : sans effet à la création

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — pour chaque
> champ déclarant `compute=`, les affectations d'autres champs dans la méthode
> sont signalées avec le risque particulier pendant `create`.

- Module : `edi_ftp_data_model` / `edi_worker`. `_encrypt_input_ftp_password` met `input_ftp_password = False` dans le calcul de `input_ftp_password_encrypted` ; à la création, la valeur saisie l'emporte : mot de passe stocké en clair (11 en prod).
- **Correction proposée** : signaler (🟡) l'écriture d'un **autre** champ, non calculé, dans une méthode `_compute_*` / `compute=`.

## 67. 🔴 `get_param` / `set_param` supprimés (Odoo 20)

> **État du migrateur (08/10/2026)** : ✅ Correction automatique quand le type
> est prouvé par une conversion, une valeur constante, une comparaison à
> `"True"` ou une valeur par défaut. Un `get_param` sans contexte devient
> `get_str`; les écritures de type dynamique restent des erreurs à traiter.

- Module : `edi_worker` (vu par PyCharm). `self.env["ir.config_parameter"].sudo().get_param(...)` : méthode supprimée (commit `a4f2879697a7`), remplacée par `get_str`, `get_int`, `get_float`, `get_bool` et `set_*`. 128 usages dans 21 modules Stof.
- **Correction proposée** : `int(get_param(k) or 0)` → `get_int(k)` ; `get_param(k) or d` → `get_str(k, d)` ; `get_param(k) == "True"` → `get_bool(k)` ; sinon `get_str(k)` + TODO 🟠 sur le type. Idem `set_param` → `set_str`/`set_int`…

## 68. 🔴 Champs `Binary` : `BinaryValue` au lieu de base64

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — les appels
> base64 portant sur un champ `Binary`/`Image` résolu et `_file_read` avec un
> argument sont signalés avec les adaptations `BinaryValue` correspondantes.

- Module : `edi_worker`. `base64.b64decode(self.file)` sur un `fields.Binary` : en 20 la valeur est le contenu **brut** (`BinaryValue`, commit `41fe2ebdb9cc`) → « Incorrect padding », intercepté : lecture CSV et aperçu vides, **sans erreur**. Écrire des `bytes` lève `TypeError: use BinaryValue instead of bytes` (le `str` base64 reste accepté).
- `ir.attachment._file_read(store_fname)` : plus d'argument, renvoie un `BinaryValue`.
- 96 `b64decode`/`b64encode` dans 21 modules Stof (EDI, imports).
- **Correction proposée** : sur un champ `Binary` connu, `base64.b64decode(rec.f)` → `rec.f.content` ; `rec.f = base64.b64encode(x)` → `rec.f = BinaryBytes(x)` (ou `.decode()`) ; TODO 🔴 sinon. `_file_read(x)` → `_file_read()`.

## 69. 🟡 Faux positifs : constantes de classe, `self.pool`, modèle « assistant »

> **État du migrateur (08/10/2026)** : ✅ Corrigé — les constantes en
> majuscules et `pool` font partie des attributs connus. La proposition de
> `TransientModel` est supprimée quand le modèle est relu par `search` ou
> `search_count`.

- Module : `edi_platform`. 🔴 « Field edi.platform.alert.SEVERITY_INFO does not exist » (constante de classe `SEVERITY_INFO = "INFO"`) ; 🔴 « Field res.config.settings.pool » (`self.pool`, le registre) ; 🟠 `edi.jwt.token` « looks like a wizard » (ouvert en `target="new"`, mais les jetons doivent rester en base).
- **Correction proposée** : ignorer les attributs de classe non-champs (`NOM = valeur` en majuscules) et les attributs de `BaseModel` (`pool`, `env`, `ids`…) ; ne proposer `TransientModel` que si aucun `search`/`search_count` ne relit le modèle.

## 70. 🔴 `mail.compose.message.res_id` / `_onchange_template_id_wrapper`

> **État du migrateur (08/10/2026)** : ✅ Détection complétée — en plus des
> champs absents, les appels de méthodes sur un modèle résolu sont maintenant
> comparés aux méthodes de la cible. La transformation de `res_id` reste à
> relire car la construction attendue de `res_ids` dépend de l'appelant.

- Module : `edi_platform`. Le formulaire d'envoi de mail n'a plus `res_id` (→ `res_ids`, texte) ni `_onchange_template_id_wrapper` (le corps se calcule depuis le modèle). Déjà le cas en 17. Le migrator a bien signalé `res_id` (🔴), pas la méthode.
- **Correction proposée** : `"res_id": x.id` → `"res_ids": str(x.ids)` sur `mail.compose.message` ; retirer `_onchange_template_id_wrapper()`.

## 71. 🔴 `mail_tracking_value` en SQL brut

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — un
> `cr.execute` contenant cette table produit une erreur et propose ORM/cascade
> ou un garde `table_exists()`.

- Module : `edi_platform`. `DELETE FROM mail_tracking_value …` dans une purge : en 20, `mail.tracking.value` est dans le module optionnel `mail_tracking` (commit `dd0c51ec1855`). Sans lui, la table n'existe pas.
- **Correction proposée** : signaler (🔴) les noms de tables de modèles déplacés ou supprimés dans le SQL brut (`cr.execute`) ; pour celle-ci, proposer de s'appuyer sur la cascade ou de tester `table_exists`.

## 72. 🟡 Widget de champ inexistant, CSS invalide

> **État du migrateur (08/10/2026)** : ✅ Correction sûre implémentée — dans
> les architectures de vues, `widget="kanban"` devient `mode="kanban"` et les
> pourcentages CSS doublés sont normalisés. Les actions et commentaires sont
> exclus de cette réécriture.

- Module : `edi_platform`. `<field … widget="kanban">` (aucun widget de champ « kanban » : avertissement console, repli sur le one2many) ; `style="width:200%%"`.
- **Correction proposée** : vérifier `widget=` contre le registre `fields` de la cible ; pour un x2many, proposer `mode="kanban"`.

## 73. 🟡 Contrôleur `auth="none"` : `message_post` sans utilisateur

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée —
> `message_post` et `activity_schedule` dans une route `auth="none"` sont
> signalés lorsqu'aucun `with_user(...)` n'est présent sur le récepteur.

- Module : `edi_platform`. Dans une route `auth="none"`, `request.env.user` est vide ; en 20, `message_post` appelle `self.env.user._is_public()` → « Expected singleton: res.users() ».
- **Correction proposée** : signaler (🟠) `message_post`, `activity_schedule`… dans une route `auth="none"` sans `with_user(...)` ; proposer `with_user(SUPERUSER_ID)`.

## 74. 🔴 `active_id` dans le contexte d'un champ de vue

> **État du migrateur (08/10/2026)** : ✅ Correction automatique — `active_id`
> devient `id` uniquement dans les attributs d'expression d'une architecture
> `ir.ui.view`. Le contexte d'une action reste inchangé.

- Module : `edi_platform_transform`. `<field name="values_ids" context="{'default_column_id': active_id}"/>` dans un formulaire : refusé en 20 à l'installation (« Incohérence des droits d'accès … le champ active_id n'existe pas »). Non signalé par le migrator.
- `active_id` reste valide dans le `domain` / `context` d'une **action** (`ir.actions.act_window`).
- **Correction proposée** : dans `arch` (attributs `context`, `domain`, `invisible`…), remplacer `active_id` par `id` ; ne pas toucher aux champs d'actions.

## 75. 🟠 Écriture de base64 en `bytes` dans un champ `Binary` / `Image`

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — les
> affectations directes et valeurs de dictionnaires `create`/`write` sont
> reliées au type du champ et proposent `BinaryBytes` ou une chaîne décodée.

- Module : `edi_platform_transform`. `rec.file_structure = base64.b64encode(png)`, `create({"file": base64.b64encode(data)})` : en 20, `TypeError: use BinaryValue instead of bytes`.
- **Correction proposée** (complète le n° 68) : ajouter `.decode()` (ou `BinaryBytes(data)`) quand on écrit `b64encode(...)` dans un champ `Binary`/`Image` ou dans un `create`/`write`.

## 76. 🟡 Calcul dans un mixin qui lit un champ des modèles concrets

> **État du migrateur (08/10/2026)** : ✅ Diagnostic enrichi — si le récepteur
> est abstrait, l'erreur liste les modèles concrets héritiers qui possèdent le
> champ et son type dans chacun, afin de choisir où déplacer le calcul.

- Module : `edi_platform_transform`. `edi.model.transform._compute_transform_partner_id` lit `configuration_id`, défini en many2one sur `edi.task` et en texte sur `edi.worker.config`. 🔴 « Field edi.model.transform.configuration_id does not exist » : juste, mais la correction (déplacer le calcul dans le modèle concret) n'est pas proposée.
- **Correction proposée** : dans ce cas, lister les modèles concrets qui héritent du mixin et le type du champ dans chacun.

## 77. 🔴 Widget `DynamicModelFieldSelectorChar` supprimé

> **État du migrateur (08/10/2026)** : ✅ Renommage automatique vers
> `field_selector`, limité aux architectures de vues Odoo 20 et conservant les
> options existantes.

- Module : `edi_platform_transform` (et `edi_generic`). Renommé `field_selector` en 20 (commit `0ab72b14a4a3`), mêmes options (`model`, `follow_relations`). Sans renommage : avertissement console et simple champ texte.
- **Correction proposée** : renommage automatique ; plus largement, vérifier chaque `widget=` contre le registre `fields` de la cible (voir n° 72).

## 78. 🟠 `create(self, vals)` sans `@api.model_create_multi`

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — toute
> surcharge de modèle nommée `create` sans le décorateur reçoit un diagnostic
> demandant `vals_list` et le traitement de chaque dictionnaire.

- Module : `edi_platform_transform`. La surcharge reçoit un dict ou une liste selon l'appelant ; avec une liste, `"clé" in vals` est faux et le code saute.
- **Correction proposée** : ajouter `@api.model_create_multi`, renommer en `vals_list` et boucler.

## 79. 🟡 Bugs Python repérables statiquement

> **État du migrateur (08/10/2026)** : ✅ Détections implémentées pour `raise`
> d'une chaîne, `env.get(...)` utilisé comme booléen, `isinstance` d'une valeur
> avec une classe `fields.*` et les `except:` nus.

- Module : `edi_platform_transform`. `raise f"..."` (lever une chaîne → `TypeError`) ; `if not env.get(model):` (recordset vide = faux, la boucle ne fait jamais rien) ; `isinstance(rec.champ, fields.One2many)` (valeur ≠ champ, toujours faux) ; `except:` nus.
- **Correction proposée** : règles dédiées (🟠) : `raise` d'une chaîne → `UserError(...)` ; `env.get(x)` testé en booléen → `x in env` ; `isinstance(…, fields.X)` sur une valeur → `self._fields[n].type`.

## 80. 🟡 Dépendance manquante pour un widget

> **État du migrateur (08/10/2026)** : ✅ Détection implémentée — le registre
> extensible des widgets fournisseurs connaît `section_and_note_one2many` et
> exige `account` dans la fermeture des dépendances lorsque l'index est complet.

- Module : `edi_platform_transform`. `widget="section_and_note_one2many"` vient d'`account`, absent des dépendances.
- **Correction proposée** : pour chaque widget, retrouver le module qui l'enregistre et vérifier qu'il est dans les dépendances.

## 81. 🟡 Ruptures `Binary` signalées mais non corrigées automatiquement

> **État du migrateur (08/10/2026)** : ✅ Correction automatique implémentée —
> lorsque l'index prouve le type `Binary`/`Image`, un décodage base64 direct
> devient une lecture `.content` et une écriture base64 directe devient
> `BinaryBytes(...)`. L'import est ajouté une seule fois ; le nettoyage habituel
> retire ensuite `base64` s'il n'est plus utilisé. Les formes ambiguës restent
> seulement signalées.

- Module : `edi_worker_enable_ftp`. Les nouvelles règles signalent bien `base64.b64decode(file.file)` et `create({"file": base64.b64encode(x)})` (🔴), mais laissent la correction à faire.
- **Correction proposée** : quand le champ est connu comme `Binary` : `io.BytesIO(base64.b64decode(r.f))` → `io.BytesIO(r.f.content)` ; `"f": base64.b64encode(x)` → `"f": BinaryBytes(x)` (+ import `odoo.tools.binary.BinaryBytes`), puis retirer l'import `base64` s'il devient inutile.

## 82. 🟡 `self.<champ>` dans une boucle `for task in self`

> **État du migrateur (08/10/2026)** : ✅ Correction automatique — dans une
> méthode de modèle, les lectures d'un champ indexé via `self` à l'intérieur de
> `for variable in self` utilisent la variable de boucle. Les méthodes,
> `self.env`, les écritures et les méthodes qui imposent `ensure_one()` sont
> exclues.

- Module : `edi_worker_enable_ftp`. `if self.input_ftp_delete_after_download:` dans `for task in self:` → erreur « Expected singleton » dès que plusieurs enregistrements.
- **Correction proposée** : dans le corps d'un `for x in self:`, signaler (🟠) les lectures de champ sur `self` et proposer `x.<champ>`.

## 83. 🔴 `record.binary_field.decode()` change de sens en silence

> **État du migrateur (08/10/2026)** : ✅ Correction automatique implémentée —
> un `.decode()` sans encodage, ou avec UTF-8/ASCII constant, sur un champ
> `Binary`/`Image` prouvé devient `.to_base64()`. Le type du record est aussi
> propagé depuis les arguments nommés des appels vers les paramètres des
> méthodes. Un encodage dynamique ou métier reste inchangé et reçoit un TODO
> expliquant `.content.decode(encoding)`.

- Module : `edi_worker_enable_webservice`. En 17, `file.file.decode()` donnait la **chaîne base64** (envoyée telle quelle dans un JSON). En 20, `BinaryValue.decode()` renvoie le **texte brut** : le service distant reçoit autre chose, et un fichier non UTF-8 plante. Rapport : « aucun risque ».
- **Correction proposée** : sur un champ `Binary`, `x.decode()` (sans encodage, ou `"utf-8"`/`"ascii"`) → `x.to_base64()` pour garder la valeur de la 17 ; TODO 🟠 si un encodage métier est passé (`x.decode(self.encoding)` : vouloir le texte brut est alors probable).

## 84. 🔴 `self.env.cr.clear()` supprimé

> **État du migrateur (08/10/2026)** : ✅ Correction automatique lorsqu'un
> `cr.clear()`/`reset()` suit immédiatement un `commit()` : remplacement par
> `env.transaction.clear()`. Dans les autres positions, un TODO rappelle aussi
> `cr.precommit.clear()` afin de ne pas supprimer implicitement des callbacks.

- Module : `edi_generic`. `Cursor.clear()` et `Cursor.reset()` n'existent plus en 20 (commit `832d8714a849`) → `AttributeError`. Non signalé.
- **Correction proposée** : `cr.clear()` → `env.transaction.clear()` (+ `cr.precommit.clear()` si l'appel n'est pas juste après un `commit`).

## 85. 🔴 `"type": "tree"` dans une vue créée par code

> **État du migrateur (08/10/2026)** : ✅ Correction structurée — les
> dictionnaires passés à `ir.ui.view.create/write` (ou contenant `arch`) passent
> de `type=tree` à `list`; les actions résolues convertissent `view_mode` sans
> toucher les autres dictionnaires métier.

- Module : `edi_generic`. Le migrator a converti `<tree>` → `<list>` dans une chaîne Python, mais pas `"type": "tree"` du dict passé à `ir.ui.view.create` → « Wrong value for ir.ui.view.type: 'tree' ».
- **Correction proposée** : dans un `create`/`write` sur `ir.ui.view` (ou un dict avec `arch`/`arch_base`), `"type": "tree"` → `"list"` ; idem `view_mode` contenant `tree` dans `ir.actions.act_window` créées par code.

## 86. 🟠 Appels explicites `x.name_get()` / faux positifs `get_external_id`

> **État du migrateur (08/10/2026)** : ✅ Corrigé — `get_external_id` et
> `_get_external_ids` sont connus sur `BaseModel`. La forme singleton prouvée
> `record.name_get()[0]` devient `(record.id, record.display_name)`; les appels
> dont la cardinalité n'est pas démontrée restent à revoir.

- Module : `edi_generic`. `column.name_get()[0]` (clé de cache) non converti ; le TODO ne vise que la **définition** de `name_get`. Inversement, 5 TODO 🔴 « get_external_id does not exist » sont faux : la méthode existe en 20 (`models.py:5200`).
- **Correction proposée** : `x.name_get()[0]` → `(x.id, x.display_name)` (ou une méthode dédiée si `name_get` est surchargé) ; ajouter `get_external_id`, `_get_external_ids` aux méthodes connues de `BaseModel`.

## 87. 🟠 Libellé de champ « Tree » renommé en « List » : traduction perdue

> **État du migrateur (08/10/2026)** : ✅ Corrigé — les remplacements textuels
> généraux de « tree view » ont été retirés. Seuls les balises, sélecteurs,
> modes et dictionnaires techniques sont migrés ; les libellés et textes
> traduisibles restent identiques.

- Module : `edi_generic`. `fields.Many2one("ir.ui.view", "EDI Tree View")` → `"EDI List View"`. Le `.po` n'a que `msgid "EDI Tree View"` → le libellé français « Vue arborescente EDI » n'est plus appliqué.
- **Correction proposée** : ne renommer `tree` → `list` que dans les éléments techniques (`<tree>`, `view_mode`, `"type"`), jamais dans les libellés (`string`, 2ᵉ argument positionnel d'un champ, textes `_()`).

## 88. 🟠 Champ `name` copié avec « (copy) » en 20 : non signalé

> **État du migrateur (08/10/2026)** : ✅ Correction automatique — sur un
> modèle explicitement nommé, un `fields.Char` simple appelé `name` ou `x_name`
> reçoit `copy=True` s'il ne définit pas déjà sa politique de copie. Les champs
> calculés, liés, dépendants de la société ou à traduction callable restent
> inchangés, ainsi que les modèles SQL `_auto = False`.

- Module : `easi_mrp` (et `edi_generic`, `edi_platform_transform` déjà migrés). Odoo 20 (commit `b84ffce402d3`) ajoute `copy=mark_as_copy("name")` à tout `fields.Char` nommé `name`/`x_name` sans `copy=` ni traduction. Les `copy()` et les lignes copiées par un One2many `copy=True` reçoivent « (copy) » : noms techniques modifiés sans erreur.
- **Correction proposée** : signaler en 🟠 les `name = fields.Char(...)` sans `copy=` dont le modèle est copié (cible d'un One2many `copy=True`, ou `.copy(` sur le modèle) ; proposer `copy=True` pour garder le comportement 17.

## 89. 🟡 `copy=True` ajouté sur les modèles SQL (`_auto = False`) / `is_done` non signalé

> **État du migrateur (08/10/2026)** : ✅ Corrigé — les modèles `_auto = False`
> sont exclus de la règle #88. Les chaînes SQL sont rapprochées des règles de
> champs supprimés chargées pour la migration ; une colonne qualifiée par sa
> table ou son alias produit une erreur avec la provenance de la règle.

- Module : `easi_sale_late`. La règle « (copy) » (#88) ajoute `copy=True` au `name` de vues SQL en lecture seule : inutile, jamais copiées. Par ailleurs, `stock_move.is_done` (supprimé en 20) utilisé dans une requête SQL brute n'est pas signalé.
- **Correction proposée** : ignorer les modèles `_auto = False` pour #88 ; signaler en 🟠 les colonnes supprimées connues (`is_done`…) dans les chaînes SQL des `_table_query` / `init()`.

## 90. 🔴 Script Odoo `18.1-00-sql-constraint.py` en échec si le message est `_("…")`

> **État du migrateur (08/10/2026)** : ✅ Les appels `_("texte")` utilisés
> comme message d'un `_sql_constraints` sont remplacés de façon structurée par
> le littéral équivalent avant la conversion. Cela fonctionne avec le script
> officiel embarqué comme avec le convertisseur de secours ; les autres appels
> de traduction restent inchangés.

- Module : `easi_transport`. `ValueError: malformed node or string` (`ast.literal_eval` sur l'appel `_()`) : les `_sql_constraints` restent tels quels, ignorés en 20 → contraintes d'unicité perdues sans erreur.
- **Correction proposée** : avant le script, remplacer `_("texte")` par `"texte"` dans les `_sql_constraints` (le message de `models.Constraint` est traduit par Odoo) ; à défaut, laisser le TODO 🔴 (déjà fait).

## 91. 🔴 Bouton `toggle_active` non signalé (méthode supprimée en 20)

> **État du migrateur (08/10/2026)** : ✅ Dans une vue, un bouton visible quand
> `active` est vrai devient `action_archive` et celui visible quand `active` est
> faux devient `action_unarchive`. Une visibilité plus complexe reste inchangée
> et produit une erreur à traiter. Les appels Python résolus sont couverts par
> le contrôle des méthodes absentes de l'index cible.

- Module : `stof_accords_galec`. `<button name="toggle_active" type="object">` (Archiver / Restaurer) : `toggle_active` supprimé (commit Odoo `37ba3b162e7d`) → erreur au clic. Aucun TODO.
- **Correction proposée** : bouton visible si `not active` / `active` → `action_archive` / `action_unarchive` ; appels Python `.toggle_active()` → signaler en 🔴 (le sens dépend de l'état).

## 92. 🟡 Manifest : `summary` non nettoyé, `description` du modèle `scaffold` gardée

> **État du migrateur (08/10/2026)** : ✅ Le `summary` est ramené à une ligne
> avec des espaces normalisés. La description exacte générée par le scaffold
> Odoo est retirée ; les descriptions réelles du module restent conservées.

- Modules : `stof_purchase_owner`, `stof_accords_galec`. `summary` réécrit en `"\n        Add purchase owner."` (retours à la ligne et espaces gardés) ; `description` « Long description of module's purpose » (texte du `scaffold`) conservée.
- **Correction proposée** : `strip()` + espaces internes réduits pour `summary` ; retirer `description` si elle vaut le texte du `scaffold` (comme le `summary` vide).

## 93. 🟠 Dépendance `stock_barcode` ajoutée à tort / `product_uom_id` des lignes de mouvement non renommé

> **État du migrateur (08/10/2026)** : ✅ Cause corrigée. `_search()` est
> maintenant connue comme méthode de base, donc une surcharge Enterprise ne
> devient plus son faux fournisseur. Les dépendances Python sous licence
> Enterprise ne sont jamais ajoutées automatiquement : le rapport indique le
> module et le modèle/champ/méthode qui les réclame. Enfin,
> `mapped("relation")` propage le modèle relationnel, ce qui applique bien la
> règle existante `stock.move.line.product_uom_id` → `uom_id` à `pack`.

- Module : `stof_partner_backorder_strategy`. « Added uniquely resolved Python dependency stock_barcode » alors que le module n'utilise rien de `stock_barcode` (Enterprise) → dépendance inutile ajoutée sans être signalée en TODO. Par ailleurs `move_line.product_uom_id` (devenu `uom_id` en 20) n'est pas converti, alors que `move.product_uom` l'est.
- **Correction proposée** : ne jamais ajouter une dépendance Enterprise automatiquement (TODO 🟠 avec le symbole qui l'a déclenchée) ; ajouter `stock.move.line.product_uom_id` → `uom_id` aux renommages de champs.

## 94. 🟡 TODO 🔴 `odoo.osv` restant alors que l'import a été retiré

> **État du migrateur (08/10/2026)** : ✅ Les diagnostics textuels sont
> reconstruits sur les fichiers finaux, après Ruff, le nettoyage qualité et
> pre-commit : un motif supprimé ne reste plus dans le rapport. Le graphe des
> imports du module part désormais du `__init__.py` racine ; les fichiers non
> atteignables sont exclus des analyses et reçoivent un unique TODO 🟠 demandant
> de les importer explicitement ou de retirer le code mort.

- Module : `easi_bom`. `from odoo.osv import expression` inutilisé : retiré par le nettoyage des imports, mais le rapport garde « [20] The odoo.osv package was removed » en 🔴 (risque « élevé » à tort). Idem pour un fichier non chargé (`mrp_production.py`, absent de `__init__.py`) qui reçoit un TODO.
- **Correction proposée** : recalculer les TODO après le nettoyage des imports ; signaler les fichiers Python non importés (🟡) au lieu de leur appliquer des TODO.

## 95. 🔴 Changement de signature de `sale.order._create_invoices` non détecté

> **État du migrateur (08/10/2026)** : ✅ Les signatures des méthodes de la
> cible sont désormais indexées et comparées aux surcharges. Les incompatibilités
> certaines sont des TODO 🔴 avec les deux signatures et le détail des arguments.
> Quand la surcharge ne fait que transmettre ses paramètres au `super()`, que
> les paramètres retirés ne sont utilisés nulle part ailleurs et que les valeurs
> par défaut sont littérales, la signature et l'appel nommé sont corrigés
> automatiquement. Les deux formes rencontrées ici, positionnelle et nommée,
> sont prises en charge.

- Module : `account_move_autosplit_delivery` (0 TODO, risque « aucun »). Odoo 20 (commit `9400a302fba0`) : `_create_invoices(self, final=False, grouped=False)` au lieu de `(self, grouped=False, final=False, date=None)`. La surcharge `super()._create_invoices(grouped, final, date)` plante (argument en trop) et inverse `final` / `grouped`. Même cas dans `easi_sale_auto_discount`.
- **Correction proposée** : comparer la signature des méthodes surchargées avec la cible (paramètres renommés, supprimés, réordonnés) et signaler en 🔴 ; pour ce cas, réécrire en `def _create_invoices(self, final=False, grouped=False)` + `super()._create_invoices(final=final, grouped=grouped)` (ou `*args, **kwargs` comme Odoo).

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
| `easi_oekotex` | Manifest jugé illisible à tort (état intermédiaire), donc non mis au modèle | 29 |
| `easi_account_validation_automatic` | Tâche planifiée qui appelle une méthode absente du module (celle de l'OCR) ; manifest au modèle incomplet | 30, 31 |
| `easi_purchase_minimum` | `product_uom` → `uom_id`, `_select_seller` renvoie un dict, `line.name` sans produit, `min_qty` par défaut à 1 | 34 à 37 |
| `sale_order_block_duplicate_product` | `_()` dans une expression génératrice (texte non traduit) ; 3 faux positifs sur `id` | 38, 39 |
| `additional_salesperson` | Clé `Salesversion` (virgule manquante), surcharge de `_create_lead_partner_data` inexistante ; plantage du rapport | 40 à 43 |
| `easi_document_on_line` | Dossiers proposés comme documents (refonte de `documents` en 18) ; faux positif sur `default_get` ; champ lu sur un modèle dynamique | 44 à 46 |
| `easi_supplierinfo` | Assistant déclaré en `models.Model` (tout le reste signalé) | 47, 48 |
| `easi_account` | Manifest non mis au modèle (fausse erreur de syntaxe), `precision_get('Product Unit of Measure')`, `+=` sur un champ HTML | 49 à 51 |
| `easi_no_recompute_on_polines` | `product_uom` dans une expression génératrice ; dépendances du calcul standard changées ; en-têtes de licence gardés, lignes vides en trop | 52 à 55 |
| `stof_account_reversal` | 2 `product_uom` sur 6 (valeur renvoyée par `super()`) ; point d'extension `_affects_qty_invoiced` non proposé | 56, 57 |
| `edi_data_model` | Rien de bloquant ; apostrophes doublées façon SQL, droits sur des modèles abstraits | 58, 59 |
| `edi_ftp_data_model` | `\.` invalide en Python 3.12 ; clés vides du manifest | 60, 61 |
| `edi_webservice_data_model` | Rien de bloquant ; commentaire orphelin dans le manifest | 63 |
| `edi_worker` | `get_param` supprimé, champs `Binary` en `BinaryValue`, `_file_read`, `__last_update`, texte + octets ; 31 TODO « dépendance circulaire » à regrouper ; calcul qui vide un champ saisi | 64 à 68 |
| `edi_platform` | `get_param` (n° 67), `BinaryValue` en JSON et à la lecture (n° 68), `_onchange_template_id_wrapper`, `mail_tracking_value` en SQL, widget `kanban`, `message_post` en `auth="none"` ; faux positifs (constantes, `self.pool`, jeton « assistant ») | 67 à 73 |
| `edi_platform_transform` | `active_id` dans une vue, base64 en `bytes` écrit dans un `Binary`, `_file_read`, fichier d'exemple en `BinaryValue`, sous-formulaire contact refait en 20 (ancres), widget `DynamicModelFieldSelectorChar`, `create` sans décorateur, `raise` d'une chaîne, `env.get` en booléen, dépendance `account` | 68, 74 à 80 |
| `edi_worker_enable_ftp` | `self.` au lieu de `task.` dans la boucle ; ruptures `Binary` signalées sans correction | 81, 82 |
| `edi_worker_enable_webservice` | `file.file.decode()` : base64 en 17, texte brut en 20 (contenu envoyé modifié) | 83 |
| `edi_generic` | `cr.clear()`, `"type": "tree"` dans une vue créée par code, appels `name_get()`, champ inexistant dans un calcul ; faux positifs `get_external_id` ; libellé « Tree » → « List » | 84 à 87 |
| `easi_mrp` | `name` copié avec « (copy) » en 20, non signalé | 88 |
| `easi_sale_late` | `copy=True` sur vue SQL, `is_done` en SQL brut non signalé | 89 |
| `easi_transport` | script `sql-constraint` en échec sur `_()` | 90 |
| `stof_accords_galec` | `toggle_active` non signalé | 91 |
| `stof_purchase_owner` | `summary` / `description` du manifest non nettoyés | 92 |
| `stof_partner_backorder_strategy` | dépendance `stock_barcode` à tort, `product_uom_id` des lignes | 93 |
| `easi_bom` | TODO `odoo.osv` après retrait de l'import, fichier non chargé | 94 |
| `account_move_autosplit_delivery` | signature de `_create_invoices` non détectée | 95 |

---

# Automatisations possibles

Ce qui a été fait **à la main** sur les modules Stof, et que l'outil pourrait faire seul.
Règle commune : **ne jamais changer le comportement, les identifiants XML ni les textes traduisibles**. Changer un texte source casse sa traduction dans les `.po`.

| # | Automatisation | Exemple (module) | Remarque | État |
|---|---|---|---|---|
| A1 | Ajouter dans `depends` les modules dont le code Python utilise un modèle ou un champ (voir problème 3) | `partner_identification` dans `stof_partner_exchange` | Signaler seulement si le module manquant est OCA / tiers non migré | ✅ Ajout automatique si l'index est complet, le fournisseur unique et non circulaire ; sinon TODO détaillé. |
| A2 | Ajouter `'license': 'LGPL-3'` quand la clé manque | `stof_partner_exchange` | Valeur qu'Odoo prend déjà par défaut : aucun changement de comportement | ✅ Fait. |
| A3 | Ajouter un `_description` aux modèles `_name` qui n'en ont pas, en anglais (dérivé de `_name` : `partner.sector` → `"Partner Sector"`) | `stof_partner_exchange` | Supprime l'avertissement Odoo ; ne pas toucher aux `.po` | ✅ Fait pour les modules internes ; OCA conservé. |
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

## Audit des TODO restants (08/10/2026)

Tous les problèmes numérotés ont été relus. Les TODO encore manuels sont
conservés lorsqu'une correction exige une décision métier ou une preuve que
l'analyse statique ne possède pas : déplacement de traductions (18), retrait
d'un bloc de vue devenu doublon (20), surcharge standard potentiellement
accidentelle (23), chargement `data` répété (25), concaténation HTML (51),
écart de `@api.depends` (53), dépendance circulaire et choix d'architecture
(64), migration complexe de `mail.compose.message` (70), route `auth="none"`
(73), champ porté par un héritier de mixin (76), adaptation de `create` au
multi-enregistrement (78) et erreurs Python qui nécessitent de choisir le type
d'exception ou le comportement voulu (79).

Les modernisations A5 à A8, A12 et A14 restent volontairement hors du mode par
défaut : elles changent l'ordre des données, la forme du code ou des
commentaires sans être nécessaires à une migration. Les contrôles A16 et A17
restent des diagnostics, car la société à utiliser et la politique de
conversion des données appartiennent au métier du module.

Les deux anciens commentaires `TODO` présents dans les scripts 10→11 et 11→12
ont également été traités. Les attributs d'accessibilité manquants des vues 12
sont maintenant signalés. La conversion Python 2 par `lib2to3` n'est pas
activée : cette bibliothèque a été retirée de Python et une conversion aveugle
ne garantirait pas la conservation du code Odoo. Ce point historique ne touche
pas les migrations modernes, dont 17→20.
