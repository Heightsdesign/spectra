# SELBY — Lot B, anomalie prioritaire B-P1

**Statut : reproduite en simulation, non corrigée ; validation du correctif requise.**

Exécution prioritaire : `20261105T222416Z_737c0e3b`.
Tests : `validation_tests/stripe_batch_b/test_batch_b.py::test_restriction_api_must_reject_new_shipment`.
Les six tests de protection échouent volontairement sur l'exigence HTTP 409 ; le comportement réel est HTTP 201.

## Reproduction

1. Préparer une commande et un devis acceptés synthétiques de 2 500 centimes EUR dans `spectra_test`.
2. Simuler une Session et un PaymentIntent payés via le transport en mémoire, puis livrer un événement signé
   avec le secret synthétique à la vraie route `POST /api/stripe/webhook`.
3. Vérifier un paiement et une échéance uniques.
4. Livrer un événement simulé de restriction, ou appliquer un blocage manuel via la vraie route staff.
5. Lire `GET /api/submissions/{id}/commercial-state` : `payment_status=restricted`,
   `charging_enabled=false`, restriction détaillée présente, paiement historique conservé.
6. Exécuter le vrai helper V1 `canDeclareShipment` sur cette réponse : résultat **false**.
7. `POST /api/submissions/{id}/stripe-checkout` : **HTTP 409**, conforme.
8. Avec l'utilisateur propriétaire, sa session et un CSRF valides, envoyer un nouveau `request_key` à
   `POST /api/submissions/{id}/shipment-declarations` : **HTTP 201**, une déclaration et un événement
   `customer_shipment_declared` sont créés malgré la restriction.

| Variante | Restriction exposée | UI autorise | API observée | Créations |
|---|---|---|---:|---:|
| Remboursement partiel 500/2500 | `partially_refunded` | Non | 201 | 1 déclaration + 1 audit |
| Remboursement total 2500/2500 | `refunded` | Non | 201 | 1 déclaration + 1 audit |
| Litige créé | `dispute_review` | Non | 201 | 1 déclaration + 1 audit |
| Remboursement échoué | `financial_review` | Non | 201 | 1 déclaration + 1 audit |
| Litige clôturé favorablement | `dispute_review` | Non | 201 | 1 déclaration + 1 audit |
| Blocage commercial manuel | `commercial_hold` | Non | 201 | 1 déclaration + 1 audit |

Les paiements, leurs dates, les échéances et les snapshots ne changent pas dans ces reproductions.
Toutes les transactions sont ensuite annulées : aucune déclaration de ce lot ne subsiste dans PostgreSQL.
Les empreintes complètes des bases de développement et de test sont identiques avant/après.

## Cause et portée

`app/commercial_api.py:62`, fonction `declare_shipment`, vérifie l'existence de l'acceptation et de
`VerifiedPayment`, sans vérifier les preuves de restriction. La présence d'un paiement historique reste
vraie après remboursement ou litige ; elle n'implique pas que le statut financier courant soit `verified`.

L'interface utilise au contraire le statut courant : `canDeclareShipment` exige `verified` et des dates valides.
Le tableau V1 ne s'actualise pas automatiquement lorsqu'il est déjà en `verified`, ce qui peut laisser
visible un bouton provenant d'un état antérieur jusqu'au prochain rafraîchissement. Le défaut API est donc
également pertinent pour un écran simplement périmé, sans falsification de compte ni de CSRF.

Ce défaut concerne une **déclaration client**, pas une réception physique, une autorisation de grading
ou un mouvement de custody. Aucune de ces protections physiques n'a été modifiée ou contournée.

## Correction minimale recommandée — proposition seulement

Dans `declare_shipment`, conserver l'authentification, CSRF, propriété, paiement historique et verrou
de commande existants. Pour une **nouvelle** clé de déclaration, contrôler `restricted(db, accepted.quote_id)`
avant toute insertion et refuser avec **HTTP 409**, par exemple `payment_financial_restriction`.

L'emplacement proposé est dans la branche de création, après la recherche de la clé idempotente et avant
la validation/création de la nouvelle déclaration. Ainsi :

- une nouvelle déclaration est refusée après toute restriction persistante ;
- un rejeu strictement identique d'une déclaration déjà créée peut rester une lecture idempotente,
  sans nouvelle ligne ni nouvel audit ;
- un rejeu de clé avec un contenu différent conserve son conflit d'idempotence ;
- les déclarations historiques, paiements, échéances et snapshots ne sont pas réécrits ;
- le contrôle reste dans la transaction et sous le verrou de commande déjà partagé avec les webhooks.

Le traitement précis d'un rejeu historique après restriction est à confirmer avec cette proposition.
Il ne doit jamais conduire à une nouvelle création ni à une levée de restriction.

Complément UX recommandé séparément : traduire ce refus, relire l'état commercial après ce conflit et
lors du retour au focus sur un suivi, sans perdre d'autres saisies non enregistrées. Le serveur reste
la protection déterminante ; le rafraîchissement UI ne remplace pas le contrôle API.

## Tests à exiger après autorisation du correctif

- Les six variantes présentes passent en HTTP 409 pour une nouvelle clé, avec zéro déclaration et zéro audit créés.
- Une commande payée sans restriction conserve la possibilité de déclarer son envoi.
- Propriété, CSRF, date future et conflits d'idempotence restent contrôlés.
- Rejeu identique d'une déclaration historique : aucun doublon et comportement explicitement validé.
- Course webhook de restriction/déclaration : sérialisation sous le verrou existant et décision cohérente avec l'ordre effectif des transactions.
- Paiement historique, montant, snapshot et échéance inchangés.

Aucun de ces correctifs n'est appliqué dans le lot B de simulations.
