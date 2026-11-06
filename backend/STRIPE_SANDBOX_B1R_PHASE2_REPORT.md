# SELBY — Stripe Sandbox B1-R, deuxième partie

Exécution du **6 novembre 2026**, compte **Selby sandbox** `acct_1UXDxRFq5FKSG47y`, clé TEST exclusivement, base locale `spectra_test`, schéma `0015`.

**B-EXPIRE et B-DELAY sont conformes aux contrôles exécutés.** Cette phase a créé **deux Sessions** (remplacement B-EXPIRE et B-DELAY), **une seule nouvelle commande QA**, et **un seul paiement TEST réussi de 25 €**. Une seule expiration explicite a été exécutée, sur la Session B-ABANDON autorisée. Aucun remboursement, litige, annulation de PaymentIntent ou autre expiration forcée.

## Résultats

| Scénario | Stripe réel | SELBY / V1 | Verdict |
|---|---|---|---|
| B-EXPIRE | B-ABANDON initialement `open/unpaid`, sans PaymentIntent. Expiration ciblée : `expired/unpaid`, sans PI. Ancienne URL sans formulaire ni bouton de soumission. Remplacement distinct `open/unpaid`, sans PI. | Passage à `expired` et « Session expirée — réessayer », puis `pending` et « Paiement en cours de vérification ». Zéro paiement, zéro échéance. Une seule Session payable à chaque relevé ; aucune coexistence de deux Sessions ouvertes. | **Réussi** |
| B-DELAY, avant livraison | Session `complete/paid`, PI `succeeded`, 2 500 centimes reçus ; deux événements de succès retenus par le proxy. | Toujours `pending`, zéro confirmation, zéro échéance, zéro preuve webhook enregistrée dans l'obligation. Retour navigateur puis `paid=true` et actualisation sans confirmation prématurée. | **Réussi** |
| B-DELAY, livraison puis rejeu | Deux événements authentiques livrés, puis mêmes corps et signatures rejoués une fois chacun. | Quatre réponses backend HTTP 200. Une seule confirmation, un seul audit de confirmation, une seule échéance ; V1 affiche « Paiement vérifié ». | **Réussi** |

## B-EXPIRE — manifeste et preuves réelles

Commande réutilisée : `c0c144df-9acb-417c-9b98-6755f73dfe91`, ancien cas B-ABANDON. Devis/obligation : `3b1452f1-5f64-4981-96f9-488aa368df23`. Client QA existant : `4b46aa58-c2c5-49c7-af55-a6c44ba33eb5`.

| Objet | Identifiant | État final |
|---|---|---|
| Session initiale autorisée | `cs_test_a1HLmQrotUiKh8VSAkSS9aFVpagjCBXH2CyjNRdimlgluvZPYeaVWSmWI8` | `expired/unpaid`, aucun PI |
| Tentative initiale | `44008cfc-4a28-4eb9-be97-a820b8bc7edb` | `expired` |
| Session de remplacement | `cs_test_a12tAC8rzDcWB5dof2HcoHEjtiKmbABlF9hubzAkUmCjZ2YOM76wrjozAb` | `open/unpaid`, aucun PI |
| Tentative de remplacement | `d08fc8cf-5270-483a-b70d-d1f315b078c9` | `pending` |
| Événement Stripe d'expiration | `evt_1UYlKRFq5FKSG47ysZiiGmaB` | `checkout.session.expired`, backend HTTP 200 |

Le prévol et le contrôle immédiatement avant l'opération ont vérifié le compte TEST, le `cs_test_`, `livemode=false`, les métadonnées de la commande et du devis, `amount_total=2500`, devise `eur`, état ouvert et impayé, PI absent et absence de paiement SELBY. L'unique appel d'expiration cible cet identifiant exact ; sa réponse canonique confirme `expired`.

L'ouverture de l'ancienne URL affiche : « Vous avez effectué votre paiement ou cette session de paiement a expiré. » Aucun formulaire de soumission n'est présent. Le message Stripe est générique ; les objets canoniques confirment ici une expiration, pas un paiement.

Le webhook d'expiration a été accepté avant le clic V1 : **un seul clic** a donc créé le remplacement selon les règles existantes. La variante « expiration constatée au premier clic, remplacement au suivant » n'a pas été exercée dans cette exécution. Le contrôleur QA a relu l'ancienne Session et exigé `expired/unpaid` sans PI avant d'autoriser la création du remplacement. Ce dernier n'a reçu aucune saisie de carte ni aucun paiement.

