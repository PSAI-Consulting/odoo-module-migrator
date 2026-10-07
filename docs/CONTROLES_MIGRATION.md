# Contrôles supplémentaires des migrations

Les reproductions dans `tests/test_client_regressions.py` utilisent des modules
fictifs. Aucune règle ne dépend du nom d'un client, d'un chemin client ou de sa
configuration.

| Problèmes signalés | Traitement |
|---|---|
| 1, 2 | Après les scripts officiels : échappements Unicode rendus lisibles uniquement si la valeur Python reste identique ; lignes vides initiales retirées. Dans les `__init__.py` composés uniquement d'imports, toutes les lignes vides sont retirées. Chaînes brutes, bytes et f-strings conservées. |
| 3, 14 | Avec les sources cibles : usages Python de modèles, champs, relations, variables de boucle et dictionnaires `create`/`write`. Le rapport nomme les modules fournisseurs et détecte une dépendance circulaire ; il recommande alors de déplacer le code ou de créer un module de liaison. |
| 4 | Nouveau type de règles `field_types`. Détection des lectures/affectations, redéfinitions et méthodes `_compute_<champ>`. Règle vérifiée pour `sale.order.line.customer_lead` en 20.0 ; aucune conversion automatique de données. |
| 5 | Après `upgrade_code`, `security/ir.access.csv` retrouve la position de l'ancien `security/ir.model.access.csv`, sans réordonner les autres fichiers. |
| 6, 11 | Imports inutilisés supprimés par défaut (F401, hors `__init__.py`, respecte `noqa`). `--format` ajoute le formatage Ruff des fichiers Python effectivement modifiés, avec la configuration du projet. |
| 7 | Ajout de la licence LGPL-3 par défaut si absente ; avertissement pour `_name` sans `_description`. La description métier reste à renseigner. |
| 8, 9 | Chemins de contexte dédoublonnés ; priorité à la copie migrée ; cache disque JSON dans SQLite pour les métadonnées Python/XML ; expressions régulières compilées une fois ; itération des scripts officiels limitée aux modules sélectionnés. Les dépendances restent accessibles en lecture explicite. |
| 10 | Avertissement uniquement si le champ invisible est utilisé par une expression de la même architecture de vue. |
| 12, 17 | Évaluation des XPath complets sur une architecture reconstruite : axes enfant/descendant, indices, attributs, modifications successives. Réécritures limitées aux vues standard concernées : colonne `price_unit`, état de facture `status_in_payment`, groupes de recherche sans `expand`. |
| 13 | Références Python `uom.uom_categ_*` signalées ; `uom.uom.category_id` signalé lorsque le modèle est résolu par l'index cible. Piste : `_has_common_reference(other_uom)`. |
| 15 | `digits='Product Unit of Measure'` devient `Product Unit` au saut 18→19. Les précisions Python inconnues de l'index cible sont signalées. |
| 16 | Les dépendances transitives renommées/fusionnées sont résolues pour les contrôles. Une dépendance introuvable n'annule plus les analyses ; le rapport affiche un risque inconnu si les vérifications sont incomplètes et qu'aucune erreur certaine ne justifie un risque élevé. |
| 18, 19 | Avertissements pour `.po` hors de `i18n/` et f-string passée à une fonction de traduction. Aucun déplacement de traductions ni changement automatique de texte source. |
| 20 | Avertissement de doublon potentiel avec la vue cible, en privilégiant un conteneur commun ou une ancre disparue. Les doublons étant parfois voulus, aucun bloc n'est supprimé automatiquement. |
| 21 | Migration des raccourcis d'environnement sur les accès Python identifiés comme appartenant à un modèle ; commentaires et textes conservés. |
| 22, 23 | Contrôle des méthodes `compute`, `inverse`, `search` nommées par une chaîne ; avertissement pour une surcharge `_compute_*` / `_search_*` sans `super()` ni référence au champ correspondant. |
| 24, 25 | Diagnostics pour `_` global utilisé sans définition/import et pour les fichiers répétés dans `data`. Les chargements répétés ne sont pas supprimés automatiquement. |
| 33 | Pour un parent de menu standard supprimé, proposition des nouveaux parents des anciens enfants qui existent encore dans la cible. Si les enfants ont été répartis, toutes les destinations sont affichées avec leur preuve et aucun remplacement ambigu n'est appliqué. |
| 34 | Les renommages de champs sont aussi appliqués avec l'index relationnel cible : les alias imbriqués comme `order.order_line` → `line` sont résolus et les renommages successifs restent ordonnés. Un accès résolu à un champ absent de la cible devient une erreur. |
| 35, 37 | Un appel à `_select_seller()` en 20 dont le résultat n'est pas extrait via `supplierinfo` est signalé car il renvoie désormais un dictionnaire. L'absence de `quantity` ajoute un avertissement sur le nouveau défaut `min_qty = 1`. |
| 36 | Avertissement sur `.name` des lignes de vente, achat et facture lorsque le code attend le nom du produit, en Python résolu et dans les expressions QWeb aux variables de ligne explicites. |
| 38 | Les champs magiques de `BaseModel` (`id`, `display_name`, dates et utilisateurs de création/modification, `__last_update`) sont présents sur chaque modèle indexé et ne produisent pas de faux diagnostic de champ absent. |
| 39 | À partir d'Odoo 18, `_()` devient `self.env._()` dans les générateurs, compréhensions et lambdas des méthodes de modèles afin de rendre la langue explicite. Les appels ordinaires restent inchangés. |
| 40 | Le sommaire accepte le risque `inconnu` des analyses incomplètes et classe prudemment tout nouveau niveau imprévu au lieu d'échouer. |
| 41 | Une version absente est insérée dans le manifest. Les clés étrangères au schéma Odoo et les clés formées par concaténation implicite de chaînes sont signalées, tout en conservant les métadonnées personnalisées pour revue. |
| 42, 44 | Une méthode qui appelle `super().<même méthode>()` est vérifiée contre les parents de la cible. Les méthodes publiques héritées de `BaseModel`, dont `default_get`, sont connues même sans dépôt Odoo. Les renommages connus viennent de règles documentées ; à défaut, les noms proches sont seulement suggérés. |
| 43 | Les ancres sont validées sur la vue héritée et ses ancêtres avant la composition avec les autres vues dépendantes. Une vue sœur qui remplace l'ancre n'invalide donc plus la vue en cours. |
| 45, 47 | À partir de la 18, les relations `Many2one` et `Many2many` vers `documents.document` utilisées comme sélecteurs dans une vue et sans domaine portant sur `type` sont signalées : les dossiers sont désormais des documents de type `folder`. Les sous-vues relationnelles et les domaines XML sont pris en compte ; les relations de stockage non affichées ne sont pas signalées. |
| 46 | Les champs lus sur un recordset provenant de `env[<modèle dynamique>]` sont signalés avec la forme explicite `record["champ"]`. Pour `x2many += record`, le rapport conseille de collecter les identifiants puis d'utiliser une seule commande `Command.set`. |
| 48 | Un modèle persistant explicitement nommé qui ressemble fortement à un assistant est signalé : action formulaire `target="new"` avec `default_get()`, ou relation `One2many` vers un modèle transitoire. Une fenêtre modale seule ne déclenche rien. |
| 49 | La remise en ordre de `security/ir.access.csv` supporte les listes où le script officiel a ajouté le premier élément directement après `[`. Le manifest final reste valide et sa normalisation s'exécute. |
| 50 | Le renommage de précision UoM couvre `digits=`, `precision_get(...)`, `dp.get_precision(...)` et les enregistrements XML `decimal.precision`, en laissant les libellés métier homonymes intacts. |
| 51 | Un `+=` sur un champ indexé comme `fields.Html` est signalé car la valeur `Markup` échappe une chaîne ordinaire. `</br>` est également signalé comme balise incorrecte. |
| 52 | Le typage des recordsets traverse les alias de `self.filtered(...)`, les générateurs, les compréhensions et `_origin`. Les renommages de champs résolus s'appliquent donc aussi dans ces expressions. |
| 53 | Les `@api.depends` des méthodes cibles sont indexés. Une surcharge `_compute_*` qui emploie un ensemble différent reçoit un avertissement détaillant les dépendances manquantes et supplémentaires. |
| 54 | Pour les modules internes, les en-têtes légaux redondants sont retirés des fichiers Python et du manifest. Les modules reconnus comme OCA conservent leurs en-têtes. |
| 55 | Après la suppression des imports inutilisés, Ruff corrige aussi les groupes d'imports et un nettoyage final normalise les blocs de lignes vides. |
| 56 | Une variable issue de `super().<méthode>(...)` et ensuite itérée est traitée comme un recordset du modèle courant. Les chemins relationnels imbriqués et leurs renommages sont alors résolus. |
| 57 | Pour une méthode cible remplacée sans `super()`, le rapport cherche les points d'extension `_prepare_*`, `_affects_*` et `_get_*_domain` appelés directement ou à un niveau, puis propose ces hooks pour limiter la surcharge. |
| 58 | Une apostrophe doublée façon SQL (`'d''entrée'` : deux littéraux `'…'` collés sans espace, lettre de chaque côté) est réécrite en apostrophe échappée dans le manifest et le code, avant le formatage. Les autres littéraux accolés entre lettres sont seulement signalés. |
| 59 | Les droits visant un `AbstractModel` sont signalés dans l'ancien `ir.model.access.csv` comme dans le nouvel `ir.access.csv`. Les noms techniques et XML IDs `model_*` sont résolus par l'index des modèles. |
| 60 | Une chaîne dont toutes les séquences d'échappement sont invalides (`"\."`, `SyntaxWarning` en Python 3.12) devient une chaîne brute de valeur identique. Un mélange de séquences valides et invalides est signalé. |
| 61 | La normalisation du manifest retire aussi `data` vide et les entrées vides de `external_dependencies` (puis la clé si elle ne contient plus rien). |
| 62 | `tracking=` sur un champ d'un modèle sans `mail.thread` (lignée entièrement connue) est signalé ; un manifest sans `author` est signalé sans inventer de valeur. |

