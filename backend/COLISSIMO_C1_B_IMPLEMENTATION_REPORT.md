# SELBY — Lot C / C1-B — Socle logistique Colissimo

Date : 6 novembre 2026. Référence : [architecture C1-A approuvée](COLISSIMO_C1_ARCHITECTURE_REPORT.md).

**Socle implémenté et testé. Aucun Checkout logistique activé, tarif publié durablement, appel Colissimo, achat de bordereau ou paiement Stripe réel. C2 n'est pas commencé.**

## 1. Modèles et migrations

### État vérifié avant intervention

Le dépôt présentait une tête Alembic `0015`. Des lectures SQL en mode lecture seule ont confirmé `0015` sur `spectra` et `spectra_test`. Les modifications préexistantes du workspace ont été conservées.

La nouvelle migration additive [0016_logistics_foundation.py](alembic/versions/0016_logistics_foundation.py) succède à `0015`. Elle ajoute uniquement :

| Table / modèle | Rôle |
|---|---|
| `logistics_catalogs` / `LogisticsCatalog` | Version UUID, document complet canonique, SHA-256 et date de création. |
| `logistics_catalog_publications` / `LogisticsPublication` | Journal séquencé de validation, publication TEST et retrait ; acteur et motif obligatoires. Un catalogue sans événement est un brouillon stocké. |
| `logistics_state` / `LogisticsState` | Pointeur du catalogue publié pour les aperçus TEST ; initialisé sans catalogue. Aucune publication de production n'est proposée en C1-B. |
| `submission_logistics_selections` / `SubmissionLogisticsSelection` | Versions successives du document de sélection par soumission, catalogue associé et empreinte. |

Des triggers interdisent UPDATE et DELETE sur les trois historiques. Un trigger d'insertion de sélection verrouille la soumission, exige la version suivante et refuse toute insertion après acceptation du devis. Le service prend le même verrou de soumission que les mécanismes existants, et les clés étrangères n'ajoutent aucune suppression en cascade vers les données historiques.

Le downgrade destructif est explicitement refusé : les historiques nécessiteraient une procédure d'archivage approuvée. Aucune table existante, règle financière, échéance, acceptation ou ancien catalogue n'est modifié par cette migration.

**Déploiement :** les opérations réelles de `upgrade()` et le marqueur `0016` ont été exercés sur PostgreSQL dans une transaction de test, puis entièrement annulés. La migration n'a pas été appliquée durablement à `spectra` ou `spectra_test`, qui restent en `0015`. Son application persistante devra précéder l'utilisation du socle. L'inscription du nouveau module dans `alembic/env.py` est ajoutée ; `alembic heads` retourne une seule tête `0016`.

## 2. Calculateur et catalogue

### Modules et format

- [logistics_schemas.py](app/logistics_schemas.py) : schémas stricts du catalogue et des sélections.
- [logistics_models.py](app/logistics_models.py) : modèles persistants additifs.
- [logistics_calculator.py](app/logistics_calculator.py) : calcul pur et diagnostic des données contractuelles manquantes.
- [logistics.py](app/logistics.py) : stockage, journal de publication, versions et intégration des aperçus.
- [logistics_catalog.py](app/logistics_catalog.py) : CLI opérateur locale, sans publication de production.
- [colissimo-catalog.schema.json](pricing/colissimo-catalog.schema.json) : JSON Schema généré depuis les modèles ; les validations croisées et contractuelles restent assurées par Python.
- [colissimo-unconfigured.json](pricing/colissimo-unconfigured.json) : document préparatoire vide, sans prix, poids, taxe, adresse ou couverture réelle. Il ne peut pas être validé pour publication.

Le catalogue décrit les produits par sens, le retour Domicile avec signature, les zones métropolitaines, les tranches de poids, les frais et suppléments documentés, les couvertures et leurs limites, la période de validité, les profils de colisage, les sources documentaires avec empreinte et les références d'approbation fiscale/contractuelle/au coût. La période du catalogue s'applique à ses produits et tranches ; un changement de période ou de prix exige une nouvelle version.

La provenance distingue `provisional`, `synthetic_test` et `contractual`. Une validation structurelle n'est pas une validation commerciale. Les documents provisoires ne peuvent être ni validés ni publiés par le service. La publication disponible est uniquement `published_test`, après un événement `validated`, dans un environnement de développement avec mode Stripe TEST et pendant la validité du catalogue. Aucun tarif de production n'a été introduit ; tous les catalogues complets des tests sont explicitement synthétiques et annulés par rollback.

