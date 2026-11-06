# SELBY — Intervention B : Stripe Sandbox B-DISPUTE

6 novembre 2026. **Scénario conforme dans le périmètre autorisé. Services QA arrêtés.** Intervention indépendante de la correction V1, achevée et testée auparavant dans [son rapport A](../frontend/SELBY_V1_READ_RECOVERY_VALIDATION.md).

## Résultat réellement observé

Une seule Session et une seule soumission de la carte TEST autorisée `4061219946393810` ont produit un paiement de **2 500 centimes EUR**, puis **un litige automatique de 2 500 centimes EUR**. Aucun remboursement, second paiement, litige manuel, envoi de preuve ou clôture. Aucun appel LIVE.

Le litige canonique est `needs_response`, raison `fraudulent`, `livemode=false`. Il reste ouvert, sans intervention : `submission_count=0`, `has_evidence=false`, méthode `not_submitted`. Les champs d'identité que Stripe préremplit ne constituent pas une soumission de preuve par SELBY.

SELBY a effectivement rencontré la branche **1 paiement / 1 échéance avant restriction**. Après le litige, `payment_status=restricted`, `charging_enabled=false`, restriction `dispute_review`. Le paiement, son montant, le snapshot et l'échéance restent intégralement conservés. Les nouvelles opérations interdites répondent HTTP 409.

## Identité et manifeste

Compte vérifié avec la clé TEST avant préparation, création de Session et lectures canoniques : **`acct_1UXDxRFq5FKSG47y` — Selby sandbox**. Base exclusivement `spectra_test`, révision `0015`. Les objets financiers lus présentent `livemode=false`. API applicative `2025-02-24.acacia` ; événements réels reçus en `2026-10-28.endive`, sans réécriture ni changement de version du compte.

| Objet dédié B-DISPUTE | Identifiant exact |
|---|---|
| Client applicatif QA | `d88729fc-26a9-4d38-8be7-d0eeea748d4b` |
| Commande | `3063e697-2332-4b5b-b39f-8c962f069d6c` |
| Devis accepté / obligation | `1bd0a3e9-a4f1-4930-ba42-575c665c5452` |
| Tentative | `ac850523-042b-42b9-80af-1e9fd09a24e8` |
| Session | `cs_test_a1M50uAEV1IU0fN46SRXhXsGxBYOtJNFvmj3RYKGpXbbwD8ZHAKfu5CGSz` |
| PaymentIntent | `pi_3UYoWfFq5FKSG47y1oRIu6yn` |
| Charge | `ch_3UYoWfFq5FKSG47y1XxsdRzZ` |
| Dispute | `du_1UYoX6Fq5FKSG47ygalOLrMe` |
| Mouvement de solde du litige TEST | `txn_1UYoX7Fq5FKSG47yaSU4GONj` |

Le Customer Stripe de la Session est **null** ; le client applicatif QA est bien distinct et créé pour ce scénario. Les métadonnées exactes `customer_id`, `submission_id`, `quote_id`, `obligation_id`, `attempt_id` sont identiques sur Session, PI et Charge. Dispute est relié par sa Charge et son PI ; ses métadonnées sont vides. Aucun préfixe historique `dp_` n'a été imposé : l'identifiant réel est `du_`.

Le client, la commande, la livraison fictive, la confirmation, le devis et son acceptation utilisent le parcours existant. Aucun changement de catalogue ou de règle métier. Deux cartes fictives Standard + Classic : grading 20 €, retour fictif France 5 €, total 25 €.

Le manifeste [manifest.json](validation_artifacts/stripe_sandbox_b_dispute/manifest.json) contient les rattachements ; [session-ledger.json](validation_artifacts/stripe_sandbox_b_dispute/session-ledger.json) conserve la clé d'idempotence applicative et l'unique création réservée avant réseau. La soumission navigateur a aussi été réservée sur disque avant clic ; aucune relance automatique ambiguë n'est permise.

## Chronologie et paiement

Heures de Paris, UTC+1 le 6 novembre :

