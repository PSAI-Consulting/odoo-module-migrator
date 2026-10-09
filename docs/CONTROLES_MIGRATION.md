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
| 7 | Ajout de la licence LGPL-3 par défaut si absente. Pour un module interne, un modèle `_name` sans `_description` reçoit une description anglaise stable dérivée de son nom technique ; le code OCA est conservé. |
| 8, 9 | Chemins de contexte dédoublonnés ; priorité à la copie migrée ; cache disque JSON dans SQLite pour les métadonnées Python/XML ; expressions régulières compilées une fois ; itération des scripts officiels limitée aux modules sélectionnés. Les dépendances restent accessibles en lecture explicite. |
| 10 | Avertissement uniquement si le champ invisible est utilisé par une expression de la même architecture de vue. |
| 12, 17 | Évaluation des XPath complets sur une architecture reconstruite : axes enfant/descendant, indices, attributs, modifications successives. Réécritures limitées aux vues standard concernées : colonne `price_unit`, état de facture `status_in_payment`, groupes de recherche sans `expand`. |
| 13 | Références Python `uom.uom_categ_*` signalées ; `uom.uom.category_id` signalé lorsque le modèle est résolu par l'index cible. Piste : `_has_common_reference(other_uom)`. |
| 15 | `digits='Product Unit of Measure'` devient `Product Unit` au saut 18→19. Les précisions Python inconnues de l'index cible sont signalées. |
| 16 | Les dépendances transitives renommées/fusionnées sont résolues pour les contrôles. Une dépendance introuvable n'annule plus les analyses ; le rapport affiche un risque inconnu si les vérifications sont incomplètes et qu'aucune erreur certaine ne justifie un risque élevé. |
| 18, 19 | Avertissement pour `.po` hors de `i18n/`. Une f-string de traduction composée de noms ou d'attributs devient un message à paramètres nommés ; les expressions complexes restent signalées INT001. |
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
| 64 | Les diagnostics de dépendance circulaire sont regroupés par méthode dans le rapport, avec les modèles/champs utilisés et un plan de hook dans le fournisseur ou un module de liaison. |
| 65, 78 | Une méthode de calcul qui écrit un autre champ et une surcharge `create` sans `@api.model_create_multi` sont signalées. |
| 66, 67, 70, 71 | Contrôles Odoo 20 sur `__last_update`, texte + octets, API typées de `ir.config_parameter`, appels de méthodes absentes et SQL brut vers `mail_tracking_value`. Les `get_param`/`set_param` sont convertis quand le type est prouvé ; les écritures dynamiques restent signalées. |
| 68, 75 | Les lectures/décodages et écritures base64 sur des champs `Binary`/`Image` résolus tiennent compte de `BinaryValue`; `_file_read` avec argument est signalé. |
| 69 | Constantes de classe et attribut `pool` exclus des faux champs ; un modèle persistant relu par `search` n'est pas proposé comme assistant. |
| 72, 74, 77 | Réécritures de vues limitées aux architectures : mode kanban, CSS `%`, `active_id` vers `id` et widget `field_selector`. Les contextes d'actions et commentaires sont conservés. |
| 73 | Les appels de messagerie dans une route `auth="none"` sans utilisateur explicite sont signalés. |
| 76 | Pour un champ absent d'un mixin abstrait, le diagnostic liste les héritiers concrets qui le définissent et leurs types. |
| 79 | Diagnostics Python pour chaîne levée, `env.get` booléen, valeur comparée à `fields.X` et `except:` nu. |
| 80 | Les widgets dont le module fournisseur est connu sont comparés à la fermeture des dépendances (`section_and_note_one2many` → `account`). |
| 81 | Pour Odoo 20, les opérations base64 directement reliées à un champ `Binary`/`Image` connu sont converties vers `.content` en lecture et `BinaryBytes(...)` en écriture, avec ajout d'import. Les usages non prouvés restent inchangés. |
| 82 | Une lecture `self.<champ>` dans `for record in self` devient `record.<champ>` afin d'éviter `Expected singleton`; les méthodes ayant appelé `ensure_one()` sont exclues. |
| 83 | Sur un champ `Binary`/`Image` résolu, `.decode()` sans encodage ou avec UTF-8/ASCII devient `.to_base64()` pour préserver la valeur historique. Les encodages dynamiques restent à revoir ; le typage traverse les arguments nommés passés aux méthodes. |
| 84 | `cr.clear()`/`reset()` immédiatement après `commit()` devient `env.transaction.clear()`; ailleurs, un diagnostic demande de traiter aussi les callbacks `precommit`. |
| 85 | Les dictionnaires Python prouvés comme vues/actions migrent `type: tree` et `view_mode: tree` vers `list`, sans remplacement global des valeurs métier. |
| 86 | `get_external_id` et `_get_external_ids` sont des méthodes de base connues. Un `name_get()[0]` dont le récepteur est prouvé singleton devient le couple `(id, display_name)`. |
| 87 | La migration tree→list ne modifie plus les libellés « Tree View » ni les textes traduisibles ; elle reste limitée aux structures techniques. |
| 88, 89 | Pour préserver le comportement antérieur au commit Odoo 20 `b84ffce402d3`, les champs `Char` simples `name`/`x_name` d'un modèle custom reçoivent `copy=True`. Les champs calculés, liés, dépendants de la société, les traductions callable et les modèles SQL `_auto = False` ne sont pas modifiés. Dans les requêtes SQL, les références qualifiées aux champs supprimés connus sont signalées à partir des règles de la migration courante. |
| 90 | Avant le convertisseur officiel ou de secours, le wrapper de traduction d'un message littéral de `_sql_constraints` est retiré de façon structurée. `models.Constraint` assure ensuite la traduction ; les autres appels `_()` restent intacts. |
| 91 | En Odoo 20, les boutons de vue `toggle_active` deviennent `action_archive` quand `invisible="not active"` et `action_unarchive` quand `invisible="active"`. Toute autre visibilité reste inchangée et est signalée. Les appels Python résolus sont contrôlés contre les méthodes de la cible. |
| 92 | Les espaces et retours à la ligne d'un `summary` de manifeste sont réduits pour obtenir une ligne. La description factice exacte du scaffold Odoo est retirée, sans supprimer une description métier. |
| 93 | Les appels aux méthodes héritées de `BaseModel`, dont `_search`, ne sont pas attribués à un module qui les surcharge. Une dépendance Python dont l'unique fournisseur porte la licence `OEEL-1` reste un TODO avec le symbole déclencheur au lieu d'être ajoutée. Le typage traverse aussi `mapped("champ_relationnel")`, notamment pour renommer `stock.move.line.product_uom_id` en `uom_id`. |
| 94 | Les erreurs et avertissements fondés sur un motif textuel sont recalculés après tous les nettoyages : le rapport ne conserve plus un TODO dont le code a disparu. Les analyses Python suivent les imports locaux depuis le `__init__.py` de l'addon ; un fichier ou paquet non chargé est exclu des diagnostics de migration et reçoit un unique avertissement de code mort. |
| 95 | Les signatures des surcharges Python sont comparées aux méthodes des modèles de la cible. Les paramètres manquants ou réordonnés et les appels `super()` incompatibles sont signalés en erreur. Une surcharge qui transmet simplement ses paramètres est synchronisée automatiquement lorsque la signature cible est unique, ses valeurs par défaut sont littérales et les paramètres supprimés ne sont utilisés que par le `super()`. L'appel devient nommé pour éviter les inversions lors d'un futur réordonnancement. |
| 96 | La conversion `ir.model.access`/`ir.rule` modifie structurellement la liste `data` du manifeste et préserve sa disposition pour un remplacement de même taille. La clé OCA `maintainers` est reconnue. `DISABLED_MAIL_CONTEXT` devient `DISABLED_MAIL_CREATE_CONTEXT`. La suppression obligatoire de la déclaration XML de `static/description/index.html` est tracée. Un paramètre devenu keyword-only reste un avertissement lorsque la surcharge plus permissive et son `super()` sont compatibles. |
| 97 | Les dossiers `migrations/` ne sont jamais supprimés. Les hooks `_select_additional_fields`, `_group_by_sale` et `account.invoice.report._select` sont reliés aux API `TableSQL` d'Odoo 20 et les extensions simples sont converties. Les bases de tests héritant directement de `BaseCommon` reçoivent `_test_user_groups = None` pour conserver les privilèges historiques. |
| 98 | Les renommages de champs analysent aussi les tests et les dictionnaires préparés hors de l'appel ORM lorsque leurs autres clés prouvent un modèle unique. Les domaines convertis dans `ir.access.csv` sont normalisés sur une ligne par tokenisation Python. |
| 99 | `_test_user_groups` est inséré avant tout décorateur de la première méthode. Odoo 20 renomme aussi `account.journal.bank_acc_number` et aplatit `partner_bank.bank_id.name/bic` en `bank_name/bank_bic` dans les contextes bancaires prouvés. Les ACL dont l'ID qualifié appartient à un autre module sont exclues avec une erreur ; les CSV vides disparaissent du manifeste. Les dossiers de modules fusionnés connus d'OpenUpgrade sont signalés même hors de la sélection courante. |
| 100 | La liste `data` réparée après le convertisseur officiel retrouve une disposition multiligne et le style de guillemets dominant tout en conservant ses commentaires. Les icônes `static/description/icon.*` des modules OCA sont restaurées si une étape les modifie. `_name` identique à l'un des modèles de `_inherit` est traité comme une extension et ne déclenche pas l'exigence `_description`. |
| 101 | Le renommage `purchase.order.notes` → `note` couvre les variables des rapports QWeb d'achat et les paramètres explicitement nommés dans les extensions Python de `purchase.order`, en plus des usages déjà résolus par l'index. |
| 102 | `excludes`, lu par le chargeur de modules Odoo 20, est une clé de manifeste connue et ne produit plus de faux diagnostic. |

