# SELBY — Protocole Stripe TEST, lot B

Statut : **audit et proposition uniquement — exécution soumise à validation**.
Audit du 5 novembre 2026. Aucun nouveau client, devis, Checkout, paiement, remboursement ou litige créé.
Aucun test du lot B exécuté à ce stade. Aucun fichier applicatif, réglage Stripe, `.env` ou schéma modifié.

## 1. Capacités vérifiées

| Élément | Constat |
|---|---|
| Backend | `development`, Stripe activé en `test`, option fictive activée, clé de type TEST, secret de signature renseigné |
| Identité Stripe | Uniquement `GET /v1/account` exécuté avec la clé TEST ; identité conforme à la configuration |
| Version API applicative | `2025-02-24.acacia`, à conserver pendant le lot |
| Stripe CLI | Version locale `1.33.0` ; aides de `listen`, `checkout sessions expire`, `events resend` disponibles |
| Connexion CLI | Le compte effectivement sélectionné par la CLI n'a pas été interrogé ; il devra être rapproché du compte du backend avant écoute |
| Connecteur Stripe | Aucun outil Stripe connecté disponible dans cette session ; CLI et API serveur disponibles |
| Navigateur | Chrome installé ; suite V1 contrôlée par CDP existante, actuellement reliée à une API simulée |
| PostgreSQL développement | `spectra`, `0015` : 2 obligations, 2 paiements, 2 tentatives, 4 preuves et 2 échéances |
| PostgreSQL isolé | `spectra_test`, `0015` : fixtures du lot A présentes ; aucune purge envisagée |

Les commandes CLI exécutées pendant l'audit se limitent à la version et aux aides. Aucun listener
n'a été démarré ou reconfiguré. Aucun secret n'est enregistré dans ce protocole.

### Comportements existants

- Confirmation uniquement après Session payée, PaymentIntent réussi, montant reçu exact, Charge payée/capturée,
  rattachement complet, compte et environnement vérifiés. Signature contrôlée sur le corps HTTP brut.
- Reprise d'une Session ouverte : réutilisation de la tentative et de sa clé d'idempotence.
- Expiration : possibilité de nouvelle tentative après constat d'expiration, sans rendre l'ancienne payable.
- Cas asynchrone terminé mais impayé : le backend peut annuler le PaymentIntent échoué avant de proposer
  une nouvelle Session. C'est une mutation Stripe à inclure explicitement dans l'autorisation d'exécution.
- Remboursements/litiges : preuves durables, statut `restricted`, création d'un autre Checkout bloquée.
- Le paiement historique et son échéance ne sont ni réécrits ni supprimés après restriction.
- Pas d'endpoint SELBY pour déclencher un remboursement ou un litige ; ces actions passent par Stripe.
- Le retour navigateur ne confirme rien. V1 relit le backend et interroge toutes les 5 secondes uniquement
  les états `creating`, `pending` et `action_required`.

## 2. Points d'attention avant exécution

### B-P1 — Déclaration d'envoi : écart potentiel entre UI et API

`app/commercial_api.py:62` exige une acceptation et une ligne `VerifiedPayment`, mais ne contrôle pas
explicitement `restricted`. V1 masque la déclaration si le statut courant est `restricted`.
La présence d'un paiement historique peut donc ne pas suffire à empêcher un POST direct après restriction.
De plus, une page restée ouverte en `verified` ne se rafraîchit pas automatiquement après un remboursement.

**Proposition :** premier test HTTP isolé après restriction synthétique. Si une nouvelle déclaration est
acceptée, consigner l'échec et proposer séparément le contrôle serveur minimal. Ne pas modifier la règle
ou le code sans accord. Ne pas considérer le masquage du bouton comme une protection serveur.

### B-P2 — Politique restrictive persistante

Tous les événements de la famille remboursement/litige traitée posent une restriction durable, y compris
`refund.failed` et `charge.dispute.closed`. Un remboursement échoué ou un litige gagné ne réactive donc
pas automatiquement la commande. Ce comportement doit être constaté, sans ajouter de levée automatique.

### B-P3 — Reprise et messages

- L'abandon du navigateur n'est pas une annulation de PaymentIntent : `cancelled` ne doit pas être attendu systématiquement.
- Le cas `Session complete/unpaid + PaymentIntent requires_action` renvoie actuellement sans URL Checkout :
  sa reprise doit être testée en simulation, sans promettre qu'un nouveau clic suffira.
- L'expiration d'une Session portant déjà un PaymentIntent peut produire une classification différente
  de celle d'une Session vierge. Tester d'abord l'expiration sans saisie de carte, puis cette variante en simulation.
