# SELBY — Stripe Sandbox B2 : préparation des remboursements

Date : **6 novembre 2026**. Compte vérifié : **Selby sandbox**, `acct_1UXDxRFq5FKSG47y`. Base : `spectra_test`. Stripe TEST exclusivement.

**Les deux commandes QA sont préparées et payées : deux nouveaux paiements TEST de 25 €, soit 50 € TEST. Aucun remboursement, litige, annulation de PaymentIntent ou expiration déclenché.** Les services QA sont arrêtés. Toute opération de remboursement attend une autorisation distincte.

## Manifeste des paiements disponibles pour la suite

Les noms B-REFUND-PARTIAL et B-REFUND-FULL désignent les scénarios futurs ; **les deux paiements sont actuellement intégralement payés et non remboursés**. Le manifeste machine conserve `refund_authorized: false`.

| Cas | Commande QA | Devis / obligation | Payé | Remboursé | Confirmation / échéance |
|---|---|---|---|---|---|
| B-REFUND-PARTIAL | `4506971d-4a51-416c-8ef2-ffda7a5698b7` | `b1d71d00-e100-4465-9c21-f9c6cd3a81e0` | 2 500 EUR centimes | 0 | 1 / 1 |
| B-REFUND-FULL | `540416f9-569f-4bad-ac9f-88b2b08e0fdd` | `73135787-893b-4658-8a62-1837a0e4f17c` | 2 500 EUR centimes | 0 | 1 / 1 |

Identifiants exacts pour une future autorisation de remboursement :

| Cas | PaymentIntent Stripe TEST | Charge Stripe TEST |
|---|---|---|
| B-REFUND-PARTIAL | **`pi_3UYlqMFq5FKSG47y0qC0NxuR`** | **`ch_3UYlqMFq5FKSG47y0hSlv6os`** |
| B-REFUND-FULL | **`pi_3UYlrMFq5FKSG47y0PEDXeRN`** | **`ch_3UYlrMFq5FKSG47y0Hu4sdnL`** |

Autres rattachements :

| Cas | Client QA | Tentative |
|---|---|---|
| B-REFUND-PARTIAL | `cfd30385-69fc-405c-85e8-bc492c4e0950` | `15dbe960-0d44-4272-9428-749cb588accd` |
| B-REFUND-FULL | `e114aba9-81aa-4fb0-a2f6-99bdbc8ec843` | `0b6cc5b6-3aac-458e-b0c2-2aa6437d6b17` |

- Session B-REFUND-PARTIAL : `cs_test_a1G8ABzdExA4iEevPkrFM0wALID6WddpRV1GKiJBwcaNNoL28a6pbfgICb`.
- Session B-REFUND-FULL : `cs_test_a1HQnWwxt40AtoOcBlaMQ5cimJd7dODe9kMm5GQsLCxuQ4KZlRgjlEK6F4`.

Le manifeste exploitable est conservé dans [`refund-targets.json`](validation_artifacts/stripe_sandbox_b2/preparation/refund-targets.json). Il inclut le compte, le mode TEST, les montants, les UUID, les empreintes des snapshots, les identifiants Session/PaymentIntent/Charge et les dates. Aucun montant de remboursement n'est autorisé par ce rapport.

## Parcours et contrôles réels

Chaque commande a son client QA dédié. Les clients et sessions d'authentification ont été provisionnés localement dans `spectra_test` ; toutes les opérations de commande, adresse, configuration du retour, confirmation, création du devis et acceptation ont utilisé les routes applicatives existantes. Aucun snapshot accepté n'a été fabriqué directement en SQL.

Le devis fictif accepté comprend deux cartes Standard + Classic : grading 20 €, retour fictif France 5 €, taxe synthétique 0 €, total **25 €**. Les catalogues existants ont été lus sans publication supplémentaire.