Les dépendances Python manquantes sont ajoutées automatiquement au manifeste
quand l'index des addons est complet, qu'un seul fournisseur existe et que cet
ajout ne crée pas de cycle. La même règle s'applique aux widgets dont le module
fournisseur est connu. Les imports inutilisés sont déjà supprimés par défaut
avec Ruff F401, sauf dans les `__init__.py`, les modules OCA et lorsque
`--keep-unused-imports` est demandé.
| 60 | Une chaîne dont toutes les séquences d'échappement sont invalides (`"\."`, `SyntaxWarning` en Python 3.12) devient une chaîne brute de valeur identique. Un mélange de séquences valides et invalides est signalé. |
| 61 | La normalisation du manifest retire aussi `data` vide et les entrées vides de `external_dependencies` (puis la clé si elle ne contient plus rien). |
| 62 | `tracking=` sur un champ d'un modèle sans `mail.thread` (lignée entièrement connue) est signalé. Un `author` absent est complété par `--default-author`, sinon signalé. |
| 63 | Les commentaires d'une clé retirée par la normalisation du manifest (clé vide ou valeur par défaut) disparaissent avec elle et sont tracés dans le journal. |

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
`data`, `demo`, `assets`) sont retirées, avec leurs commentaires. Un site
absent reste vide, ou reçoit `--default-website URL` ; un auteur absent reçoit
`--default-author NOM`, sinon il est signalé.
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
