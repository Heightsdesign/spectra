# SELBY — Stripe TEST, lot A : idempotence et sécurité

Validation du 5 novembre 2026. Exécution finale : `20261105T185149Z_6af3b0a3`.

**Résultat final : 53 tests réussis, 0 échec, 0 scénario ignoré. Aucune correction métier nécessaire.**

## Périmètre et isolation

- Code applicatif testé sans modification : routes HTTP FastAPI, authentification/CSRF, vérification HMAC,
  montant et rattachement Stripe, confirmation financière, échéance et idempotence.
- PostgreSQL existant `spectra_test`, déjà à `0015` : aucune migration ni création de schéma/table.
- Le runner ne charge pas `tests/conftest.py`, qui applique habituellement Alembic.
- Les opérations Alembic sont bloquées, comme les verbes SQL non autorisés. Aucun appel bloqué n'a été tenté.
- Les accès HTTP réels du transport Stripe sont bloqués ; leur compteur est **0**.
- Les données Stripe et les secrets de signature utilisés sont entièrement synthétiques. Aucun identifiant
  ni événement des deux commandes payées n'a été réutilisé pour les simulations.
- La base de développement `spectra` n'a été ouverte qu'en lecture seule. Les empreintes SHA-256
  avant/après des commandes, cartes déclarées, devis, acceptations, obligations, paiements, tentatives,
  preuves webhook, échéances, audit commercial, adresses et choix de retour sont identiques.
- Les empreintes du schéma (colonnes, contraintes, index, triggers et fonctions) sont également identiques
  avant/après sur les bases contrôlées. Les triggers d'immutabilité n'ont jamais été désactivés.

Les compteurs de développement restent exactement : **2 obligations, 2 confirmations de paiement,
2 tentatives Checkout, 4 preuves webhook et 2 échéances**.

## Scénarios exécutés

| Famille | Tests | Résultat vérifié |
|---|---:|---|
| Rejeux des deux événements dans les deux ordres | 2 | 13 livraisons HTTP par ordre ; toujours 1 confirmation, 1 échéance et 2 preuves d'événements distincts |
| Nouveaux identifiants d'événement pour le même PaymentIntent | 1 | Pas de deuxième crédit ; dates et identifiants de la confirmation initiale conservés |
| Même identifiant d'événement avec corps modifié | 1 | HTTP 400 ; aucune modification du paiement initial |
| Signatures invalides | 7 | HTTP 400 avant consultation du fournisseur simulé : signature absente, malformée, mauvais digest, mauvais secret, corps modifié, horodatage expiré, horodatage dupliqué |
| Montants et objets Stripe canoniques incorrects | 14 | HTTP 400 : sous/sur-montant Session ou PaymentIntent, montant Charge incorrect, devise incorrecte, mode incompatible, références incorrectes, objets LIVE |
| Métadonnées devis/obligation/commande/client incorrectes | 5 | HTTP 400 ; aucune confirmation ni échéance |
| Comptes, environnement et tentatives incorrects | 6 | Compte d'événement incorrect, événement LIVE, tentative inconnue/absente, PaymentIntent d'une autre session : HTTP 400 ; compte fournisseur incorrect : HTTP 503 |
| Règlement incomplet/non définitif | 5 | HTTP 200 et état `pending`, mais **0 confirmation et 0 échéance** |
| Configuration LIVE ou production | 3 | Configuration refusée par `Settings` |
| Garde-fous LIVE/production/désactivation à l'exécution | 4 | Checkout et webhook signé refusés avec HTTP 503, sans appel fournisseur |
| Autre client | 1 | Consultation et paiement de la commande d'autrui : HTTP 404 ; injection du devis d'autrui dans sa propre commande : HTTP 409 |
| Modification du payload et CSRF | 1 | Montant/devise/indicateur `paid` imposés : HTTP 422 ; CSRF absent : HTTP 403 |
| Double clic séquentiel | 1 | Même réponse, 1 tentative, 1 session simulée, aucun crédit prématuré |
| Réponse fournisseur perdue après création simulée | 1 | Reprise avec la même clé d'idempotence et une seule session simulée |
| Concurrence HTTP et PostgreSQL | 1 | 6 demandes Checkout concurrentes, puis 8 livraisons webhook concurrentes : toutes HTTP 200, 1 tentative, 1 confirmation, 1 échéance |

Total : **53**.