Cette inutilisabilité de la Session expirée correspond au [contrat Stripe d'expiration Checkout, version applicative](https://docs.stripe.com/api/checkout/sessions/expire?api-version=2025-02-24.acacia).

## B-DELAY — manifeste et paiement

Client QA dédié : `d28313cc-be52-4f61-981a-0000574de768`.

| Objet | Identifiant |
|---|---|
| Commande | `fe30de1b-bcde-4131-9a54-a27605ea3126` |
| Devis / obligation accepté | `58e4c334-99a7-461c-a51c-8e5a5cc812a6` |
| Tentative unique | `1e106cb5-3680-4951-b33b-92e02b6d3077` |
| Session unique | `cs_test_a1me6IZauES2ta5hgAAUVR1KN6wwFQjvPjFj2xKJsQXiZFxRSezPhhLKY0` |
| PaymentIntent | `pi_3UYlMeFq5FKSG47y1m7m1dm2` |
| Charge | `ch_3UYlMeFq5FKSG47y1aQHEX5s` |
| Succès PI | `evt_3UYlMeFq5FKSG47y18lFnzWP` |
| Session terminée | `evt_1UYlMfFq5FKSG47yP7wJUDMD` |

Le devis fictif a été créé, confirmé et accepté par les routes applicatives existantes : deux cartes Standard + Classic, grading 20 €, retour fictif France 5 €, taxe synthétique 0 €, total **2 500 centimes EUR**. Aucun nouveau catalogue n'a été publié pendant cette phase.

Le paiement a été effectué une seule fois dans Checkout hébergé avec la carte Stripe TEST `4242424242424242`. Les objets finaux confirment `livemode=false`, Session `complete/paid`, PI `succeeded`, `amount_received=2500`, Charge `paid=true` et `captured=true`, `amount_refunded=0`, `disputed=false`. Aucun autre paiement de cette phase n'a été soumis.

## Rétention et conservation de la signature

Le listener QA transférait vers le proxy local `127.0.0.1:18011`, puis vers le backend QA `18010`. Il était abonné aux familles d'événements traitables par l'application. Les événements de paiement de la commande B-DELAY ont tous été retenus ; aucun événement de cette obligation n'était autorisé à atteindre directement la route backend sans le marqueur privé du proxy. Le listener de développement n'a pas été modifié.

Avant paiement, un message à signature invalide a reçu HTTP 400 du proxy. La rétention a ensuite été armée et contrôlée vide avant l'unique paiement. Les deux messages Stripe réels ont été conservés avec :

- Corps brut original stocké sous forme binaire encodée, sans réorganisation ni réencodage JSON lors de la transmission.
- Valeur originale de `Stripe-Signature`, timestamp compris ; aucune signature de remplacement n'a été fabriquée.
- Empreintes SHA-256 du corps et de la signature, comparées aux empreintes reçues à l'entrée du backend pour chaque livraison et rejeu.
- Vérification par le proxy, puis à nouveau par la route applicative normale, avec le secret du même listener et la tolérance HMAC existante de 300 secondes, inchangée.

La vérification de signature sur le corps original suit le [contrat Stripe de vérification des signatures](https://docs.stripe.com/events/manage-webhook-endpoints#signature-errors).

**Un HTTP 200 du proxy pendant la rétention n'est pas une livraison acceptée par SELBY.** Les logs distinguent explicitement les deux : le proxy a accusé réception vers 11:31:25 UTC ; les réponses HTTP 200 de la route SELBY n'ont été obtenues qu'après la rétention.

Le relâchement était programmé 70 secondes après réception du premier événement. Avant tout transfert, un nouveau relevé canonique et SQL a confirmé Stripe payé mais aucun crédit, aucune échéance et aucune preuve webhook dans SELBY. Les événements ont ensuite été livrés avec le succès PI en premier, puis rejoués. Toutes les transmissions sont restées dans la fenêtre de 120 secondes prévue au protocole :

| Transmission | Réponse backend UTC | Âge de la signature à la réponse | HTTP |
|---|---|---|---|
| `payment_intent.succeeded`, livraison | 11:32:43.030 | 78,03 s | 200 |
| `checkout.session.completed`, livraison | 11:32:47.297 | 82,30 s | 200 |
| Même succès PI, rejeu | 11:32:50.039 | 85,04 s | 200 |
| Même Session terminée, rejeu | 11:32:52.799 | 87,80 s | 200 |

Les deux événements restent deux preuves distinctes d'un seul paiement. Après les quatre transmissions, le contrôle retrouve un paiement, un audit de confirmation, une échéance et deux preuves Stripe uniques.

## Horodatages et échéance

| Donnée | Valeur UTC |
|---|---|
| Succès fournisseur `payment_intent.succeeded.created` | **2026-11-06 11:31:25** |
| `VerifiedPayment.verified_at` | **2026-11-06 11:31:25** |
| `VerifiedPayment.recorded_at` | **2026-11-06 11:32:43.008374** |
| Retard d'enregistrement | **78,008374 secondes** |
| `DispatchExpectation.dispatch_deadline` | **2026-12-06 11:31:25** |

L'échéance est exactement à **paiement fournisseur + 30 jours**, sans décalage de 78 secondes. Le paiement conserve un `recorded_at` antérieur aux rejeux : ils n'ont pas remplacé l'enregistrement initial.

## V1 et observation UX

Les captures montrent : expiration puis attente sur B-EXPIRE ; sur B-DELAY, attente après retour Stripe, attente après `?stripe_return=1&paid=true` et actualisation, puis suivi « Paiement vérifié » après livraison. Aucune action de déclaration d'envoi n'a été exécutée.

Une **alerte de chargement transitoire** (« Impossible de charger la commande… ») est visible dans la première capture de retour B-DELAY, avec le statut financier encore correctement en attente. Elle disparaît au rechargement suivant ; le retour avec `paid=true`, l'actualisation et le passage à l'état vérifié fonctionnent ensuite. Sa cause n'est pas établie par cette exécution. Elle est conservée comme observation UX à surveiller, sans correctif métier ni frontend non autorisé et sans incidence financière observée.

## B-P2 et limites

**B-P2 n'a pas été reproduit et reste ouvert.** Les relevés d'expiration ne contiennent aucun PI ; les relevés après le paiement B-DELAY montrent directement `complete/paid + succeeded`. Aucun état `complete/unpaid + requires_action` n'a été constaté. Ces deux scénarios n'exercent pas un nouveau challenge 3DS et ne démontrent pas l'impossibilité de B-P2 ou d'états transitoires entre deux relevés.

Les appels de l'intégration restent en `2025-02-24.acacia`. Les événements réels du listener sont en `2026-10-28.endive`, comme en première partie ; aucun réglage de version du compte n'a été changé. Les trois événements uniques utiles à cette phase ont été traités, mais cela ne valide pas les autres familles ni tous les moyens de paiement.

La rétention courte avec signatures originales a été validée ici ; aucun retard dépassant 120 secondes, aucune re-signature, aucune redelivery Dashboard et aucun nouvel endpoint public n'ont été testés. Les tests des lots A/B n'ont pas été relancés dans cette phase sans modification applicative.

## Intégrité et arrêt

`isolation-final.json` confirme :

- Base de développement intégralement inchangée selon les empreintes de toutes ses tables, donc conservation des deux commandes payées protégées.
- Empreinte de schéma de test inchangée, révision toujours `0015`. Aucune migration, purge ou modification de schéma.
- Empreintes des fichiers `app`, de `frontend/src` et de `backend/.env` inchangées.
- Paiements, échéances et snapshots des cas payés B-DECLINE et B-3DS de la première partie inchangés.
- Snapshots B-EXPIRE et B-DELAY inchangés.
- B-EXPIRE : deux tentatives historiques, mais une seule Session encore payable ; zéro paiement et zéro échéance.
- B-DELAY : une tentative, un paiement de 2 500 centimes, un audit de confirmation et une échéance, même après rejeu.

Le contrôleur QA limitait les créations à un remplacement B-EXPIRE et une Session B-DELAY ; les autres mutations Stripe serveur restaient interdites. L'expiration ciblée est un appel séparé sur l'unique identifiant autorisé, vérifié immédiatement avant l'action et réservé avant l'appel réseau. Aucun code de reprise métier n'a été modifié.

Services QA arrêtés : ports `13010`, `18010`, `18011`, `19313` et `19314` fermés, aucun listener Stripe CLI restant sur la cible QA `18011`. Le fichier généré `frontend/next-env.d.ts` est identique à sa copie avant cette phase. Les deux nouvelles Sessions et les données QA restent conservées ; le remplacement B-EXPIRE est laissé ouvert et impayé, sans expiration de nettoyage.

## Preuves

Dossier : `validation_artifacts/stripe_sandbox_b1r/phase2/`.

- `manifest.json`, `session-ledger.json`, `stripe-operations.jsonl` : périmètre, rattachements et deux créations.
- `old-session-preflight.json`, `expiration-operation.json`, `B-EXPIRE-*.json` : prévol, expiration et remplacement.
- `B-DELAY-provider-paid-retained.json`, `B-DELAY-browser-paid-flag-retained.json`, `B-DELAY-pre-delivery-auto.json` : Stripe payé, SELBY non crédité avant livraison.
- `B-DELAY-post-delivery-auto.json`, `B-DELAY-final.json`, `B-EXPIRE-final.json` : états, paiements, échéances et preuves en base.
- `event-evt_*.json`, `canonical-event-evt_*.json` : événements reçus et relus chez Stripe, exports sans `client_secret`.
- `retention-selftest.json`, `retention-state.json`, `delivery.jsonl`, `backend-envelopes.jsonl` : validation du dispositif, rétention, réponses HTTP et égalité des empreintes.
- `checkout-api.jsonl`, `api.jsonl`, `v1-api.jsonl` : réponses applicatives ; les deux POST Checkout sont archivés HTTP 200 avec `status=pending` et URL présente, URL retirée de l'export public.
- Captures PNG des états Stripe et V1 ; `before.json` et `isolation-final.json` pour l'intégrité.
- Les enveloppes originales signées, accès QA et URL sont stockés dans des fichiers locaux `private-*`, exclus de Git avec le profil navigateur. Aucun secret de signature n'apparaît dans le rapport ou les logs publics.

**Arrêt après B-EXPIRE et B-DELAY. Aucun remboursement ni litige commencé. Une nouvelle autorisation est nécessaire avant toute phase suivante.**