Une seule Session a été initiée via le bouton V1 pour chaque commande. Le paiement a été soumis une seule fois par Session dans Checkout hébergé, avec la carte officielle Stripe TEST `4242424242424242`. [Référence des cartes TEST](https://docs.stripe.com/testing).

Avant les opérations, les contrôles ont rapproché la clé TEST, l'identité du compte, les commandes du manifeste, les métadonnées, les montants et les objets canoniques. Le contrôleur QA permettait uniquement la création d'une Session par obligation dédiée et refusait les autres mutations Stripe, y compris remboursement, litige, expiration et annulation. Une identité ambiguë après un appel de création ne pouvait pas déclencher automatiquement une seconde Session.

État final des deux paiements :

- Session `complete/paid`, `livemode=false`, `amount_total=2500`, devise `eur`.
- PaymentIntent `succeeded`, `livemode=false`, `amount_received=2500`.
- Charge `paid=true`, `captured=true`, `amount=amount_captured=2500`, `refunded=false`, `amount_refunded=0`, `disputed=false`.
- Charge rattachée au PI exact ; PI rattaché à la Session exacte ; métadonnées Charge/PI/Session concordantes avec la commande, le client et le devis.
- SELBY `verified`, `charging_enabled=false`, aucune restriction financière, une tentative, un paiement vérifié, un audit de confirmation et une échéance par commande.
- V1 affiche « Paiement vérifié » et 25 € payés pour les deux commandes. Aucun envoi n'a été déclaré.

La distinction entre montant capturé, montant remboursé et rattachement au PaymentIntent est vérifiée sur l'[objet Charge canonique Stripe](https://docs.stripe.com/api/charges/object?api-version=2025-02-24.acacia).

### Dates vérifiées

| Cas | Paiement vérifié, UTC | Échéance, UTC |
|---|---|---|
| B-REFUND-PARTIAL | 2026-11-06 **12:02:07** | 2026-12-06 **12:02:07** |
| B-REFUND-FULL | 2026-11-06 **12:03:09** | 2026-12-06 **12:03:09** |

Chaque échéance est exactement à +30 jours du paiement vérifié. Les identifiants et dates initiaux sont conservés pour vérifier leur immutabilité lors de la future phase autorisée de remboursement.

### Webhooks

Quatre événements réels signés ont été acceptés, tous HTTP **200** :

| Cas | Type | Événement |
|---|---|---|
| B-REFUND-PARTIAL | `payment_intent.succeeded` | `evt_3UYlqMFq5FKSG47y0Dfu0Vfc` |
| B-REFUND-PARTIAL | `checkout.session.completed` | `evt_1UYlqNFq5FKSG47yIYfrr5Ub` |
| B-REFUND-FULL | `payment_intent.succeeded` | `evt_3UYlrMFq5FKSG47y0lqQlmcb` |
| B-REFUND-FULL | `checkout.session.completed` | `evt_1UYlrNFq5FKSG47y5km7ivsk` |

Les événements ont été relus chez Stripe et archivés. L'intégration utilise toujours `2025-02-24.acacia` ; le listener fournit les événements en `2026-10-28.endive`, comme pendant B1-R. Aucun paramètre du compte Stripe n'a été changé.

## Alerte V1 — diagnostic sans modification frontend

### Ce qui est établi

L'alerte spontanée de B1-R ne s'est pas reproduite lors des deux retours de paiement B2 : les relevés montrent un suivi vérifié et aucun élément `role=alert` pour chaque commande. La cause réseau exacte de l'incident B1-R reste inconnue, faute de trace de la requête en échec à ce moment-là.

Un diagnostic contrôlé a ensuite été exécuté sur la page QA déjà payée B-REFUND-FULL, sans nouvelle action financière :

1. Une seule requête **GET locale** `/commercial-state` au focus a été interceptée et mise en échec par CDP. Il s'agit d'une panne synthétique du navigateur, explicitement identifiée dans les preuves, pas d'un échec Stripe ni d'une injection de webhook.
2. L'alerte « Impossible de charger la commande. Vos données enregistrées sont conservées. » est apparue.
3. Un second focus, sans interception, a effectué une lecture réussie HTTP 200. Le navigateur et le backend confirmaient `verified`, avec toujours un paiement et une échéance.
4. **L'alerte restait affichée malgré cette lecture réussie.**
5. Le bouton « Actualiser le statut » a ensuite supprimé l'alerte ; la lecture est restée réussie et l'état financier inchangé.

La lecture statique de `frontend/src/components/order-workspace.tsx` confirme ce mécanisme : les échecs de `load()`/`refreshCommercial()` positionnent l'état partagé `error`, mais une réussite ultérieure de ces lectures ne le réinitialise pas. `refresh()` manuel le réinitialise explicitement. La panne initiale B1-R n'est pas prouvée identique, mais **la persistance d'une erreur de lecture devenue obsolète est reproduite et justifie une correction ciblée**.

### Proposition à valider, non appliquée

Séparer l'erreur de relecture des erreurs d'action métier. Après une relecture serveur réussie et encore courante, effacer uniquement l'erreur de relecture correspondante. Protéger ces mises à jour avec une identité de requête ou un mécanisme équivalent pour qu'un échec ancien ne puisse pas réafficher l'alerte après un succès plus récent ; ignorer les résultats après démontage.

Cette proposition doit conserver les erreurs de validation, de conflit ou de restriction tant qu'elles restent pertinentes, ainsi que tous les champs non enregistrés et l'autorisation exclusivement serveur. Un simple effacement global de `error` à chaque succès pourrait masquer une erreur métier et n'est pas la correction recommandée.

Validation proposée avant intégration : échec GET puis succès au focus, échec puis succès du polling, réponses concurrentes dans les deux ordres, conservation d'une erreur d'action et des saisies non enregistrées, absence de mise à jour après démontage. **Aucun fichier frontend ni règle métier n'a été modifié.**

Preuves : `v1-diagnostic.json`, `diagnostic-injected-read-failure.json`, `v1-api.jsonl` et les trois captures `V1-diagnostic-*.png`. Les deux requêtes `GET /api/auth/me` HTTP 401 au démarrage du profil QA précèdent son authentification ; elles ne constituent pas une erreur de paiement ou la reproduction de l'alerte B1-R.

## B-P2

**B-P2 reste une anomalie ouverte.** Les nouveaux relevés montrent des Sessions ouvertes et impayées avant soumission, puis `complete/paid + succeeded` après paiement. Aucun état `complete/unpaid + requires_action` n'a été observé. Cette préparation avec carte TEST ordinaire ne teste pas un nouveau challenge 3DS et ne prouve pas l'impossibilité d'un état transitoire entre deux relevés. Aucune règle de reprise n'a été changée.

## Preuves d'intégrité

[`isolation-final.json`](validation_artifacts/stripe_sandbox_b2/preparation/isolation-final.json) atteste :

- **Base de développement intégralement inchangée**, selon empreintes avant/après de toutes ses tables ; les deux commandes protégées restent intactes.
- **Toutes les lignes préexistantes de `spectra_test` inchangées** : chaque empreinte de ligne présente avant la préparation existe encore avec la même multiplicité. Les données QA et paiements B1-R sont donc conservés, pas seulement leurs compteurs.
- Colonnes, contraintes, index et triggers du schéma inchangés ; révision toujours `0015`.
- Sources `app`, `frontend/src` et fichier `backend/.env` inchangés.
- Snapshots des deux devis B2 inchangés ; une confirmation, un audit et une échéance par obligation.
- Exactement deux nouveaux paiements TEST de 2 500 centimes, total **5 000 centimes EUR**, zéro remboursement et zéro litige déclenché.

Aucune migration, purge, publication de catalogue ni modification métier. Les seuls changements de code concernent les outils QA hors frontend applicatif. Les fichiers d'accès et profils navigateur sont locaux et exclus de Git. Le fichier généré `frontend/next-env.d.ts` est identique à sa copie avant la phase.

Les services QA ont été arrêtés : ports `13010`, `18010`, `19313`, `19314` fermés ; aucun listener Stripe CLI restant sur la cible QA `18010`. Le listener et les services de développement n'ont pas été modifiés. Les données QA restent conservées, sans opération financière de nettoyage.

## Fichiers de preuve

Dossier : `validation_artifacts/stripe_sandbox_b2/preparation/`.

- `manifest.json`, `refund-targets.json`, `session-ledger.json`, `stripe-operations.jsonl` : identités et deux créations autorisées.
- `B-REFUND-PARTIAL-final.json`, `B-REFUND-FULL-final.json` : objets canoniques Session/PI/Charge, état commercial, paiements, échéances et preuves SQL.
- `event-evt_*.json`, `canonical-event-evt_*.json`, `webhooks.jsonl`, `listener.log` : événements réels et réponses HTTP, secret de signature masqué.
- `api.jsonl`, `checkout-api.jsonl`, `v1-api.jsonl`, captures `B-REFUND-*-v1-paid.png` : parcours applicatif et résultats V1.
- `before.json`, `isolation-final.json`, `shutdown.json` : intégrité et arrêt des services.
- `v1-diagnostic.json` et captures associées : reproduction contrôlée de l'alerte persistante.

Les montants futurs et l'opération de remboursement elle-même doivent faire l'objet d'une nouvelle autorisation portant sur les objets exacts du manifeste. **Arrêt avant tout remboursement et tout litige.**
