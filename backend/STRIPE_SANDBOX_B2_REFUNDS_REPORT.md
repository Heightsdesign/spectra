# SELBY — Stripe Sandbox B2 : remboursements ciblés

Date : **6 novembre 2026**. Compte vérifié : **Selby sandbox**, `acct_1UXDxRFq5FKSG47y`. Stripe TEST uniquement ; base locale `spectra_test`.

**Les deux remboursements autorisés ont réussi : 500 + 2 500 = 3 000 centimes EUR TEST effectivement remboursés.** Aucun nouveau paiement, remboursement supplémentaire, expiration, annulation de PaymentIntent ou litige déclenché. Les services QA sont arrêtés.

## Résultats financiers

| Cas | Montant réellement remboursé | Refund Stripe | État Stripe | État SELBY |
|---|---|---|---|---|
| B-REFUND-PARTIAL | **500 centimes EUR / 5 € TEST** | `re_3UYlqMFq5FKSG47y04wJRJAg` | `succeeded`, Charge cumul remboursé 500, `refunded=false` | `restricted`, `partially_refunded` |
| B-REFUND-FULL | **2 500 centimes EUR / 25 € TEST** | `re_3UYlrMFq5FKSG47y0ebIhM87` | `succeeded`, Charge cumul remboursé 2 500, `refunded=true` | `restricted`, `refunded` |

Un seul objet Refund existe par Charge, confirmé par la liste canonique filtrée sur chaque Charge et par la lecture individuelle des Refunds. Les deux paiements historiques restent chacun à 2 500 centimes EUR. Ce montant historique n'est pas un solde net après remboursement.

Manifeste des cibles effectivement utilisées :

| Cas | Commande / devis | PaymentIntent | Charge |
|---|---|---|---|
| B-REFUND-PARTIAL | `4506971d-4a51-416c-8ef2-ffda7a5698b7` / `b1d71d00-e100-4465-9c21-f9c6cd3a81e0` | `pi_3UYlqMFq5FKSG47y0qC0NxuR` | `ch_3UYlqMFq5FKSG47y0hSlv6os` |
| B-REFUND-FULL | `540416f9-569f-4bad-ac9f-88b2b08e0fdd` / `73135787-893b-4658-8a62-1837a0e4f17c` | `pi_3UYlrMFq5FKSG47y0PEDXeRN` | `ch_3UYlrMFq5FKSG47y0Hu4sdnL` |

Résultats structurés : [`refund-results.json`](validation_artifacts/stripe_sandbox_b2/refunds/refund-results.json).

## Prévol avant mutation

Le manifeste de préparation `validation_artifacts/stripe_sandbox_b2/preparation/refund-targets.json` a été relu et son empreinte SHA-256 conservée. Il n'a pas été modifié. Son ancien indicateur `refund_authorized=false` décrit la préparation ; l'autorisation utilisateur distincte de cette phase est enregistrée dans le nouveau manifeste d'exécution avec les montants autorisés.

Le prévol a vérifié les deux cibles avant tout remboursement, puis l'ensemble des préconditions a été relu immédiatement avant chaque mutation :

- Clé TEST, compte exact `acct_1UXDxRFq5FKSG47y`, base `spectra_test`, environnement de développement.
- Deux Charges, PaymentIntents, Sessions, commandes et devis distincts.
- Métadonnées Session/PI/Charge identiques et conformes au client QA, à la commande, au devis, à l'obligation et à la tentative du manifeste.
- `livemode=false` sur les Sessions, PI et Charges ; devise `eur` ; montant initial, montant reçu et montant capturé tous à **2 500**.
- Session `complete/paid`, PI `succeeded`, Charge payée et capturée, sans litige.
- `amount_refunded=0`, `refunded=false` **et liste canonique des Refunds vide** pour chaque Charge avant son opération. Le contrôle ne repose donc pas uniquement sur le montant cumulé.
- Paiement historique, snapshot accepté et échéance identiques aux preuves de préparation.

Tout écart aurait interrompu l'exécution avant mutation. Aucun écart n'a été constaté.

## Exécution séquentielle et idempotence

L'unique opération partielle a été réalisée à **12:45:11 UTC**. Le remboursement intégral n'a été soumis qu'après validation du partiel : objets canoniques, restrictions, refus API, historique, rejeux et messages V1 vérifiés. L'unique opération intégrale a été réalisée à **12:47:27 UTC**.

Clés d'idempotence stables, persistées avec les paramètres avant les appels réseau :