La CLI accepte `validate`, `store`, `validated`, `published_test` et `withdrawn`. `store` conserve un brouillon sans publication. `validate` renvoie les motifs bloquants, même si le JSON est structurellement valide. Exemple exécuté sans accès fournisseur ni écriture SQL :

```text
.venv/Scripts/python.exe -m app.logistics_catalog validate pricing/colissimo-unconfigured.json
```

Résultat : références contractuelles, documents, période, zones, produits et minimum retour manquants ; `production_publish_available: false`. Aucun fichier `.env` ni catalogue actif historique n'a été modifié.

### Calcul déterministe

Le calculateur reçoit un catalogue, une sélection, un instant explicite avec fuseau et les clés exactes des exemplaires présents dans la soumission. Il retourne les lignes, leur ventilation fiscale, les services inclus, une trace des choix et les totaux seulement si toutes les données requises sont présentes.

- Une seule sélection aller et une seule sélection retour : aucun modèle de multi-colis ou fractionnement automatique.
- Zones par liste explicite de codes postaux et référence de validation ; aucun pays `FR` interprété à lui seul comme zone admissible. Les codes de zone commençant par `97` ou `98` sont rejetés. La liste contractuelle métropolitaine reste à fournir et valider ; aucun référentiel géographique actif n'est inventé.
- Poids en grammes entiers, bornes inclusives explicites. Les tranches qui se chevauchent sont rejetées ; une lacune ou un dépassement ne devient jamais une tranche implicite. Seule une règle documentée de grammes exacts est prise en charge, sans poids volumétrique ou arrondi inventé.
- Poids et dimensions doivent être renseignés et conformes au produit. Le retour requiert un profil de colisage validé, dont les mesures, le nombre de cartes et les catégories correspondent à la sélection. Les bornes techniques des schémas ne valent pas limites commerciales Colissimo.
- Les montants et taux utilisent les types entiers stricts existants : refus des flottants, booléens, chaînes monétaires et valeurs négatives. Le calcul réutilise `checkout.shipping_amounts`, donc les conventions HALF_UP existantes.
- Chaque composante chargeable porte son prix, sa base de coût approuvée, sa source et son traitement fiscal validé. Une donnée manquante produit un total indéterminé, pas zéro.
- Les couvertures incluses sont annotées, sans facture monétaire supplémentaire inventée. Une option payante apporte une ligne distincte. Le plafond d'une option supérieure est un plafond total de remplacement, pas la somme automatique des plafonds ; sa prime incrémentale doit être documentée.
- Les catégories et valeurs par exemplaire sont vérifiées pour les produits et couvertures choisis. La disponibilité d'une couverture ne vaut pas assurabilité de toutes les cartes.

**Hypothèse de 150 € :** `PREPARATORY_RETURN_MINIMUM_MINOR=15000` est identifié comme seuil préparatoire demandé par le client. Le champ contractuel du catalogue reste `null` par défaut, avec une référence de validation obligatoire. L'hypothèse ne remplit jamais une couverture manquante et n'est pas une garantie Colissimo. Le calcul exige un minimum contractuel renseigné au moins égal à ce seuil ; une éventuelle révision de l'hypothèse devra être validée avant activation.

La somme logistique et la somme commerciale préparatoire sont calculées en unités mineures : grading existant + lignes logistiques, sans remise grading appliquée au transport. Le calcul ne crée ni obligation, ni paiement, ni bordereau.

## 3. Intégration au devis

### Sélection et aperçu

[logistics_api.py](app/logistics_api.py) expose uniquement :

```text
GET /api/submissions/{id}/logistics-selection
PUT /api/submissions/{id}/logistics-selection
```

Authentification, propriété de la soumission, protection CSRF, réponses sans cache et contrôles de version reprennent les mécanismes existants. Le client soumet des choix et valeurs déclarées, jamais un prix. Les sélections incomplètes sont conservables pour poursuivre la saisie, mais ne rendent pas le devis payable.

La sélection contient les adresses d'origine client, de destination SELBY et de retour client, les valeurs par exemplaire et par sens, les poids/dimensions, produits, options de couverture et profils. L'adresse SELBY doit correspondre au catalogue ; les adresses sont copiées dans la version de sélection, pas relues depuis un carnet mutable après coup.

Le paramètre `Settings.logistics_enabled` est faux par défaut. Après migration, il permet l'entrée de nouvelles sélections et les aperçus C1. Il **n'active pas un paiement logistique**. Une soumission ayant déjà une sélection C1 reste dans le parcours C1 même si le paramètre repasse à faux : aucun retour silencieux vers un devis payable qui omettrait l'aller. Une vérification d'existence de la nouvelle table permet de conserver le fonctionnement historique avant déploiement de `0016`, sans créer de schéma à l'exécution.

