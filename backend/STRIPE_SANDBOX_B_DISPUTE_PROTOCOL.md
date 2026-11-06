# SELBY — B-DISPUTE : protocole préparatoire Stripe Sandbox

Date : **6 novembre 2026**. **Document soumis à validation, sans exécution.** Aucun client, commande, devis, Checkout, paiement ou litige créé pour B-DISPUTE. Aucun appel à l'API de compte Stripe, aucun accès LIVE, aucune connexion aux bases ni aucun démarrage QA pendant cette préparation documentaire.

## 1. Mécanisme officiel retenu et risque de déclenchement

Pour une future exécution, retenir la carte Stripe TEST **`4061 2199 4639 3810`** (`4061219946393810`), correspondant au scénario de litige frauduleux asynchrone. La documentation actuelle indique qu'avec les réglages par défaut le paiement réussit puis un litige est créé peu après. Elle signale une protection après authentification 3DS pour ce type de litige. [Source Stripe, cartes de litige](https://docs.stripe.com/testing#disputes).

**Le paiement est lui-même le déclencheur du litige.** Il faut donc autoriser le paiement **et** sa conséquence automatique avant de saisir et soumettre cette carte. Une validation de préparation ou de paiement ordinaire ne suffira pas.

Adaptation à SELBY : saisir cette carte dans le Checkout hébergé créé par la route existante, en `mode=payment`, avec expiration future telle que `12/34`, CVC fictif `123`, identité et adresse QA. Ne pas envoyer le numéro de carte à l'API serveur, créer un PI direct ou utiliser un autre mécanisme en parallèle.

Cette compatibilité est **documentaire et déduite du parcours Checkout existant** ; elle n'est pas encore démontrée par une exécution dans notre compte. Si les réglages effectifs entraînent un refus, un challenge, une protection ou l'absence du litige attendu, arrêter pour analyse sans changer Radar, 3DS ou les moyens de paiement.

La carte synchrone `4000000000000259` n'est pas retenue pour ce premier scénario. Le test par remboursement partiel et les mécanismes de litiges multiples sont également exclus. Le mécanisme choisi ne requiert aucun remboursement préalable. [Référence Stripe des mécanismes TEST](https://docs.stripe.com/testing#disputes).

## 2. Périmètre proposé à autoriser ultérieurement

| Élément | Plafond proposé | Autorisé maintenant ? |
|---|---|---|
| Nouveau client applicatif QA | 1, dédié à B-DISPUTE dans `spectra_test` | Non |
| Commande et devis fictif accepté | 1 commande, 2 500 centimes EUR | Non |
| Session et tentative Checkout | 1 Session, 1 tentative, clé de création stable | Non |
| Paiement Stripe TEST avec la carte retenue | 1 soumission, au maximum 1 réussite de 25 € | Non |
| Litige automatique lié à ce paiement | 1 litige attendu, sur sa seule Charge ; montant attendu 2 500 centimes EUR | Non |
| Lectures canoniques, webhooks, contrôles API et V1, rejeux signés de cette seule obligation | À inclure dans l'autorisation d'exécution | Non |
| Répondre au litige, soumettre des preuves, accepter/perdre/gagner/clore | Hors phase initiale ; autorisation ultérieure par identifiant de litige | Non |
| Remboursement, paiement de remplacement, seconde tentative, expiration, changement métier/Radar/3DS | Hors protocole | Non |

La limite de 25 € concerne le paiement. Les mouvements et éventuels frais de litige du solde **TEST** seront relevés séparément s'ils sont produits par ce mécanisme ; ils ne constituent ni un nouveau paiement ni une modification du montant de l'obligation. Aucun mouvement LIVE n'est permis.

## 3. Séparation QA et manifeste à constituer après accord

Créer une nouvelle identité applicative fictive propre à B-DISPUTE, une commande et une obligation dédiées. Ne réutiliser aucun client, devis, PI ou Charge B1-R ou B-REFUND, ni aucun paiement déjà remboursé. Si Checkout crée un objet Customer Stripe selon sa configuration, l'archiver ; ne pas prétendre qu'un Customer Stripe existe lorsqu'il reste nul.

Utiliser backend et frontend QA distincts, base `spectra_test`, origine et profil navigateur séparés, clé `sk_test_` et `STRIPE_MODE=test`. Le compte attendu d'après les phases validées est `acct_1UXDxRFq5FKSG47y` (Selby sandbox) ; son identité devra être relue avec la clé TEST avant exécution. Si un autre Sandbox est souhaité, son choix et ses identifiants doivent être validés avant toute création.

