# Historique des versions

## Non publié

- Relecture et réparation 100 % locales avec Ollama :
  - Abstraction de fournisseur (`BaseLLMProvider`), profilage matériel sans dépendance lourde et commande de diagnostic `--ollama-info`.
  - RAG hybride auditable : recherche lexicale BM25 et symbolique, filtrage strict par version, priorisation curated et isolation des invites contre les injections.
  - Boucle autonome de réparation bornée (`--ollama-repair`, `--ollama-max-attempts`, `--ollama-max-minutes`, `--ollama-max-diff-lines`) opérant dans des copies/transactions et annulant tout échec ou régression.
  - Applicateurs structurés déterministes pour Python (imports, dictionnaires, AST), XML (attributs, XPath), manifestes et CSV.
  - Score de confiance objectif fondé sur des preuves vérifiables (règles officielles, résolution des symboles, syntaxe et tests).
  - Mode explicite `--ollama-apply` sécurisé contre les conflits et chevauchements, confinement strict au module et validation syntaxique.
  - Rapports Markdown enrichis avec bilan des indicateurs, niveau de validation atteint et diffs audités.

- Python 3.12 minimum ; scripts officiels Community 18/19/20 et références
  intégrés pour une utilisation hors ligne, avec provenance et empreintes.
- Modèle générique de manifeste et nettoyage des imports inutilisés par défaut ;
  formatage Ruff optionnel, respect des modules OCA et des métadonnées client.
- Contrôles supplémentaires des dépendances Python, méthodes de champs,
  changements de types, précisions, traductions et héritages de vues.
- Corrections sûres des `_description`, f-strings traduisibles simples, API
  typées `ir.config_parameter` d'Odoo 20 et lectures singleton dans les boucles.
- Préservation du nom à la copie pour les modèles custom face au nouveau
  suffixe automatique « (copy) » d'Odoo 20.
- Contrôle des champs supprimés dans le SQL brut et exclusion des vues SQL de
  la règle de copie des noms.
- Conversion fiable des `_sql_constraints` dont le message utilise `_()`,
  migration des boutons `toggle_active` d'Odoo 20 et nettoyage des textes
  scaffold du manifeste.
- Typage des recordsets renvoyés par `mapped`, exclusion des faux fournisseurs
  de méthodes ORM et revue obligatoire avant d'ajouter une dépendance
  Enterprise.
- Rapports recalculés sur les sources finales et détection des fichiers Python
  non atteignables depuis les imports du module.
- Comparaison des signatures de surcharges avec les modèles de la cible et
  synchronisation sûre des simples appels de transmission à `super()`.
- Conservation systématique des scripts de migration de données et migration
  des extensions simples de rapports SQL vers les API `TableSQL` d'Odoo 20.
- Compatibilité `BaseCommon`, métadonnées OCA, constantes de tests renommées et
  renommages de champs dans les dictionnaires construits par les tests.
- Conversion `ir.access.csv` respectueuse du manifest et domaines CSV ramenés
  sur une ligne sans altérer les chaînes littérales.
- Conversion bancaire Odoo 20 étendue aux journaux et aux anciens chemins
  `bank_id.name/bic` ; ACL externes exclues et modules fusionnés signalés à
  l'échelle du dépôt.
- Réparation commentée des listes `data` après `upgrade_code`, protection des
  icônes OCA, extensions multi-héritées reconnues et renommage complet de
  `purchase.order.notes` vers `note`.
- Renommages de champs dans les lambdas et XPath relationnels, détection des
  champs liés redéfinis comme calculés et guide de migration du moteur fiscal.
- Typage des clés `config_parameter` depuis les champs de réglages, avec
  conversion booléenne sûre et détection des chaînes utilisées comme booléens.
- Détection des champs devenus stockés lorsqu'un module remplace leur calcul,
  déplacements `odoo.http`, suppression sûre de valeurs de champs retirés dans
  les `create`/`write` Python et renommages imbriqués dans `related=`.
- Migration `ir.attachment.datas` vers `raw`/`BinaryValue` jusque dans les
  tests, inventaire ORM complété, widgets de vues 20 et champs redéclarés.
- Test de conservation des commentaires de manifeste aligné sur le moteur :
  un remplacement positionnel les préserve, une reconstruction ambiguë reste
  refusée.
- Génération de la liste OCA sécurisée : les manifestes sont lus comme des
  littéraux et ne peuvent plus exécuter du code Python arbitraire.
- Le runner `upgrade_code` conserve maintenant un module explicitement
  sélectionné même si son nom possède un alias de fusion dans la cible ; les
  alias continuent de s'appliquer aux seules dépendances.
- Les manifestes indentés sont acceptés par les contrôles qualité et les
  réécritures officielles ; chaque fichier `data` référençant un chemin absent
  est maintenant signalé explicitement.
- Correction des faux positifs XPath et retrait de la conversion globale
  `invisible` vers `column_invisible`.
- Cache des analyses, parcours limité aux dépendances utiles et commandes Git
  limitées aux modules sélectionnés.
- Voir `docs/CONTROLES_MIGRATION.md` pour la couverture et les limites.

## 0.6.0 — octobre 2026

Refonte du fork pour en faire l'outil de référence de migration du code
source de modules Odoo, de 8.0 à 20.0 (priorité 17.0 → 20.0).

### Moteur
- Lecture / écriture des fichiers sans changer l'encodage, le BOM ni les fins
  de ligne ; écritures atomiques.
- `--dry-run` : prévisualisation sous forme de diff, sans rien écrire.
- Rapport par module `MIGRATION_REPORT.md` (risque, TODO `fichier:ligne`,
  transformations, fichiers modifiés) ou `--report-dir`.
- Scripts officiels d'Odoo (`odoo/upgrade_code`) lancés avec `--odoo-root` /
  `--odoo-python`, en n'écrivant que dans les modules migrés.
- Une étape en échec n'arrête plus la migration.
- `installable` laissé tel quel par défaut (`--set-installable` pour le forcer).
- Version du manifest : `X.0` / `X.0.a.b.c` → `<cible>.1.0.0`.
- `--version`.

### Analyse (zéro faux positif)
- Champs renommés / supprimés traités selon leur modèle (Python et XML,
  sous-vues x2many, héritage par délégation `_inherits`).
- Avec `--odoo-root` : ancres des vues héritées, XML ids, modèles, chemins
  `@api.depends` / `related=`, imports `odoo.addons.*` vérifiés contre
  l'Odoo cible ; dépendance manquante dans `depends` nommée.

### Règles
- 17.0 → 20.0 : modules, champs, modèles, vues, modules JS, API Python
  extraits des sources Odoo / Enterprise et d'OpenUpgrade, chacun avec sa
  source ; transformations dédiées (`ir.access`, `res.groups.privilege`,
  `odoo.registry` → `Registry`, imports `odoo.tools` déplacés,
  `report_file`, `slugify`, `is_storable`…).
- 8.0 → 17.0 : règles vérifiées et sourcées, conversion `attrs` / `states`
  réécrite, anciennes règles non prouvées retirées.
- Règles destructrices ou non prouvées de l'amont retirées.

### Outils de mainteneur (`tools/`)
- `extract/extract_changes.py` : régénération des règles par sous-commande.
- `bench/bench.py` : bancs d'essai avec installation réelle sur Odoo, boucle
  rapide `--retry-failed`.

## 0.5.x

Versions de l'outil amont
[OCA/odoo-module-migrator](https://github.com/OCA/odoo-module-migrator).
