# SELBY — Stripe Sandbox B1-R, première partie

Exécution réelle le **6 novembre 2026**, compte **Selby sandbox**, `acct_1UXDxRFq5FKSG47y`. Les trois scénarios autorisés sont réussis. **Trois Sessions Checkout, deux paiements TEST réussis de 25 €, soit 50 € TEST ; aucun autre paiement réussi.**

## Résultat par scénario

| Cas | États réellement observés chez Stripe | Résultat SELBY / V1 | Verdict |
|---|---|---|---|
| B-DECLINE | D'abord `open/unpaid`, sans PI. Après carte de refus : même Session `open/unpaid`, PI `requires_payment_method`, erreur `card_declined / generic_decline`. Après reprise et carte valide : même Session `complete/paid`, même PI `succeeded`. | `pending`, puis `failed` / « Tentative échouée — réessayer Checkout », puis `verified` / « Paiement vérifié ». Aucun paiement ni échéance avant réussite ; ensuite une seule confirmation et une seule échéance. | **Réussi** |
| B-3DS | Challenge affiché ; Session `open/unpaid`, PI `requires_action`. Interruption par navigation hors du challenge : mêmes objets, toujours `open/unpaid + requires_action`. Reprise V1, nouvelle saisie de la même carte sur la même Session et second challenge : mêmes objets. Après bouton Complete du simulateur bancaire Stripe : `complete/paid + succeeded`. | `action_required` / « Action requise — reprendre Checkout » après réception du webhook. Aucun paiement ni échéance avant authentification. Après réussite : une confirmation et une échéance, « Paiement vérifié ». | **Réussi** |
| B-ABANDON | Session `open/unpaid`, PI absent. Retour avec le lien Stripe « Retour à Selby sandbox », sans saisir de carte. Reprise depuis V1 : même Session `open/unpaid`, PI toujours absent. | `pending` / « Paiement en cours de vérification », bouton « Reprendre Stripe Checkout ». Zéro paiement, zéro échéance, aucune fausse annulation ni confirmation au retour. | **Réussi** |

