# Politique de relecture Odoo du migrateur

Cette base complète les règles déterministes retrouvées dans
`migration_scripts/`. Elle ne les remplace jamais.

## Ordre de confiance

1. L'AST Python, l'arbre XML, le manifeste et les index construits depuis les
   sources Odoo cibles sont des preuves.
2. Une règle sourcée par un commit Odoo, un script officiel `upgrade_code` ou
   OpenUpgrade peut justifier une correction.
3. Une ressemblance de nom, une convention habituelle ou la mémoire du modèle
   ne suffit pas. Dans ce cas, proposer une vérification, jamais une édition.

## Préservation obligatoire

- Préserver le comportement métier, les XML IDs, textes traduisibles,
  commentaires utiles, métadonnées OCA et scripts de migration de données.
- Ne jamais inventer un modèle, champ, méthode, module ou XML ID Odoo.
- Ne pas transformer un cas ambigu ni masquer un diagnostic déterministe.
- Préférer le plus petit changement local et expliquer la preuve.
- Une dépendance n'est ajoutée automatiquement que si son fournisseur est
  unique et ne crée pas de cycle ; Enterprise nécessite une revue explicite.

## Lecture du contexte

- `DIAGNOSTICS` décrit ce que les analyseurs ont réellement observé.
- `TRANSFORMATIONS DÉJÀ APPLIQUÉES` ne doit pas être reproposé.
- `RÈGLES RETROUVÉES` cite le code ou les données de règle du migrateur ; leur
  chemin doit être mentionné comme preuve lorsqu'elles fondent le conseil.
- Un contexte incomplet impose une confiance faible ou moyenne et une étape de
  vérification concrète dans les sources de la version cible.

## Éditions proposées

Une édition exacte n'est proposée que si elle est de confiance haute, minimale,
présente textuellement dans le contexte et valide sans décision métier. Les
réécritures larges, suppressions de blocs, créations de dépendances ambiguës et
changements de données restent des conseils manuels.