| Observation | Heure / résultat |
|---|---|
| Prévol immédiatement avant soumission | 15:53:42 : Session `open/unpaid`, aucun PI, aucun paiement ni échéance, une seule Session payable |
| Unique clic de paiement | 15:53:55.755, carte se terminant par 3810 |
| Paiement fournisseur | 15:53:58, `Session complete/paid`, `PI succeeded` |
| Confirmation SELBY enregistrée | 15:54:04.482100 |
| Dispute créé chez Stripe | 15:54:24, **26 secondes après le paiement fournisseur** |
| Événement d'ouverture créé | 15:54:26 |
| Webhook d'ouverture traité | 15:54:40.928313 |
| Lecture canonique suivante | 15:54:45.909555 : Dispute présent, SELBY `restricted`, branche 1/1 |

Checkout proposait une conversion facultative CHF. **EUR a été sélectionné avant soumission** ; Session, PI, Charge, Dispute et versement vérifié sont tous de 2 500 centimes EUR. Aucun paiement CHF n'a été effectué.

Le PI reçoit 2 500 centimes ; la Charge est payée et capturée à 2 500 centimes, `disputed=true`, `amount_refunded=0`, liste des remboursements vide. L'échéance est **6 décembre 2026 à 15:53:58**, exactement +30 jours depuis le paiement fournisseur, et non depuis la réception du webhook. Une seule confirmation auditée.

Le solde TEST comporte un retrait de litige `amount=-2500`, frais `fee=2000`, net `-4500` centimes EUR, statut `pending`. Ces **20 € de frais TEST** sont produits automatiquement par Stripe, distincts du paiement et du montant de l'obligation ; aucun nouveau paiement n'a été créé pour ces frais.

Preuves : [prévol immédiat](validation_artifacts/stripe_sandbox_b_dispute/B-DISPUTE-immediate-prepayment.json), [première confirmation](validation_artifacts/stripe_sandbox_b_dispute/B-DISPUTE-after-payment-01.json), [litige observé](validation_artifacts/stripe_sandbox_b_dispute/B-DISPUTE-dispute-observed.json), [objets finaux](validation_artifacts/stripe_sandbox_b_dispute/B-DISPUTE-final.json), [chronologie](validation_artifacts/stripe_sandbox_b_dispute/timing.json).

## Webhooks réels et idempotence

| Événement | Identifiant |
|---|---|
| `payment_intent.succeeded` | `evt_3UYoWfFq5FKSG47y183HAmWj` |
| `checkout.session.completed` | `evt_1UYoWgFq5FKSG47yowBzHwLo` |
| `charge.dispute.created` | `evt_1UYoX8Fq5FKSG47yW1Z7QiSL` |
| `charge.dispute.funds_withdrawn` | `evt_1UYoX8Fq5FKSG47yDmtUA5LG` |

**Quatre événements réels signés**, puis **un rejeu de chacun**, soit huit réponses HTTP 200. Les signatures Stripe originales et corps bruts sont conservés dans les fichiers privés ignorés `private-envelope-*`. Aucune signature fabriquée, aucun `stripe trigger`, aucun réenvoi réencodé. Âge des signatures lors des rejeux : environ 52 à 92 secondes, dans la tolérance existante. Les empreintes du corps et de la signature sont consignées.

La conformité dépasse les HTTP 200 : comparaison complète des états SQL avant/après rejeu, mêmes quatre lignes de preuve, un paiement, une échéance, une confirmation auditée, mêmes identifiants, montant, dates, snapshot, tentative et restriction. Les succès rejoués après restriction ne recréditent pas l'obligation.

Preuves : [webhooks.jsonl](validation_artifacts/stripe_sandbox_b_dispute/webhooks.jsonl), [replays.jsonl](validation_artifacts/stripe_sandbox_b_dispute/replays.jsonl), [conformity.json](validation_artifacts/stripe_sandbox_b_dispute/conformity.json). Les fichiers `event-evt_*.json` conservent les événements lisibles, sans URL ni secrets client.

## Refus API et V1

Avec propriétaire et CSRF valides, sur cette seule commande :

- Nouveau Checkout : **409**, `payment_already_verified_or_restricted`.
- Nouvelle déclaration : **409**, `payment_financial_restriction`.
- Après ces refus : une seule tentative, aucune déclaration créée, aucune nouvelle Session.

Preuve : [rejected-actions.json](validation_artifacts/stripe_sandbox_b_dispute/rejected-actions.json).