Cartes exclusivement issues de la [documentation officielle de test Stripe](https://docs.stripe.com/testing) : `4000000000000002` pour le refus générique, `4242424242424242` pour sa reprise réussie, `4000000000003220` pour le 3DS requis. Saisie dans le vrai Checkout hébergé, jamais création d'un paiement parallèle par API ou Dashboard.

## Manifeste des objets

Chaque scénario utilise son propre client QA dans `spectra_test`, deux cartes Standard + Classic, grading fictif 20 €, retour fictif France 5 €, taxe synthétique 0 €, devis accepté à **2 500 centimes EUR**. Les trois devis et commandes ont été créés via les routes applicatives existantes. Les clients et sessions d'authentification QA ont été provisionnés localement dans la seule base de test.

| Cas | Commande QA | Devis / obligation | Tentative |
|---|---|---|---|
| B-DECLINE | `72b147f5-3105-49a3-97f9-a3cccb246508` | `fee46f77-1c01-46b2-aa62-14dd1d58b8f7` | `650fdf27-4d2d-4b86-9af9-d1095b1840a9` |
| B-3DS | `f4e12894-7f53-422f-8a8b-631f4dbdc937` | `5719f71f-1d15-4e12-ab73-f4f4c0a2f45a` | `b2ea17a8-44aa-444f-a37b-7ae7a469680b` |
| B-ABANDON | `c0c144df-9acb-417c-9b98-6755f73dfe91` | `3b1452f1-5f64-4981-96f9-488aa368df23` | `44008cfc-4a28-4eb9-be97-a820b8bc7edb` |

| Cas | Session Stripe TEST | PaymentIntent | Charge finale réussie |
|---|---|---|---|
| B-DECLINE | `cs_test_a1IRqUhmuM7h8wTrTVMuqMOVK1D4zdCwXgQUTHSIPgcdiHNWyEJIPxePtC` | `pi_3UYjo3Fq5FKSG47y05NDxyiB` | `ch_3UYjo3Fq5FKSG47y0di5T9MU` |
| B-3DS | `cs_test_a1kuJ3LT0esdx2EInMrkDkhF7vffDC68OI0JJ2QHBXJCMwpfLdfDHMLw60` | `pi_3UYjqGFq5FKSG47y1dqC01J1` | `ch_3UYjqGFq5FKSG47y11lUQC32` |
| B-ABANDON | `cs_test_a1HLmQrotUiKh8VSAkSS9aFVpagjCBXH2CyjNRdimlgluvZPYeaVWSmWI8` | Aucun | Aucune |

Les objets canoniques finaux confirment `livemode=false`, devise `eur`, montant `2500`, rattachement au devis et à l'obligation QA. Les deux Charges sont `paid=true`, `captured=true`, avec `amount_refunded=0` et `disputed=false`.

La Charge B-3DS confirme en outre :

```json
{
  "authentication_flow": "challenge",
  "result": "authenticated",
  "version": "2.1.0",
  "electronic_commerce_indicator": "05"
}
```

## Observation de B-P2

**B-P2 n'a pas été reproduit dans cette exécution.** Aux relevés pendant le premier challenge, après son interruption, à la reprise et pendant le second challenge, le PaymentIntent était bien `requires_action`, mais la Session était **`open`**, pas `complete`. Après authentification réussie, elle est passée à `complete/paid` avec PI `succeeded`.

La reprise a donc pu réutiliser l'URL de la Session ouverte. Aucun nouveau PaymentIntent ni aucune nouvelle Session n'a été créé pour cette obligation. Aucun état canonique `complete/unpaid + requires_action` n'a été observé aux points de contrôle ; cela ne prouve pas son impossibilité dans tout parcours Stripe, ni l'absence d'un état transitoire entre deux relevés.

**B-P2 reste ouvert.** Le scénario simulé du lot B n'est pas requalifié comme conforme et aucune règle de récupération n'a été ajoutée. Aucun PaymentIntent n'a été annulé manuellement ou par le backend pendant ces scénarios.

L'interruption testée consiste à quitter la page pendant le challenge. Le bouton bancaire Fail, l'annulation explicite du challenge et d'autres types de navigation ne sont pas validés par cette exécution.

## API et webhooks réels

Le listener QA a transmis **sept événements réels**, tous traités en HTTP **200** avec vérification de signature par la route applicative :

| Événement | Type |
|---|---|
| `evt_3UYjo3Fq5FKSG47y02yuoRI2` | `payment_intent.payment_failed` |
| `evt_3UYjo3Fq5FKSG47y0zz7IyWY` | `payment_intent.succeeded` |
| `evt_1UYjpBFq5FKSG47yMd92z60e` | `checkout.session.completed` |
| `evt_3UYjqGFq5FKSG47y1dsLmPzD` | `payment_intent.requires_action` |
| `evt_3UYjqGFq5FKSG47y1MDVVHiu` | `payment_intent.requires_action` |
| `evt_3UYjqGFq5FKSG47y14Qf1Wbs` | `payment_intent.succeeded` |
| `evt_1UYjsUFq5FKSG47yRnGSGf1Y` | `checkout.session.completed` |

Aucun événement synthétique n'a été généré et aucune signature n'a été fabriquée. Les événements reçus et les lectures canoniques Stripe sont archivés. Les réponses commerciales GET avec leurs corps et statuts HTTP sont enregistrées par le contrôleur et par le navigateur V1 ; les réponses HTTP webhook sont également archivées. Les corps des POST Checkout immédiatement suivis d'une navigation n'ont pas été récupérés par CDP : leur résultat est corroboré par le registre de création, les Sessions réelles et les reprises observées, mais aucun corps de réponse non capturé n'est reconstruit comme une preuve réseau.

Les requêtes de l'intégration utilisent toujours `Stripe-Version: 2025-02-24.acacia`. Le compte/listener a fourni ses événements dans la version **`2026-10-28.endive`**. Cette différence est enregistrée, sans changer la version du compte ni les paramètres de l'intégration. Les sept événements de cette phase ont été correctement traités ; les autres familles d'événements ne sont pas validées par ce constat.

V1 peut brièvement afficher `pending` lors du démarrage d'une reprise ou avant livraison du webhook `requires_action`, alors que le PI canonique nécessite déjà une action. Cet état transitoire a été observé ; aucune confirmation prématurée ni échéance n'a été créée.

## Intégrité et respect du périmètre

Le contrôle final dans `isolation-final.json` confirme :

- Base de développement intégralement inchangée selon les empreintes avant/après de toutes ses tables ; les deux commandes payées protégées sont donc conservées.
- Schéma de la base de test inchangé selon l'empreinte des colonnes, révision toujours **0015**. Aucune migration, purge ou modification de schéma exécutée.
- Une seule tentative pour chacune des trois obligations ; exactement trois Sessions créées.
- B-DECLINE et B-3DS : un paiement vérifié de 2 500 centimes, une échéance à +30 jours, un audit de confirmation chacun.
- B-ABANDON : aucun paiement, aucune échéance, aucun audit de confirmation.
- Empreintes des trois snapshots acceptés inchangées.
- Deux paiements TEST réussis, montant cumulé **5 000 centimes EUR**.

Le banc est séparé des services de développement : backend `18010`, frontend V1 `13010`, profil Chrome QA distinct. La clé TEST et l'identité du compte ont été contrôlées avant les opérations Stripe, avec contrôles d'identifiants, montants et rattachements. Les mutations serveur étaient limitées à la création de l'unique Session de chacune des trois commandes du manifeste ; toute annulation, expiration, remboursement ou autre mutation Stripe côté serveur était refusée par le contrôleur QA. Les saisies ont exclusivement utilisé les cartes TEST et le challenge Stripe TEST.

Aucun code métier, fichier `.env`, règle de reprise, schéma ou migration n'a été modifié. Les ajouts se limitent au contrôleur QA, au pilote de navigateur, au présent rapport et aux preuves. Le catalogue fictif a été publié dans `spectra_test` uniquement lorsqu'aucun catalogue actif n'y était présent ; aucune configuration de développement n'a été remplacée.

Comme lors des autres lancements Next locaux, Next a automatiquement régénéré `frontend/next-env.d.ts` avec les chemins de types du dossier de compilation QA `.next-stripe-b1r-qa`. Il s'agit d'un fichier généré, sans changement des règles applicatives ; le prochain démarrage Next le régénérera pour son propre dossier de compilation.

Les services QA ont été arrêtés après les relevés : ports `18010`, `13010`, `19313` et `19314` fermés ; aucun processus Stripe CLI ne conserve la cible de transfert QA `18010`. Le listener de développement n'a pas été touché. Les données QA sont conservées sans purge. La Session B-ABANDON reste ouverte chez Stripe au dernier relevé ; aucune expiration forcée ni annulation n'a été demandée.

## Preuves conservées et limites

Dossier : `validation_artifacts/stripe_sandbox_b1r/phase1/`.

- `manifest.json`, `session-ledger.json` : identifiants QA et registre des trois créations.
- `B-DECLINE-*.json`, `B-3DS-*.json`, `B-ABANDON-*.json` : états canoniques Stripe et réponses commerciales par étape ; les fichiers `*-final.json` comprennent les Charges.
- `event-evt_*.json`, `webhooks.jsonl`, `listener.log` : événements Stripe réels et résultats HTTP, secret de signature masqué.
- `api.jsonl`, `v1-api.jsonl` : réponses applicatives conservées.
- Captures PNG : refus, statut V1 échoué, challenge 3DS, statut après interruption, statuts vérifiés, Checkout d'abandon et sa reprise.
- `before.json`, `isolation-final.json` : empreintes et contrôles d'intégrité.

Les secrets et URL de reprise ne figurent pas dans le rapport ; les champs `client_secret` sont retirés des exports canoniques. Le fichier d'accès QA et le profil navigateur restent locaux et sont exclus de Git par le `.gitignore` du dossier de preuves.

La validation porte sur ces trois parcours en français avec Chrome et les cartes TEST précisées. Elle ne démontre ni B-P2 dans tous les moyens de paiement/versionnements, ni les variantes d'échec du challenge, ni les délais contrôlés ou l'expiration. Les validations locales antérieures A 53/53 et B 32/33 ne sont pas remplacées par un nouveau lancement de leurs suites dans cette phase.

**Arrêt après B-DECLINE, B-3DS et B-ABANDON. Aucun B-EXPIRE, B-DELAY, remboursement ou litige exécuté. Toute poursuite attend une nouvelle autorisation.**