Construire progressivement le manifeste, sans identifiants inventés :

```text
cas, autorisation, compte TEST, version API, base QA, client applicatif QA,
commande, devis accepté, obligation, montant/devise, empreinte du snapshot,
tentative, clé d'idempotence, Session cs_test_, PaymentIntent, Charge,
identifiant canonique du Dispute, reason/status/montant/devise,
événements reçus, dates fournisseur et dates SELBY, compteurs et empreintes.
```

La commande fictive reprendra le parcours existant : deux cartes Standard + Classic, grading 20 €, retour fictif France 5 €, taxe synthétique 0 €, confirmation de commande puis consentement et acceptation du devis distincts. Aucun catalogue supplémentaire n'est nécessaire si les configurations fictives QA existantes sont conformes.

Exclusions absolues : commandes de développement `c54cbac8-5098-423c-946f-02d7ec8d3915` et `d4dd84bf-5112-4301-a66c-cb51e2fdc4fd`, ainsi que toutes les commandes QA historiques hors du nouveau manifeste.

## 4. Prévol obligatoire avant paiement, après accord

1. Vérifier la séparation des processus et des bases. Enregistrer les empreintes en lecture seule des tables de développement et des lignes QA préexistantes, des sources applicatives/frontend et de `.env` ; révision `0015`, colonnes, contraintes, index et triggers.
2. Vérifier la clé TEST, le compte attendu et les gardes LIVE. Ne jamais interroger avec une clé LIVE. Conserver la version applicative `2025-02-24.acacia` ; enregistrer la version réelle des événements sans changer le compte pour l'aligner.
3. Après création applicative du nouveau client et de la commande autorisés, vérifier le devis accepté et son obligation : montant exactement 2 500 centimes EUR, conditions fictives, snapshot empreinté, aucun paiement ni restriction antérieurs.
4. Démarrer un listener QA dédié **avant** le paiement. Préserver signatures et corps bruts et vérifier son compte avec la même clé TEST. Ne pas utiliser `stripe trigger` pour remplacer un litige rattaché à un vrai paiement SELBY.
5. Créer au plus une Session par la route SELBY, puis vérifier sa lecture canonique : `cs_test_`, `livemode=false`, `mode=payment`, `amount_total=2500`, devise `eur`, statut ouvert/impayé et métadonnées exactes client/commande/devis/obligation/tentative. Vérifier l'absence d'autre Session payable pour cette obligation.
6. Confirmer que **l'autorisation conjointe paiement + litige automatique** est toujours applicable avant la saisie et l'unique soumission de la carte. Ne pas basculer vers une carte normale pour obtenir un succès si ce scénario échoue.

### Outillage QA à adapter avant une future exécution

Les contrôleurs précédents ne doivent pas être lancés tels quels : leurs listes de cas, gardes de mutation et abonnements couvrent les anciennes phases. Une adaptation du seul outillage QA devra :

- Autoriser la seule nouvelle création de Session, puis interdire toute autre mutation Stripe serveur.
- Ajouter la lecture canonique `GET /v1/disputes/{id}` pour le seul objet découvert par un événement rattaché à la Charge autorisée ; ne pas exiger un préfixe historique d'identifiant.
- Résoudre les événements de litige par `Dispute.charge` puis Charge → PI → métadonnées et obligation. Les métadonnées d'un Dispute peuvent être vides : un filtrage uniquement par `metadata.submission_id` risquerait d'ignorer le litige légitime.
- Conserver la vérification de signature de l'application et ses contrôles de rattachement. Ne pas réécrire un corps webhook pour l'adapter à une version.

Aucune adaptation ni aucun script exécutable B-DISPUTE n'est créé dans cette préparation.

## 5. Événements attendus et états SELBY