Les lectures du délai produit devenu dépendant de la société en 20 sont aussi
signalées lorsque le modèle est identifié, ainsi que les appels `write()` dans
les méthodes de calcul. Les appels directs `model.<méthode>()` déclarés par une
tâche planifiée ou une action serveur sont vérifiés contre le modèle cible et
les dépendances du module ; un fournisseur hors dépendances est nommé.

Le renommage Odoo 20 `res.partner.bank.acc_number` → `account_number` couvre
aussi les dictionnaires de commandes x2many sous `bank_ids` et les expressions
QWeb dont le récepteur est identifié comme une banque. Les clés homonymes des
flux d'import restent intactes. Un accès `.acc_number` ambigu est laissé en
place et signalé pour revue.

## Formatage

```shell
odoo-module-migrate -d ./addons -m mon_module -i 17.0 -t 20.0 --no-commit --format
```

Ruff utilise `.ruff.toml`, `ruff.toml` ou `[tool.ruff]` dans `pyproject.toml`.
Le mode `--dry-run --format` utilise également la configuration du projet
d'origine. Ruff est installé avec l'outil. Le migrateur applique les corrections
sûres F401 par défaut (`--keep-unused-imports` pour les désactiver), puis
`ruff format` si demandé. Il n'applique pas toutes les corrections d'un `select = ["ALL"]` :
celles-ci pourraient changer des chaînes traduisibles ou ajouter des en-têtes.
Les nettoyages cosmétiques et ce formatage sont ignorés pour les modules OCA.