La vraie V1 QA affiche d'abord « Paiement vérifié ». Sur la page déjà ouverte, une relecture au focus affiche ensuite **« Examen requis »**, **« Litige — examen requis »** et le message de restriction. Une actualisation conserve cet état. Le paiement historique de 25 € et son échéance restent visibles, sans bouton de paiement ou déclaration d'envoi. Aucun faux état de réception physique n'est introduit.

En anglais : **« Review required »**, **« Dispute review required »**, montant €25.00 et échéance conservés. Aucune alerte de lecture persistante observée. Le contrôle de concurrence et la conservation des saisies reposent sur les tests indépendants de l'intervention A ; aucune saisie d'expédition n'a été soumise pour créer une déclaration dans ce scénario financier.

Preuves : [focus FR](validation_artifacts/stripe_sandbox_b_dispute/v1-focus-fr.json), [actualisation FR](validation_artifacts/stripe_sandbox_b_dispute/v1-refresh-fr.json), [état EN](validation_artifacts/stripe_sandbox_b_dispute/v1-restricted-en.json), [capture FR](validation_artifacts/stripe_sandbox_b_dispute/v1-restricted-focus-fr.png), [capture EN](validation_artifacts/stripe_sandbox_b_dispute/v1-restricted-en.png), [réponses API V1](validation_artifacts/stripe_sandbox_b_dispute/v1-api.jsonl).

## Intégrité et arrêt

Tous les contrôles avant/après réussissent dans [integrity-final.json](validation_artifacts/stripe_sandbox_b_dispute/integrity-final.json) :

- Empreintes de toutes les tables de développement identiques.
- Toutes les lignes QA préexistantes conservées à l'identique, y compris les scénarios B1-R et B2.
- Commandes protégées `c54cbac8-5098-423c-946f-02d7ec8d3915` et `d4dd84bf-5112-4301-a66c-cb51e2fdc4fd` inchangées.
- Colonnes, contraintes, index, triggers et révision `0015` inchangés : aucune migration, purge ou modification du schéma.
- Sources backend, frontend et `.env` identiques au prévol B, effectué **après** la correction autorisée A. Le seul outillage B ajouté/adapté réside dans les scripts QA ; aucune modification applicative B.

Backend, listener Stripe, Next et Chrome QA arrêtés. Ports 13010, 18010, 19313 et 19314 fermés ; les ports du banc A 18581–18583 sont également fermés. Aucun listener `stripe.exe` ciblant le webhook QA 18010 ne subsiste, vérifié après arrêt. Le fichier généré `next-env.d.ts` a été restauré à son contenu antérieur au démarrage B. Preuve : [services-stopped.json](validation_artifacts/stripe_sandbox_b_dispute/services-stopped.json).

## Limites et suites non exécutées

Le délai de 26 secondes est une observation de cette exécution, sans garantie sur les prochains tests. La branche où le litige précède toute confirmation n'a pas été exécutée ici. Aucune évolution `updated`, `closed` ou `funds_reinstated` n'est revendiquée ; le comportement de clôture ou de levée éventuelle de restriction reste hors périmètre. Le litige reste tel quel chez Stripe après arrêt du listener : ses évolutions futures ne sont pas couvertes par ce rapport.

La différence de version REST/événements est réelle et documentée ; la conformité observée ne prouve pas toutes les variantes de payload de versions futures. Aucun résultat LIVE n'est extrapolé.

**B-P2 reste ouvert et sa logique est inchangée.** Aucune lecture n'a montré `Session complete/unpaid + PI requires_action` ; cela ne clôt pas l'anomalie. Aucun nouvel écart financier ni régression observés dans ce scénario et les tests A. Le lint global garde la limite de fichiers générés explicitée dans le rapport A.

Mécanisme officiel vérifié : [carte de litige asynchrone Stripe](https://docs.stripe.com/testing#disputes), [liste des litiges filtrée par Charge](https://docs.stripe.com/api/disputes/list), [objet Dispute](https://docs.stripe.com/api/disputes/object). Le numéro de carte a uniquement été saisi dans Checkout hébergé ; aucun numéro de carte n'a été envoyé à l'API serveur SELBY.

**Arrêt après les deux interventions autorisées. Aucune suite financière, réponse ou clôture de litige n'est engagée.**