- Le libellé FR de `cancelled` contient encore `Tentative annul?e` : correction de présentation à soumettre,
  sans changement du statut métier.

## 3. Séparation des environnements

### Simulations

- Réutiliser le principe du runner autonome du lot A, jamais les fixtures ordinaires qui appliquent Alembic.
- Base `spectra_test` existante, transactions/savepoints et rollback, identifiants uniques `B-SIM-*`.
- Aucun réseau Stripe : réponses Session/PaymentIntent/Charge/Event simulées, vraie route HTTP et HMAC synthétique.
- Ne pas modifier les fixtures conservées du lot A ; aucune suppression ni désactivation de trigger.
- Navigateur V1 avec API simulée et profil Chrome indépendant.

### Objets réels créés dans Stripe Sandbox — après autorisation

- Backend QA distinct, par exemple `127.0.0.1:18010`, base `spectra_test`, environnement development.
- Frontend QA distinct, par exemple `127.0.0.1:13010`, pointant exclusivement vers ce backend.
- Surcharge des variables au niveau des processus, sans modifier `.env` ni le serveur habituel.
- `AUTH_ORIGIN` correspondant au frontend QA ; profil navigateur séparé, les cookies n'étant pas isolés par port.
- Client QA et commandes dédiés, créés par le parcours existant. Aucune copie des clients ou commandes de développement.
- Publication des deux configurations fictives versionnées dans la seule base de test si aucun catalogue n'y est actif :
  opération de données à inclure dans la validation, sans migration ni modification de schéma.
- Manifeste du lot : cas, client QA, commande, devis, obligation, tentative, Session, PaymentIntent, Charge,
  événements et, ultérieurement seulement, Refund/Dispute.
- Liste d'exclusion absolue des deux commandes payées :
  `c54cbac8-5098-423c-946f-02d7ec8d3915` et `d4dd84bf-5112-4301-a66c-cb51e2fdc4fd`.
- Vérifier les clés TEST et le compte du backend et de la CLI. Ne pas changer de compte avec des tentatives actives.
  Si un autre Sandbox est choisi, ses identifiants restent propres aux processus QA.

Un Sandbox dédié offre une meilleure séparation des réglages. Le mode TEST historique peut partager
certains réglages avec LIVE : aucun changement Radar, moyens de paiement ou configuration de compte
n'est prévu. [Comparaison officielle des environnements Stripe](https://docs.stripe.com/testing-use-cases#testing-environments).

## 4. Ordre d'exécution proposé

### Étape B0 — Prévol et preuves

1. Enregistrer en lecture seule les empreintes des deux commandes protégées, de leurs snapshots, acceptations,
   obligations, paiements, tentatives, événements et échéances ; contrôler les contraintes et la révision `0015`.
2. Vérifier la séparation des processus, des bases, du profil navigateur et des comptes Stripe.
3. Après accord, préparer uniquement les données QA nécessaires. Attribuer une commande par scénario.
4. Valider le manifeste avant chaque mutation : commande du lot, `cs_test_`, compte attendu, `livemode=false`,
   2 500 centimes EUR, métadonnées conformes. Ne pas exécuter une action sur un identifiant inconnu.
5. Ne pas lancer `stripe trigger` pour représenter un paiement SELBY : ses objets non rattachés ne constituent pas un E2E.

### Étape B1-S — Simulations automatisées sans opération Stripe

| Cas | Injection simulée | Assertions obligatoires |
|---|---|---|
| Refus puis reprise | `requires_payment_method`, puis nouvelle tentative de paiement sur la Session ouverte | Aucun paiement/échéance avant règlement ; Session réutilisée ; montant accepté inchangé |
| 3DS | `requires_action`, abandon/échec, puis réussite | Aucun crédit pendant le challenge ; contrôle de la reprise et du libellé d'action |
| Abandon | Session toujours ouverte, retour `stripe_return=1&paid=true` | Aucun crédit ; pas de fausse annulation ; même tentative à la reprise |
| Expiration | Session expirée sans puis avec PaymentIntent | Aucun crédit ; ancienne Session non payable ; reprise sans tentative concurrente payable |
| Webhook retardé | Fournisseur réussi mais aucune livraison au backend | Lecture et retour navigateur sans crédit ; date finale fondée sur Stripe, pas sur la livraison |
| Remboursement partiel/total | Charge et événements synthétiques rattachés | Restriction, historique conservé, absence de second paiement/échéance |
| Litige et clôture | Événements synthétiques créés/mis à jour/clôturés | Restriction persistante, preuves cohérentes, pas de réactivation implicite |
| Événements tardifs/rejoués | Succès ancien après restriction, rejeux et ordres inversés | Aucun déblocage, aucun doublon, aucune modification des dates |
| Actions interdites | Checkout, déclaration d'envoi, éligibilité commerciale après restriction | Contrôler l'API et l'UI, notamment B-P1 ; conserver les protections de custody |