## Modèle de manifeste

Le modèle est intégré au code, sans dépendance à Obsidian : ordre des clés,
listes une valeur par ligne, suppression des valeurs par défaut et des
commentaires scaffold, `website` et `license` présents. Les valeurs métier,
clés personnalisées, commentaires de l'auteur et descriptions non vides sont
conservés. Les descriptions multilignes gardent leurs triples guillemets. Les
clés optionnelles vides (`summary`, `description`, `external_dependencies`,
`demo`, `assets`) sont retirées. Un site absent reste vide, ou reçoit
`--default-website URL`.
`--no-manifest-format` conserve la présentation d'origine.

L'ordre des fichiers `data` reste inchangé : certains fichiers de sécurité
dépendent de données chargées avant eux. Seul le remplacement d'un fichier ACL
par `ir.access.csv` reprend sa position initiale. Aucune identité client n'est
inscrite dans le modèle commun.

## Scripts officiels embarqués

Les archives Community 18/19/20 sont incluses dans le paquet (environ 45 Mo),
avec licence, révision Git, empreintes et provenance. Python 3.12+ suffit ;
aucun serveur Odoo ni téléchargement n'est nécessaire à l'exécution.
Les références Enterprise restent à fournir par `--addons-path`.
`--odoo-root` remplace les sources embarquées ; `--no-upgrade-code` désactive
les scripts officiels et les analyses contre les sources cibles.