Les rejeux comparent explicitement `verified_at`, `recorded_at`, la date de paiement de l'échéance,
`dispatch_deadline`, les identifiants de la confirmation et l'empreinte du snapshot. Ces valeurs restent
strictement identiques. L'échéance est exactement 30 jours après le paiement vérifié.

Un HTTP 200 n'est pas assimilé à un paiement réussi : les cinq cas de règlement non définitif
incluent un `amount_received` insuffisant, un PaymentIntent en traitement, une session impayée,
une charge non payée et une charge non capturée. Ils sont acquittés sans crédit financier.

## Échecs rencontrés et correction du harnais

Le premier lancement a eu **50 échecs de harnais et 3 réussites** : le token de session synthétique
ne respectait pas le format de 43 caractères imposé par l'authentification. Les appels étaient donc
refusés en HTTP 401 avant les contrôles Stripe. Le format des fixtures a été corrigé ; le cas production
utilise aussi le nom de cookie correspondant. Aucun contrôle applicatif n'a été modifié ou contourné.

L'exécution complète finale réussit. Aucune anomalie applicative observée dans les scénarios du lot A.
Deux avertissements d'outillage sont présents : dépréciation de l'intégration httpx de TestClient et
option `cache_dir` sans plugin de cache, volontairement désactivé pour ce runner.

## Données synthétiques conservées dans la seule base de test

Les tests séquentiels utilisent des savepoints puis un rollback intégral.
La concurrence utilise de vraies connexions indépendantes et des commits ; ses fixtures restent
identifiées dans `spectra_test`, afin de ne pas purger ou contourner les protections d'immutabilité.

- Premier lancement interrompu : commande synthétique `142e1af8-b3ab-4327-80e4-073a92ff84bb`,
  obligation sans paiement, sans tentative et sans échéance.
- Exécution finale : commande synthétique `80424d24-dd87-419a-84a2-5cb777b8421f`, devis
  `fdbac55d-86dc-45a0-850a-ee4fc50ef2f6`, 1 confirmation simulée, 1 tentative, 2 preuves et 1 échéance.

Ces enregistrements ne correspondent à aucun objet Stripe réel. Aucune donnée existante de développement
n'a changé. La suite du lot A est relançable, car ses assertions sont filtrées par identifiants de fixture.
Les anciennes suites qui supposent une base de test globalement vide devront disposer d'une base propre
avant leur exécution ; aucune purge n'a été faite dans ce lot sans autorisation spécifique.

## Limites non vérifiées

- Pas de rejeu effectué par Stripe Dashboard/CLI ni sur un endpoint publiquement exposé.
- Pas de validation du réseau, des délais/retries Stripe réels ni de la gestion des clés dans le Dashboard.
- Les réponses Stripe API sont simulées. Le code de signature et les routes HTTP réellement utilisées
  par l'application sont exécutés, mais aucune signature produite par Stripe n'est demandée ici.
- La concurrence couvre 6 appels Checkout et 8 webhooks simultanés, pas une campagne de charge multi-hôtes.
- Aucun remboursement, litige, nouveau paiement TEST ou appel LIVE. Ces parcours ne font pas partie de ce lot.
- Les fixtures partent d'une obligation acceptée synthétique de 2 500 centimes ; la création du devis
  complet depuis le frontend n'est pas rejouée dans ce lot de résistance.

## Reproduction et preuves

Depuis `backend` :

```powershell
.\.venv\Scripts\python.exe validation_tests\stripe_batch_a\run.py
```

Le runner refuse une base différente d'une base locale dédiée portant le suffixe `_test`, et refuse une
révision différente de `0015` au lieu de migrer. Il ne modifie pas `.env` et n'utilise pas les secrets Stripe réels.

Preuves de l'exécution finale :

- `validation_artifacts/stripe_batch_a/20261105T185149Z_6af3b0a3/results.json` : résultats par scénario.
- `validation_artifacts/stripe_batch_a/20261105T185149Z_6af3b0a3/isolation.json` : empreintes avant/après et absence de DDL/réseau Stripe.
- `validation_artifacts/stripe_batch_a/20261105T185149Z_6af3b0a3/concurrency.json` : compteurs de concurrence et conservation des dates.

Fichiers ajoutés uniquement : le présent rapport et les trois fichiers `conftest.py`, `test_batch_a.py`,
`run.py` sous `validation_tests/stripe_batch_a`, ainsi que les artefacts de validation. Aucun fichier
applicatif, fixture habituelle ou migration n'a été changé.