Ne pas brancher ni débloquer le fournisseur d'inspection. Une restriction commerciale ne remplace pas
les contrôles physiques de réception, de rapprochement ou de custody.

### Étape B1-R — Phase 1 avec vrais objets Stripe Sandbox

Base commune : 2 cartes Standard + Classic, grading 2 000 + retour fictif France 500, taxe 0, total 2 500 EUR-centimes.
La confirmation de commande et l'acceptation restent deux opérations distinctes via V1.

| Commande dédiée | Procédure après autorisation | Attendu |
|---|---|---|
| `B-DECLINE` | Carte de refus de la documentation Stripe ; observer le refus, revenir puis reprendre avec une carte TEST normale | `failed` si l'événement est rattaché et traité ; toujours 0 paiement/échéance avant réussite ; au plus 1 après reprise |
| `B-3DS` | Carte TEST 3DS obligatoire `4000000000003220` ; interrompre le challenge, vérifier l'absence de crédit, reprendre puis terminer | Aucun crédit avant authentification et règlement ; `action_required` si cet état est remonté ; 1 confirmation après réussite |
| `B-ABANDON` | Ouvrir Checkout, fermer/revenir sans payer, rouvrir | 0 paiement, 0 échéance ; réutilisation de la Session ouverte |
| `B-EXPIRE` | Session sans carte, laissée à expiration ou expirée explicitement après contrôle de son ID | 0 paiement/échéance ; possibilité de remplacement ; ancienne Session non payable |
| `B-DELAY` | Paiement TEST normal avec rétention temporaire de toutes les livraisons utiles pour cette seule tentative | 0 confirmation avant livraison ; 1 après ; horodatage du règlement Stripe conservé |