Les adaptations du lanceur concernent les accès fichiers, les dépendances et
les manifestes. Les scripts embarqués eux-mêmes sont conservés tels quels.
Le script d'exemple, la conversion interne de plan comptable et le remplacement
textuel des raccourcis d'environnement sont exclus ; ce dernier est remplacé
par la transformation Python structurée du migrateur.
Pour actualiser une archive depuis les sources Community :

```shell
python tools/vendor_upgrade_code.py --source /repos/odoo/20.0 --version 20.0
```

## Extraire de nouvelles règles

```shell
python tools/extract/extract_changes.py field-types --from 19.0 --to 20.0 --repo /repos/odoo.git --output /tmp/types.yaml
python tools/extract/extract_changes.py decimal-precisions --from 18.0 --to 19.0 --repo /repos/odoo.git --output /tmp/precisions.yaml
```

Après relecture, les règles de types peuvent être placées sous
`migration_scripts/field_types/migrate_XXX_YYY/`. Chaque ligne porte le modèle,
le champ, l'ancien type, le nouveau et sa provenance. L'extraction des précisions
produit deux inventaires par XML id, avec le nom et la source de chaque version.

## Limites et choix de conservation

L'analyse reste statique : elle ne remplace pas une installation Odoo ni les
tests métier. Les méthodes fabriquées dynamiquement, les accès via `getattr`,
certains alias et héritages complexes ne sont pas complètement résolus.
Une expression XPath ou opération d'héritage non prise en charge est indiquée
comme incomplète. La détection de doublons est une aide à la revue, pas une
preuve historique de déplacement entre deux versions.

Le cache utilise les chemins absolus, la version de son schéma, celle de Python
et les métadonnées des fichiers. Il tient compte des fichiers modifiés hors
commit ; aucun cache n'est écrit dans le dépôt client. Il est facultatif : un
cache inaccessible n'empêche pas l'analyse.

Les propositions cosmétiques qui changent potentiellement le comportement
(ordre général de chargement de la sécurité, commandes x2many, renommage de
variables, suppression de code commenté, dédoublonnage des chargements) ne sont
pas appliquées arbitrairement. Le modèle de manifeste commun n'impose aucune
valeur d'auteur, de nom ou de site d'une équipe à un autre client.

`invisible` et `column_invisible` sont conservés distincts : le premier peut
dépendre des valeurs de la ligne, le second masque la colonne entière sans ce
contexte. La conversion globale de l'un vers l'autre a été retirée.