Le paiement devrait produire `payment_intent.succeeded` et `checkout.session.completed`. L'ouverture du litige devrait produire `charge.dispute.created` ; `charge.dispute.funds_withdrawn` peut accompagner le retrait de fonds TEST. Ne pas imposer un ordre de livraison ni un nombre exact d'événements. `updated`, `closed` et `funds_reinstated` correspondent à des évolutions, pas à des conditions de réussite de la simple ouverture. [Types d'événements Stripe](https://docs.stripe.com/api/events/types?api-version=2025-02-24.acacia).

Abonnement QA proposé, à réaliser seulement après accord :

```text
checkout.session.completed
payment_intent.succeeded
payment_intent.processing
payment_intent.requires_action
payment_intent.payment_failed
charge.dispute.created
charge.dispute.updated
charge.dispute.closed
charge.dispute.funds_withdrawn
charge.dispute.funds_reinstated
```

La souscription aux évolutions du litige permet de les observer si elles surviennent ; elle n'autorise pas à les déclencher. Les autres événements financiers éventuellement reçus doivent être archivés et classés comme écarts avant toute poursuite.

### Vérifications canoniques et rattachements

- Session, PI, Charge et Dispute : mode TEST confirmé ; compte relu ; chaque identifiant exact du manifeste doit correspondre à l'objet canonique.
- Session `complete/paid`, PI `succeeded`, montant reçu/capturé 2 500, devise `eur`, Charge rattachée au même PI et métadonnées concordantes.
- Dispute canonique : même Charge, même PI lorsque le champ est renseigné, `livemode=false`, devise `eur`, montant attendu 2 500, raison attendue `fraudulent`. Si le PI du Dispute est nul, vérifier le lien par la Charge, sans inventer un identifiant.
- Statut d'ouverture attendu `needs_response` ; un autre statut doit être consigné et analysé. Une inquiry n'est pas automatiquement requalifiée comme le litige ciblé. Les champs et statuts sont ceux de l'[objet Dispute Stripe](https://docs.stripe.com/api/disputes/object?api-version=2025-02-24.acacia).
- `Charge.disputed` et les preuves de litige doivent concorder ; liste des remboursements toujours vide et montant remboursé nul. Les éventuels mouvements/frais du Dispute sont relevés séparément de l'obligation.

### Deux ordres financiers acceptables selon le code actuel

Le caractère asynchrone chez Stripe **ne garantit pas** que SELBY enregistre un paiement avant de voir le litige. Le handler relit la Charge canonique ; un événement positif peut donc déjà constater `disputed=true`.

| Ordre réellement observé | Paiement et échéance SELBY | État final exigé après traitement des événements pertinents |
|---|---|---|
| Paiement vérifié avant toute restriction | 1 paiement de 2 500 et 1 échéance à +30 jours, conservés à l'identique | `restricted`, `charging_enabled=false`, label `dispute_review` ; aucun nouveau crédit |
| Litige ou Charge déjà disputée avant la première confirmation | 0 paiement confirmé, 0 échéance ; montant contractuel accepté reste 2 500 | `restricted`, `charging_enabled=false`, label `dispute_review` ; les succès tardifs ne créent pas rétroactivement un paiement ni une échéance |

Ces deux branches découlent de `handle_event`, `restricted`, `payment_state` et `financial_restrictions` dans `app/stripe_checkout.py`. Une transition d'un paiement déjà confirmé vers zéro ne serait pas acceptable. Un paiement/une échéance créé tardivement après une restriction persistante serait également un écart.

V1 devra afficher « Examen requis », le message de restriction financière et « Litige — examen requis ». Le backend devra refuser une nouvelle Session et une nouvelle déclaration d'envoi en HTTP 409, avec propriétaire/CSRF valides. Aucun droit physique ni contrôle de réception/inspection ne sera ouvert par ce test ; aucun objet physique n'est à créer.

Le code actuel conserve `dispute_review` après les événements de clôture, y compris `won`. Cette persistance est une règle existante, pas une autorisation d'exécuter une clôture. Une politique de levée de restriction nécessiterait une décision métier distincte.

## 6. Déroulement proposé après autorisation

1. Effectuer le prévol, constituer la commande et le manifeste QA et préparer le listener, sans réutiliser un paiement existant.
2. Après accord conjoint pour le paiement et son litige automatique, créer l'unique Session, vérifier ses objets puis soumettre une seule fois la carte retenue dans Checkout.
3. Relever sans délai le résultat fournisseur et les états SELBY, les objets Charge/PI et les dates. Ne pas essayer d'imposer la branche « confirmation avant litige » en retardant ou fabriquant des événements.
4. Attendre les événements et lire le Dispute canonique. Fenêtre d'observation proposée : au plus **10 minutes**, avec lectures espacées d'au moins 15 secondes. Il s'agit d'une limite opératoire proposée, pas d'un délai garanti par Stripe.
5. Si aucun litige canonique correspondant n'est observé dans cette fenêtre, arrêter le scénario comme non concluant. Ne pas répéter le paiement, changer de carte, forcer un litige ou ajuster Radar/3DS.
6. Après restriction effectivement traitée, vérifier objets, comptes, montants, branche 0/0 ou 1/1, snapshots, refus API et V1 au focus et après actualisation. Un HTTP 200 webhook seul ne constitue pas une réussite.
7. Rejouer une fois les événements signés de cette seule obligation si leur signature reste valide ; vérifier stabilité des identifiants, lignes de preuve, compteurs, dates et restrictions. Ne pas fabriquer de signature. Si trop ancienne, arrêter ce sous-test ; une nouvelle livraison fournisseur devra être cadrée séparément.
8. Enregistrer les empreintes après exécution, arrêter les seuls services QA et conserver le litige en l'état, sans réponse, clôture, remboursement ou nettoyage.

## 7. Critères d'arrêt

Arrêt avant toute mutation si mauvais compte/mode/base, clé non TEST, montant différent, cible hors manifeste, données QA non séparées, listener non vérifié ou preuve d'un objet antérieur réutilisé.

Arrêt pendant l'exécution si :

- Plus d'une Session payable, plus d'un paiement, nouvelle tentative ambiguë ou plus d'un litige pour la seule Charge attendue.
- Mauvais lien Dispute–Charge–PI–Session–commande, montant/devise inattendu, remboursement inattendu, statut/type de litige hors scénario.
- Refus, challenge/traitement non prévu ou protection empêchant le mécanisme attendu ; aucun contournement de sécurité ni changement de configuration.
- Signature rejetée, webhook non rapproché, événement pertinent non traité, absence de restriction après traitement effectif, refus API manquant ou confirmation tardive après restriction.
- Modification d'un paiement historique, d'un snapshot ou d'une échéance existante ; doublon après rejeu ; modification d'une commande protégée, d'un schéma ou de sources applicatives.
- B-P2 reproduit : `Session complete/unpaid + PI requires_action`. Archiver les objets et arrêter sans récupération non validée.

« Arrêter » signifie cesser toute nouvelle action financière ou de gestion du litige, conserver les preuves et rendre compte. Un litige déjà déclenché automatiquement ne sera ni annulé ni clos pour nettoyer le test.

## 8. Intégrité et livrables à exiger

Avant/après : empreintes de toutes les tables de développement, lignes QA préexistantes, schéma et sources. Autoriser en base de test uniquement les nouveaux objets du manifeste et les transitions de statut de sa tentative prévues par le handler ; aucune purge ni migration.

Conserver : manifeste exact et autorisation, objets canoniques horodatés et sans secrets client, versions API/événements, corps bruts et signatures privés, résultats HTTP, preuves SQL, compteurs et empreintes historiques, captures V1 FR/EN pertinentes et résultats de rejeu.

Le rapport final devra distinguer ce qui a réellement été observé de ce qui est seulement attendu, la branche de confirmation rencontrée, les montants disputés et les frais TEST éventuels, l'absence de remboursement, les limites de livraison/versionnement, les contrôles d'intégrité et l'arrêt des services.

## 9. Autorisations à obtenir

Les accords sont distincts ; aucun n'est acquis pour cette nouvelle phase :

1. **UX :** autoriser, si souhaité, le correctif limité décrit dans [le diagnostic V1](SELBY_V1_PERSISTENT_ALERT_DIAGNOSTIC.md). Cet accord n'autorise aucune opération Stripe.
2. **B-DISPUTE :** autoriser la préparation QA puis **une Session et une soumission de paiement TEST de 25 € avec `4061219946393810`, en acceptant explicitement qu'elle déclenche automatiquement un litige TEST sur cette seule Charge**, ainsi que les lectures, webhooks, contrôles et rejeux définis ici. L'accord doit exclure réponse/clôture du litige, remboursement, seconde tentative et changement de configuration. Cet accord peut être donné indépendamment du correctif UX ; la correction frontend n'est pas un prérequis imposé au scénario.

Une réponse au litige ou une simulation de gain/perte demanderait ensuite un accord séparé portant sur l'identifiant canonique réel du Dispute. Aucun identifiant de litige n'existe encore pour ce scénario.

**Arrêt documentaire. La demande actuelle n'autorise aucune de ces exécutions. B-P2 reste ouvert.**