### Snapshot et invariants

`checkout.py` délègue au nouvel agrégat uniquement pour les brouillons C1. `pricing_api.py` identifie leur snapshot par `quote_schema_version: 3`. Les versions/empreintes de sélection et du catalogue publié participent au contexte de fraîcheur. Une modification de sélection ou une nouvelle publication invalide les devis non acceptés ; les documents existants ne sont pas réécrits.

Le snapshot préparatoire contient la sélection, le catalogue complet et son empreinte, les règles et la trace de calcul, les lignes de grading et de logistique et un `commercial_preview`. La racine `snapshot.total_minor` conserve sa signification grading.

En C1-B, le garde est volontairement **inconditionnel** pour les devis C1, y compris avec un catalogue synthétique complet :

```text
checkout.readiness.ready = false
checkout.readiness.states contient logistics_checkout_disabled_c1b
checkout.final_payable_minor = null
snapshot.order_total_minor = null
checkout.payment.charging_enabled = false
```

`logistics.calculation.ready` indique seulement qu'un calcul préparatoire dispose de données suffisantes ; il n'autorise pas l'acceptation payable. `commercial_preview` n'est jamais utilisé comme montant Stripe.

L'acceptation existante refuse donc ces devis. Aucune nouvelle obligation, tentative payable ou Session Stripe n'est créée par cette intégration. La future activation pourra transmettre le total complet à **la même** acceptation et à **la même** obligation, sans mécanisme financier parallèle ; elle n'est pas réalisée ici.

Les modules `stripe_checkout.py`, `stripe_api.py`, `commercial.py` et `commercial_api.py` ne sont pas modifiés pendant C1-B. Les critères de confirmation, l'idempotence Stripe et l'échéance de trente jours après succès fournisseur sont inchangés. B-P2 et B-DISPUTE ne sont ni modifiés ni requalifiés.

## 4. Tests exécutés et résultats

| Validation | Résultat |
|---|---|
| Nouveau banc `validation_tests/logistics_c1` | **50 tests réussis** |
| Régression isolée `validation_tests/stripe_batch_b/test_batch_b.py` | **46 tests réussis**, transports Stripe réels interdits |
| Frontend `npm test` | **105 tests réussis** |
| Frontend `npm run typecheck` | **Réussi** |
| ESLint hors build QA généré | **Réussi**, zéro avertissement |
| Compilation Python des nouveaux modules, migration et points d'intégration | **Réussie** |
| `alembic heads` | Une tête, `0016` |
| Validation du document Colissimo non configuré | Structure acceptée comme brouillon, données contractuelles signalées manquantes, publication production indisponible |

Les nouveaux tests couvrent les bornes et lacunes de tranches, chevauchements, catégories non admissibles, zones hors périmètre, poids/dimensions manquants, profils, absence de prix/taxe/source, calcul HT/TVA/TTC, prime facultative et couverture incluse sans double comptage, plafond supérieur non additionné, minimum préparatoire sans garantie implicite, validité temporelle, publication provisoire/production refusée, immuabilité SQL, numérotation, refus de sélection après acceptation et refus de downgrade destructif.

Ils vérifient également l'authentification, les droits sur les soumissions, CSRF, le rejet de prix fournis par le client, la préservation des versions précédentes, l'invalidation sans modification du snapshot, l'absence de devis/obligation C1 payable même sur calcul complet et l'absence de route ou de capacité d'achat d'étiquette dans le nouveau module.

### Isolation et commandes

Les tests Colissimo utilisent uniquement des prix, taxes, poids et couvertures explicitement **synthétiques**. Aucun de ces paramètres n'est une grille professionnelle ou une preuve d'assurabilité. Les transports HTTP fournisseurs sont remplacés par des fonctions qui font échouer immédiatement tout appel.

Le banc lit les empreintes de toutes les tables existantes de développement et de test. La migration et chaque scénario s'exécutent sous transactions/savepoints, puis rollback. Preuve finale :

`validation_artifacts/logistics_c1/run_fd44051454f244d0bd3cb8ab3f066d54/isolation.json`

Ce fichier confirme `test_data_schema_and_revision_unchanged: true`, `development_unchanged: true` et la migration exercée dans une transaction annulée.

La preuve Stripe est conservée dans `validation_artifacts/stripe_batch_b/colissimo_c1b_regression/isolation.json` : données et schéma de test inchangés, développement inchangé, zéro tentative de HTTP Stripe réel et zéro SQL/migration interdits.

Depuis `backend`, avec `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` :