Les cartes 3DS doivent être utilisées dans Checkout, pas dans un paiement créé directement au Dashboard.
Pour les paiements normaux de ce protocole, utiliser la Visa TEST `4242424242424242`.
[Cartes de test et 3DS officielles](https://docs.stripe.com/testing#test-3d-secure-authentication).

Budget proposé pour B1-R : **5 commandes, cible de 6 Sessions dont le remplacement d'expiration,
et au maximum 3 paiements Sandbox réussis de 25 EUR**. Aucun remboursement ni litige.
Toute création supplémentaire non prévue demande un nouvel accord.

#### Expiration : opération à autoriser, même sans débit

Le backend ne configure pas `expires_at` : Stripe utilise normalement 24 heures. Deux choix : attente naturelle,
ou expiration ciblée d'une Session dédiée ouverte via la commande CLI vérifiée `checkout sessions expire`.
Aucun changement de durée dans le code n'est proposé. Selon l'état déjà enregistré, SELBY peut constater
l'expiration au premier clic et créer la nouvelle Session au suivant.
[Durée Stripe](https://docs.stripe.com/api/checkout/sessions/create) · [Expiration ciblée](https://docs.stripe.com/api/checkout/sessions/expire).

#### Webhook retardé : ne pas affaiblir la signature

1. Utiliser un proxy local QA entre un listener dédié et le backend QA, avec manifeste d'identifiants autorisés.
   Vérifier qu'aucun autre listener ne livre simultanément la même tentative au backend QA.
2. Mettre en rétention **tous les événements traitables de cette tentative**, pas seulement les deux succès :
   le handler relit Stripe et peut constater un règlement à partir d'un ancien événement d'un autre type.
3. Conserver corps brut et signature inchangés, dans un stockage local privé ; ne jamais journaliser le secret.
   Un HTTP 200 du proxy ne vaut pas acceptation par SELBY.
4. Payer, revenir à V1, tester le paramètre `paid=true`, actualiser : aucune confirmation ni échéance ne doit exister.
5. Relâcher après environ 60 secondes et avant 120 secondes, à l'intérieur de la tolérance HMAC de 300 secondes.
   Comparer l'heure Stripe du succès à `verified_at` ; le retard affecte `recorded_at`, pas le début des 30 jours.
6. Si la fenêtre est dépassée, arrêter ce scénario : ne pas fabriquer une nouvelle signature de fournisseur.
   Une nouvelle livraison Stripe requiert un mécanisme de redelivery approprié.

`events resend --webhook-endpoint=...` vise un endpoint Stripe enregistré, pas le listener local éphémère.
Ses secrets sont distincts. Un test de retry long ou un nouvel endpoint HTTPS nécessite un cadrage séparé.
Conserver les événements snapshot attendus par l'application, sans passage aux thin events ni à une autre
version API. [Livraison et rejeux Stripe](https://docs.stripe.com/webhooks#manual-retries).

### Étape B2 — Phase 2, uniquement après accord explicite distinct

| Commande dédiée | Préparation autorisable | Action bloquée jusqu'à autorisation précise | Attendu |
|---|---|---|---|
| `B-REFUND-PARTIAL` | Nouveau paiement TEST 25 EUR, vérifié dans SELBY | Remboursement Stripe de **500 centimes** sur son seul paiement | `restricted`, `partially_refunded`, montant remboursé cumulé 500 |
| `B-REFUND-FULL` | Autre paiement TEST 25 EUR, vérifié dans SELBY | Remboursement Stripe de **2 500 centimes** | `restricted`, `refunded`, pas de deuxième crédit |
| `B-DISPUTE` | Commande, devis et Session dédiés | Paiement avec une carte de test déclenchant automatiquement un litige, ou mécanisme Dashboard disponible et préalablement vérifié | `restricted`, `dispute_review`, pas de levée automatique à la clôture |

**Attention au litige automatique :** l'autorisation de litige doit précéder le paiement avec cette carte,
puisque le litige peut être créé à la suite du paiement lui-même. Une autorisation de payer seule ne suffit pas.
Choisir le scénario asynchrone documenté uniquement après accord. Si le mécanisme Dashboard n'est pas disponible,
ne pas inventer un endpoint de création de litige. [Scénarios de litige Stripe](https://docs.stripe.com/testing#disputes).

Les deux commandes remboursées restent distinctes pour ne pas cumuler les scénarios. Budget de préparation :
2 paiements TEST normaux de 25 EUR, puis 1 paiement de 25 EUR pour le scénario de litige s'il est autorisé.
Autoriser séparément les deux remboursements (montant, commande et PaymentIntent exacts) et le litige.

Contrôles après chaque événement :

- Paiement historique, obligation et snapshot restent à 2 500 centimes ; leur historique n'est pas un solde net.
- Une confirmation et une échéance préexistantes restent uniques et inchangées.
- Si un litige arrive avant la première vérification, le comportement restrictif actuel peut laisser 0 confirmation
  et 0 échéance : consigner cet ordre réel, ne jamais fabriquer rétroactivement une confirmation.
- Les montants remboursés proviennent des objets canoniques Stripe. Ne pas additionner les montants cumulés
  répétés dans plusieurs preuves webhook.
- Rejouer les événements du seul lot : aucune nouvelle confirmation ni échéance, aucun déblocage.
- Contrôler `charging_enabled=false`, le refus du Checkout, les libellés V1 après actualisation, l'éligibilité
  commerciale et le test HTTP de déclaration d'envoi. Arrêter sur un écart de protection.
- Après succès tardif ou clôture favorable d'un litige, la restriction persistante est le comportement actuel.
  Toute politique de levée nécessite une proposition et un accord distincts.

## 5. Preuves et critères d'arrêt

Pour chaque scénario, consigner : IDs du manifeste, source simulée ou Sandbox réelle, état Stripe,
statut HTTP, état SELBY, compteurs de paiements/échéances, montants, empreintes du snapshot,
dates Stripe/SELBY en UTC et capture V1 FR/EN. Aucun secret, cookie, mot de passe ou payload privé complet
dans le rapport partageable.

Réutiliser les requêtes de `STRIPE_TEST_MANUAL.md`, filtrées par les seuls IDs B, puis compléter avec
les preuves de restriction et les comparaisons avant/après. Vérifier séparément les deux commandes protégées.

Arrêt immédiat : mauvais compte/mode, identifiant hors manifeste, modification de schéma, paiement prématuré,
deux confirmations/échéances, montant différent, snapshot modifié, reprise donnant deux Sessions payables,
action autorisée malgré une restriction attendue ou modification d'une commande protégée.
Ne pas lancer de remboursement de nettoyage en cas d'erreur : demander une autorisation avec les IDs concernés.

## 6. Décisions demandées

1. Valider ce protocole et la première étape de simulations uniquement, sans objet Stripe créé.
2. Après leurs résultats et les éventuelles propositions de correction, autoriser explicitement B1-R
   et son budget : jusqu'à 3 paiements Sandbox de 25 EUR, sans remboursement ni litige.
3. Après B1-R, autoriser la préparation des commandes de remboursement, puis chaque remboursement ciblé.
4. Autoriser le scénario de litige avant tout paiement susceptible de le déclencher automatiquement.

La validation du protocole ne vaut ni approbation d'une modification métier, ni autorisation implicite
de remboursement, de litige ou d'opération LIVE.