```text
B-REFUND-PARTIAL
selby-b2-b-refund-partial-500-ch_3UYlqMFq5FKSG47y0hSlv6os

B-REFUND-FULL
selby-b2-b-refund-full-2500-ch_3UYlrMFq5FKSG47y0Hu4sdnL
```

Chaque appel a ciblé `POST /v1/refunds` avec la Charge exacte et le montant explicite, conformément au [contrat Stripe de création d'un remboursement](https://docs.stripe.com/api/refunds/create?api-version=2025-02-24.acacia). Aucun motif de fraude ou réglage Radar n'a été transmis. Aucun second appel de création de remboursement n'a été effectué pour tester l'idempotence : les rejeux de validation portent sur les webhooks réels.

Le contrôleur interdit une relance automatique après réservation d'une opération, y compris si sa réponse devient ambiguë. Les deux réponses reçues ici sont non ambiguës et `succeeded`. Aucune récupération ni opération de nettoyage n'a été nécessaire.

## Vérification complète après chaque remboursement

| Contrôle | B-REFUND-PARTIAL | B-REFUND-FULL |
|---|---|---|
| Refund canonique unique, bon PI/Charge/devise | Réussi | Réussi |
| Montant Refund / cumul Charge | 500 / 500 | 2 500 / 2 500 |
| `payment_status` SELBY | `restricted` | `restricted` |
| `charging_enabled` | `false` | `false` |
| Restriction financière | `partially_refunded` | `refunded` |
| Nouveau Checkout | HTTP **409** | HTTP **409** |
| Nouvelle déclaration d'expédition | HTTP **409** | HTTP **409** |
| Paiements historiques | 1, montant **2 500** inchangé | 1, montant **2 500** inchangé |
| Échéances historiques | 1, dates et politique inchangées | 1, dates et politique inchangées |
| Snapshots acceptés | Empreinte inchangée | Empreinte inchangée |
| Audit de confirmation initial | 1, inchangé | 1, inchangé |
| Déclarations créées par les tests de refus | **0** | **0** |
| Tentatives | 1, même identité, statut `restricted` | 1, même identité, statut `restricted` |

Les réponses de protection sont celles des routes métier, avec propriétaire et CSRF valides :

```json
POST /api/submissions/{id}/stripe-checkout
HTTP 409 {"detail":"payment_already_verified_or_restricted"}

POST /api/submissions/{id}/shipment-declarations
HTTP 409 {"detail":"payment_financial_restriction"}
```

Les identités des tentatives et le nombre de déclarations sont contrôlés avant et après : aucun Checkout ni aucune déclaration n'a été créé à la suite de ces appels refusés.

Les Sessions restent `complete/paid` et les PI `succeeded` chez Stripe : le remboursement ne réécrit pas le succès historique. L'autorisation commerciale actuelle de SELBY est bien `restricted`, à partir des preuves de restriction, et non déduite du seul ancien succès.

### Dates historiques conservées, UTC

| Cas | Paiement vérifié initial | Échéance conservée |
|---|---|---|
| B-REFUND-PARTIAL | 2026-11-06 **12:02:07** | 2026-12-06 **12:02:07** |
| B-REFUND-FULL | 2026-11-06 **12:03:09** | 2026-12-06 **12:03:09** |

Les lignes complètes des paiements et échéances, y compris leurs identifiants, dates d'enregistrement et événements fournisseur initiaux, ont été comparées à celles d'avant remboursement. Elles sont identiques.

## Webhooks réels et absence de double comptabilisation

Six événements uniques ont été reçus et traités, puis chacun a été rejoué une fois : **douze réponses backend HTTP 200**, dont six initiales et six rejeux.

| Cas | Type | Événement |
|---|---|---|
| Partiel | `refund.created` | `evt_3UYlqMFq5FKSG47y0RVMEbdG` |
| Partiel | `charge.refunded` | `evt_3UYlqMFq5FKSG47y0ReflzFo` |
| Partiel | `refund.updated` | `evt_3UYlqMFq5FKSG47y0UXktIzL` |
| Intégral | `refund.created` | `evt_3UYlrMFq5FKSG47y05q6I0Us` |
| Intégral | `charge.refunded` | `evt_3UYlrMFq5FKSG47y0LCvuXtD` |
| Intégral | `refund.updated` | `evt_3UYlrMFq5FKSG47y0abZpCVd` |

Chaque événement a traversé la vérification applicative de signature et la relecture canonique normale. Les corps bruts et signatures d'origine sont conservés dans des enveloppes locales privées. Les rejeux ont retransmis exactement les mêmes corps et signatures, sans re-signature ni événement synthétique ; leurs empreintes correspondent à celles enregistrées à l'entrée backend. Âge des signatures au lancement des rejeux : **24,03 à 45,29 secondes**, dans la tolérance existante inchangée.

La conformité ne repose pas sur ces seuls HTTP 200. Après les rejeux, les contrôles confirment :

- Toujours **un seul Refund** par Charge, status `succeeded`, cumul toujours exactement **500** ou **2 500**.
- Toujours un seul paiement historique de 2 500 centimes, un audit de confirmation et une échéance par commande.
- Toujours **cinq preuves Stripe par obligation** : les deux preuves initiales de paiement et les trois nouvelles preuves de remboursement. Le rejeu n'ajoute aucune ligne.
- Les observations cumulées de remboursement des preuves restrictives restent à 500 ou 2 500 ; elles ne sont pas additionnées entre événements pour produire un faux cumul de 1 500 ou 7 500.

L'état applicatif ne présente pas un solde net agrégé de remboursement. Les montants réellement remboursés sont donc contrôlés sur les Refunds et les Charges canoniques, tandis que l'idempotence locale est contrôlée sur les lignes de preuve, confirmations, audits, dates et restrictions.

L'intégration reste en version `2025-02-24.acacia` ; les événements du listener sont en `2026-10-28.endive`, comme aux phases précédentes. Aucun réglage de version du compte n'a été modifié.

## Interface V1 après actualisation

Les deux pages de suivi ont été ouvertes puis explicitement actualisées :

- Partiel : « **Examen requis** », « Cette commande comporte une restriction financière. Contactez SELBY avant toute nouvelle action. », « **Remboursement partiel — examen requis** ».
- Intégral : mêmes messages de blocage, avec « **Remboursement intégral — examen requis** ».
- Aucun bouton de nouveau paiement ni de déclaration d'envoi n'est proposé. Le bouton d'actualisation reste disponible.
- Montant historiquement payé affiché : **25 €** ; échéance historique conservée. Aucun indicateur de réception physique n'a été créé.

Captures : `B-REFUND-PARTIAL-v1-restricted.png`, `B-REFUND-PARTIAL-v1-after-refresh.png`, `B-REFUND-FULL-v1-restricted.png`, `B-REFUND-FULL-v1-after-refresh.png`.

## Alerte V1 persistante : scénario, cause et proposition minimale

**Aucun correctif frontend n'a été appliqué.** Le diagnostic contrôlé de la préparation reste la preuve reproductible ; les événements de remboursement réels n'ont pas été remplacés par une simulation.

### Scénario reproductible établi

1. Ouvrir une page de suivi QA déjà chargée, dont l'état serveur est valide.
2. Faire échouer une seule requête locale **GET `/commercial-state`** déclenchée au focus, par exemple par interception navigateur. Ne modifier ni paiement, ni webhook, ni données enregistrées.
3. Constater l'alerte « Impossible de charger la commande. Vos données enregistrées sont conservées. ».
4. Retirer l'interception et redonner le focus : la lecture suivante réussit HTTP 200 et restitue l'état financier correct.
5. Constater que l'alerte reste affichée malgré ce succès.
6. Cliquer sur « Actualiser le statut » : l'alerte disparaît, avec l'état financier inchangé.

La préparation a enregistré deux lectures navigateur HTTP 200 après la panne contrôlée, ainsi que les captures de l'alerte persistante puis de sa disparition au rafraîchissement manuel. Voir `preparation/v1-diagnostic.json` et `preparation/V1-diagnostic-*.png`.

### Cause prouvée et limite du diagnostic

Dans `frontend/src/components/order-workspace.tsx`, `load()` (ligne 48) et `refreshCommercial()` (ligne 73) mettent les données à jour en cas de succès sans effacer l'erreur de lecture précédente. Les échecs au chargement, au focus et au polling appellent `setError(t.error)` aux lignes 68, 78 et 85. Le rafraîchissement manuel (ligne 148) efface explicitement cet état. **La persistance de l'alerte est donc expliquée par un état d'erreur obsolète, partagé avec les erreurs d'action.**

Ce diagnostic explique le comportement reproductible de persistance. La requête et la panne réseau exactes qui avaient initialement déclenché l'alerte spontanée B1-R restent non déterminées : cette origine ne doit pas être présentée comme prouvée.

### Correction minimale proposée, soumise à validation distincte

Limiter la modification à la gestion des erreurs de lecture dans `OrderWorkspace` :

1. Distinguer l'erreur de relecture des erreurs d'action métier.
2. Effacer une erreur de lecture seulement après réussite de la relecture correspondante, encore courante. Une réussite partielle de `/commercial-state` ne doit pas masquer une erreur portant sur un autre élément du chargement complet.
3. Ignorer les résultats obsolètes ou postérieurs au démontage, afin qu'un ancien échec ne réaffiche pas l'alerte après un succès plus récent.

Conserver les formulaires, leurs saisies non enregistrées, les erreurs de conflit/validation/restriction et l'autorisation exclusivement backend. Ne pas ajouter un simple `setError('')` global à tout succès : cela pourrait effacer une erreur métier encore pertinente.

Validation à prévoir avec la correction : échec puis succès au focus et au polling ; réponses concurrentes dans les deux ordres ; erreur de chargement complet non masquée par une lecture commerciale seule ; conservation des erreurs métier et des saisies ; absence de mise à jour après démontage. Aucun de ces changements n'a été engagé dans cette phase.

## B-P2

**B-P2 reste ouvert.** Les relevés canoniques de cette phase conservent les Sessions `complete/paid` et les PI `succeeded` malgré les remboursements, avec restriction commerciale séparée. Aucun état `complete/unpaid + requires_action` n'a été observé. Cette phase ne teste pas un nouveau challenge 3DS et ne démontre pas l'impossibilité de B-P2. Aucune règle de reprise n'a été modifiée.

## Intégrité et arrêt

[`isolation-final.json`](validation_artifacts/stripe_sandbox_b2/refunds/isolation-final.json) confirme :

- **Base de développement intégralement inchangée**, selon les empreintes de toutes ses tables ; les deux commandes protégées sont conservées.
- Toutes les lignes préexistantes de `spectra_test` restent inchangées, avec pour seule exception autorisée les deux statuts de tentative passés de `verified` à `restricted`. Les autres champs de ces tentatives ont été comparés séparément et sont identiques.
- Lignes historiques de paiement et d'échéance et empreintes des snapshots inchangées pour les deux cibles ; aucune déclaration créée par les appels refusés.
- Colonnes, contraintes, index et triggers inchangés ; révision `0015`. Aucune migration ni purge.
- Sources `app`, `frontend/src` et fichier `backend/.env` inchangés. Aucun changement métier, de règles de reprise ou de frontend.
- Deux opérations de remboursement, total effectif **3 000 centimes EUR TEST** ; aucun nouveau paiement et aucun litige déclenché.

Services QA arrêtés : ports `13010`, `18010`, `19313`, `19314` fermés ; aucun listener Stripe CLI restant sur la cible QA `18010`. Le fichier généré `frontend/next-env.d.ts` est identique à sa copie avant la phase. Les services de développement n'ont pas été modifiés et les preuves QA sont conservées sans nettoyage financier.

## Preuves conservées

Dossier : `validation_artifacts/stripe_sandbox_b2/refunds/`.

- `manifest.json`, `*-preflight.json`, `*-immediate-before-mutation.json` : autorisation et rattachements avant mutation.
- `*-mutation-reserved.json`, `*-refund-response.json`, `mutations.jsonl` : paramètres exacts, clés d'idempotence et résultats des deux seules mutations.
- `refund-results.json`, `*-final.json`, `*-conformity.json` : Refunds/Charges/PI/Sessions canoniques et résultats financiers SELBY.
- `*-rejected-actions.json` : vrais refus métier Checkout et expédition HTTP 409, sans nouvelle tentative ni déclaration.
- `*-before-replay.json`, `*-after-replay.json`, `event-evt_*.json`, `canonical-event-evt_*.json`, `webhooks.jsonl`, `replays.jsonl` : signatures, événements, résultats et invariants après rejeu.
- `api.jsonl`, `v1-api.jsonl` et captures PNG : réponses commerciales et restrictions V1 après actualisation.
- `before.json`, `isolation-final.json`, `shutdown.json` : intégrité et arrêt.

Les enveloppes signées originales, cookies QA et profils navigateur restent dans des fichiers locaux `private-*` exclus de Git. Les exports publics retirent les secrets client et URL de reprise ; les logs masquent le secret du listener.

**Arrêt après les deux remboursements ciblés. Aucun scénario de litige commencé. Toute phase suivante et toute correction frontend attendent une validation distincte.**