```text
.venv/Scripts/python.exe -m pytest validation_tests/logistics_c1 --confcutdir=validation_tests/logistics_c1 -c pytest.ini -p no:cacheprovider -q --tb=short --basetemp=validation_artifacts/logistics_c1/pytest-final-tmp
```

Pour la régression, avec `SELBY_STRIPE_BATCH_B_RUN_ID=colissimo_c1b_regression` :

```text
.venv/Scripts/python.exe -m pytest validation_tests/stripe_batch_b/test_batch_b.py --confcutdir=validation_tests/stripe_batch_b -c pytest.ini -p no:cacheprovider -q --tb=short --basetemp=validation_artifacts/logistics_c1/stripe-regression-tmp
```

Depuis `frontend` :

```text
npm test
npm run typecheck
node node_modules/eslint/bin/eslint.js . --ignore-pattern=.next-stripe-b1r-qa/** --max-warnings=0
```

L'exclusion ESLint porte sur le build QA généré préexistant, comme lors du correctif B-P2 ; aucune règle lint n'est modifiée. Deux avertissements backend non bloquants subsistent : dépréciation Starlette/httpx du TestClient et option de cache inconnue lorsque son plugin est désactivé. La compilation Python n'est pas un contrôle statique de types.

## 5. Compatibilité historique

Les tables et documents `ShippingConfiguration`, `ShippingState`, `SubmissionDelivery`, `SubmissionQuote`, `QuoteAcceptance` et les journaux commerciaux existants sont conservés. Il n'y a aucun backfill.

Les commandes sans sélection C1 conservent le chemin historique lorsque le socle n'est pas demandé. Les devis déjà acceptés continuent à être servis depuis leur snapshot avant toute tentative de recalcul. Les tests vérifient un devis historique avec retour et un accord de grading seul : aucun transport aller ou montant payable supplémentaire n'est inventé.

Le système ne transforme pas les devis complémentaires existants en financement du retour normal. Les contrôles Stripe existants restent basés sur le montant exact de l'obligation acceptée ; aucun changement de statut financier persistant n'est ajouté.

## 6. Fonctionnalités encore désactivées

- Le socle n'est pas activé dans les fichiers d'environnement ; sa migration n'est pas déployée durablement sur les deux bases locales.
- Aucun devis C1 n'est acceptable comme devis payable ; tous les Checkouts logistiques restent bloqués.
- Aucune publication de production, aucun import de tarifs réels et aucun catalogue provisoire actif.
- Aucun achat, génération, stockage ou téléchargement de bordereau transporteur ; aucune réservation d'achat, outbox, tâche fournisseur ou intégration API Colissimo. Ces mécanismes appartiennent à C2.
- Aucun suivi transporteur automatique, aucune réception ou déclaration de dépôt déduite d'une étiquette.
- Aucune interface client/opérateur nouvelle pour saisir le catalogue ou télécharger une étiquette ; C1-B fournit les schémas, CLI, endpoints de sélection et aperçus backend. Le frontend existant est inchangé.
- Aucun second paiement, remboursement, annulation/remplacement de PI ou action sur un litige.

## 7. Conditions nécessaires à l'activation

L'activation financière n'est pas un simple changement du drapeau `logistics_enabled` : le garde constant C1-B doit faire l'objet d'une évolution validée, avec tests d'acceptation et de montant exact sur le parcours complet.

Il reste à obtenir et valider :

1. Grille professionnelle 2026 exacte, avenants et contrats SELBY, dates d'application et engagement permettant de figer aussi le coût du retour futur.
2. Produits réels dans chaque sens, signature retour, limites de poids/gabarit, zones métropolitaines et adresse SELBY structurée.
3. Assurabilité des catégories de cartes, valeurs admises et justificatifs, exclusions/franchises, couverture minimale contractuelle et éventuelles options supérieures ; l'hypothèse de 150 € ne suffit pas.
4. Profils de colisage validés pour les cartes et boîtiers, mesures admissibles et traitement opérateur des écarts après paiement, sans deuxième paiement automatique du retour normal.
5. Définition comptable du coût et fiscalité de chaque composante, avec ventilation et références validées ; aucun taux fiscal réel n'a été choisi ici.
6. Autorisation de publier une offre réelle en production et conception de son activation distincte du pointeur TEST ; revue des dates, révocations et historiques.
7. Validation des interfaces de présentation/consentement pour les nouveaux devis et des règles d'autorisation de départ retour avant l'éventuelle phase C2.

**Arrêt à C1-B. Le socle ne contourne aucune protection financière et n'autorise aucune émission de bordereau.**
