# SELBY — Lot B / B-P2 — Investigation et recommandation

Date : 6 novembre 2026. **B-P2 reste ouvert. Aucun correctif métier implémenté.**

L'analyse du code et de la documentation est réalisée. La nouvelle reproduction fournisseur est **bloquée au prévol réseau**, et non déclarée réussie ou négative. Les observations B1-R ci-dessous proviennent des archives existantes, relues pendant cette intervention. Elles ne sont pas de nouveaux essais.

## 1. Analyse technique

### Parcours applicatif

- `app/config.py` : version configurée et valeur par défaut `2025-02-24.acacia`. Gardes TEST, environnement hors production, clé `sk_test_`. Aucun paramètre modifié.
- `app/stripe_checkout.py`, `StripeGateway.call` : REST via httpx, en-tête `Stripe-Version` explicite, délai réseau 15 secondes, pas de redirection. L'API du compte doit correspondre au compte configuré.
- `start_checkout` : obligation acceptée et snapshot commercial contrôlés ; refus si paiement déjà vérifié ou restriction ; réutilisation de la tentative active et de sa Session. Création en `mode=payment`, EUR, montant du devis, métadonnées de rattachement sur Session et PI. Aucun type de paiement n'est explicitement fixé dans la requête : les moyens effectivement proposés doivent être relevés sur la Session et dans la configuration Stripe, sans les déduire du seul test carte.
- Pour `complete/unpaid`, le PI est relu et contrôlé (TEST, identité, métadonnées, montant, devise). Avec `requires_action`, la tentative devient `action_required`. L'URL n'est conservée que pour une Session `open` et la réponse ne fournit une URL que pour le statut applicatif `pending`. B-P2 produit donc `200 {"status":"action_required","url":null}` par construction. Ce HTTP 200 indique le traitement de la requête, jamais un paiement réussi.
- `app/stripe_api.py` expose ce résultat ; GET payment status lit l'état local, sans interrogation Stripe. `handle_event` relit les objets Stripe canoniques, contrôle leur rattachement et archive une preuve par identifiant d'événement avec empreinte du contenu. La signature est vérifiée sur le corps brut, tolérance 300 secondes.
- `frontend/src/components/order-workspace.tsx`, `paid-order-panel.tsx` et `lib/commercial.ts` : actualisation périodique et invitation à reprendre Checkout. Une réponse sans URL déclenche un rafraîchissement, sans mécanisme supplémentaire d'authentification. Le libellé de reprise devient trompeur pour une Session terminée.

Le code ignore `next_action` pour la récupération. `requires_action` ne signifie pourtant pas systématiquement un challenge 3DS : le type d'action et le moyen de paiement sont indispensables au diagnostic.

### Confirmation et délais

`handle_event` exige Session `paid`, PI `succeeded`, montant reçu exact, Charge présente, payée et capturée, sans restriction financière. `checkout.session.completed` seul ne confirme donc pas la commande. Une absence de Charge capturée, y compris transitoire, laisse le paiement en attente ; ne pas assouplir ce contrôle dans B-P2.

`app/commercial.py`, `record_provider_confirmation` conserve une confirmation par obligation ; `verified_at` provient du succès fournisseur et `recorded_at` de l'enregistrement. L'échéance d'expédition est **succès fournisseur + 30 jours UTC**, jamais challenge, fin de Checkout, retour navigateur, début de revue ou livraison tardive du webhook. Sans paiement confirmé : aucune nouvelle confirmation ni échéance. Une échéance déjà enregistrée ne doit être ni recalculée ni prolongée.

Le rapprochement retrouve l'événement `payment_intent.succeeded` si nécessaire, avec limite locale de 20 pages de 100 événements. L'indisponibilité de cet horodatage entraîne HTTP 503. Une revue prolongée peut dépasser la disponibilité des événements ou cette limite de recherche : conserver les preuves de succès et prévoir un rapprochement opérateur, sans dater arbitrairement le paiement.

### Idempotence et point de vigilance existant

Identité durable de tentative avant l'appel réseau, clé `selby-test-<attempt_id>`, verrou de commande, index unique des tentatives actives, unicité de Session/PI, déduplication des événements et contrôle des conflits de confirmation constituent les protections existantes. Une création ambiguë sans Session après 23 heures exige déjà une revue, pour éviter la réutilisation d'une clé Stripe potentiellement purgée après 24 heures. Cette limite ne doit pas devenir un délai d'annulation de B-P2.

**Risque préexistant à examiner avant une nouvelle campagne :** dans `start_checkout`, un PI de Session `complete/unpaid` passant à `requires_payment_method` déclenche une tentative d'annulation directe ; un PI déjà `canceled` classe la tentative `cancelled`. Cela peut ensuite ouvrir la voie à une nouvelle Session. La documentation Checkout restreint cette annulation (voir §3). Ne pas utiliser la route POST de reprise comme une simple lecture lors de l'investigation d'un état susceptible d'évoluer vers ces branches. Aucune de ces branches n'a été exécutée ici et aucun changement n'y a été apporté.

## 2. Essais Sandbox et preuves

### Nouveau prévol du 6 novembre 2026

Preuve : `validation_artifacts/stripe_sandbox_b_p2/access-preflight.json`.

| Contrôle | Résultat |
|---|---|
| Clé disponible | Préfixe TEST vérifié en mémoire ; aucun secret affiché ou archivé |
| Compte configuré attendu | `acct_1UXDxRFq5FKSG47y` — identité actuelle non vérifiée auprès du fournisseur |
| Requête tentée | GET `https://api.stripe.com/v1/account`, version `2025-02-24.acacia` |
| Heure | `2026-11-06T15:30:15.227853+00:00` |
| Résultat | `URLError`, `WinError 10013` : accès au socket interdit par les permissions |
| HTTP / Request-Id Stripe | Aucun : aucun échange HTTP Stripe obtenu |
| Mutations Stripe / SQL | Zéro |
| Nouveaux événements / réponses backend B-P2 | Aucun |

La restriction réseau de cet environnement et l'interdiction d'escalade empêchent de poursuivre le prévol authentifié. Aucun secret n'a été transféré à un outil de recherche web ; la consultation documentaire publique ne constitue pas un accès à l'API Sandbox. Aucun paiement parallèle, faux webhook, modification de statut fournisseur ou objet financier autonome n'a été créé pour contourner ce blocage.

**La phase 2 demeure incomplète.** Il n'existe dans cette intervention ni nouveau résultat fournisseur B-P2 ni réponse HTTP backend observée pour cet état.

### Preuves réelles B1-R relues

Compte et version relevés dans les archives : même compte Sandbox, lectures `2025-02-24.acacia`. Les événements du listener portent `2026-10-28.endive` ; la version des événements est distincte de celle des lectures REST. La configuration actuelle du listener n'a pas été interrogée.

| Archive `validation_artifacts/stripe_sandbox_b1r/phase1/` | Session | PI / action | SELBY |
|---|---|---|---|
| `B-3DS-challenge-active.json` | `open/unpaid` | `requires_action`, `use_stripe_sdk`, reçu 0 | `pending` avant synchronisation |
| `B-3DS-challenge-interrupted.json` | `open/unpaid` | mêmes états | `action_required`, pas de paiement ni échéance |
| `B-3DS-final.json` | `complete/paid` | `succeeded`, reçu 2500 EUR centimes, `next_action=null` | `verified` |

Session : `cs_test_a1kuJ3LT0esdx2EInMrkDkhF7vffDC68OI0JJ2QHBXJCMwpfLdfDHMLw60` ; PI : `pi_3UYjqGFq5FKSG47y1dqC01J1`. Le rapport `STRIPE_SANDBOX_B1R_PHASE1_REPORT.md` archive deux événements réels `payment_intent.requires_action`, puis succès PI et Session terminée, acceptés en HTTP 200. Il distingue les réponses réseau capturées des corps de POST Checkout non récupérés : ne pas reconstruire ces derniers comme preuve.

Conclusion limitée : interruption puis reprise 3DS réussies sur **la même Session ouverte et le même PI**. Aucun relevé B1-R n'atteste `complete/unpaid + requires_action`. Des instantanés espacés n'excluent pas un état transitoire.

Le banc `validation_tests/stripe_batch_b/test_batch_b.py`, cas B-P2, impose cette combinaison à un transport simulé. Il prouve l'impasse applicative, pas l'atteignabilité Stripe. Il n'a pas été relancé ici et ne remplace pas la reproduction fournisseur.

## 3. Comportement documenté de Stripe

Sources officielles consultées le 6 novembre 2026. Les pages avec version sont celles de l'intégration ; les guides généraux et l'exception actuelle d'annulation ne constituent pas une preuve d'exécution sous Acacia.

1. [Objet Checkout Session, Acacia](https://docs.stripe.com/api/checkout/sessions/object?api-version=2025-02-24.acacia) : `complete` et paiement terminé sont deux notions distinctes ; un paiement peut encore être en cours. L'URL Checkout concerne la Session active. La référence interdit la confirmation directe du PI géré par Checkout. **`complete/unpaid` est compatible avec le contrat ; cela ne démontre pas la combinaison exacte avec `requires_action` pour SELBY.**
2. [Fulfillment Checkout](https://docs.stripe.com/checkout/fulfillment.md?ui=full-page) : certains moyens ont une notification différée ; traiter les événements asynchrones de succès/échec et rendre le traitement unique malgré appels concurrents. Le retour navigateur n'est pas une preuve de règlement.
3. [Confirmation PI, Acacia](https://docs.stripe.com/api/payment_intents/confirm?api-version=2025-02-24.acacia) : dans une intégration PaymentIntents, `requires_action` s'accompagne d'une action décrite par `next_action` ; les suites dépendent du mode de confirmation. **Ce contrat générique n'autorise pas à confirmer directement un PI Checkout.**
4. [Stripe.js handleNextAction](https://docs.stripe.com/js/payment_intents/handle_next_action) : outil officiel pour terminer une action dans le parcours de finalisation serveur prévu par Stripe, avec le client secret. Pas de garantie trouvée pour reprendre ainsi un PI de Checkout hébergé déjà terminé. Ne pas exporter le client secret ou greffer ce parcours par hypothèse.
5. [Expiration Checkout, Acacia](https://docs.stripe.com/api/checkout/sessions/expire?api-version=2025-02-24.acacia) : réservée aux Sessions `open`. Elle ne permet donc pas de débloquer une Session déjà `complete`.
6. [Annulation PI, documentation actuelle](https://docs.stripe.com/api/payment_intents/cancel) : l'annulation directe d'un PI Checkout est prévue uniquement pour `requires_capture` ; sinon la documentation renvoie à l'expiration de la Session. L'autorisation générique d'annuler un PI `requires_action` ne s'applique pas automatiquement à Checkout.
7. [Vouchers](https://docs.stripe.com/payments/vouchers) : plusieurs moyens Checkout exigent une action externe après émission d'instructions. Cela justifie de distinguer action de paiement externe et authentification carte ; ce guide ne prouve pas les trois états exacts de B-P2. [Virements bancaires](https://docs.stripe.com/payments/bank-transfers/accept-a-payment) : Stripe propose des parcours Checkout et PaymentIntents distincts ; les instructions et restrictions du moyen effectivement utilisé doivent être vérifiées avant toute proposition spécifique.

Les variantes détaillées des guides de récupération de paniers et de virements n'ont pas pu être récupérées par l'outil documentaire. Aucun contrat de reprise d'une Session `complete` n'en est déduit. Les mécanismes de récupération de Session expirée, de facture ou d'abonnement ne doivent pas être transposés au paiement ponctuel SELBY sans vérification explicite.

**Réponse à l'atteignabilité : non établie pour le parcours SELBY sous Acacia ; impossibilité non démontrée.** Aucun mécanisme universel officiellement confirmé pour récupérer cette combinaison Checkout précise n'a été identifié. Cela n'exclut pas une action officielle spécifique au moyen, fournie dans `next_action` ; il faut l'observer et vérifier son contrat. Ne jamais fabriquer une URL à partir d'un identifiant, réutiliser une ancienne URL terminée comme garantie de reprise, ou traiter `use_stripe_sdk` comme une URL.

## 4. Risques identifiés

- Boucle client sans issue, attente indéfinie et libellé trompeur ; un HTTP 200 peut être interprété à tort comme une réussite.
- Double paiement si remplacement de Session, nouvelle tentative ou confirmation directe ajoutés sans contrat fournisseur.
- États Session/PI lus successivement : une évolution entre les lectures peut produire un constat incohérent. Répéter les lectures horodatées, sans affirmer leur atomicité.
- Paiements différés et actions propres au moyen : ne pas confondre `requires_action` avec 3DS, ni `complete/unpaid` avec échec définitif.
- Version webhook différente de REST, événements dupliqués ou désordonnés, synchronisation locale tardive ; conserver les versions et objets canoniques.
- Risque de perdre la date réelle de succès lors d'une attente longue ; aucun décalage d'échéance permis.
- Une mise en restriction via le hold existant peut bloquer une confirmation automatique ultérieure : `restricted()` reste vrai et aucun parcours de levée n'est défini ici. **Ne pas réutiliser automatiquement ce hold pour B-P2.**
- La branche préexistante d'annulation lors d'un échec asynchrone doit être auditée ; aucun test B-P2 ne doit la déclencher incidemment.

## 5. Stratégie recommandée — soumise à validation

Préférer une **attente avec revue opérateur**, sans déclarer le paiement échoué ni confirmer la commande. Conserver la tentative active, le PI, le devis accepté et tout historique. Interdire dans cette voie annulation automatique, remplacement et deuxième tentative payable. Un dépassement de délai de revue doit déclencher une alerte, jamais une mutation financière ou une nouvelle échéance.

Proposition concrète à valider : distinguer dans la réponse de reprise l'absence de récupération disponible, présenter « Paiement en attente — vérification par SELBY nécessaire », proposer actualisation et contact SELBY, et supprimer l'invitation à reprendre un Checkout terminé. Le nom exact du statut/action API et les modalités de file opérateur restent à approuver ; aucune migration n'est proposée ou effectuée ici.

La revue conserverait un relevé horodaté : compte TEST, version REST et événement, Session/PI et métadonnées, montant/devise, statuts, type de `next_action`, événements et Request-Id, rapprochement commercial. Éviter secrets et liens sensibles dans les journaux généraux. Aucun opérateur ne doit marquer manuellement « payé » sans les preuves fournisseur requises.

Si une action officielle propre au moyen est observée et son usage après Checkout terminé confirmé par Stripe, proposer séparément son exposition autorisée au bon client, sur **le même PI**, sans confirmer celui-ci via une API interdite à Checkout. Validation de l'URL réellement fournie et de sa validité, absence de journalisation de secrets et échec sûr si action absente/expirée sont requis. Cette option n'est pas validée aujourd'hui.

En cas de succès ultérieur, garder le rapprochement et la confirmation idempotents existants, ainsi que l'horodatage fournisseur. Si une revue doit bloquer la confirmation même après paiement, cela constitue une règle métier supplémentaire à faire valider, pas un usage implicite du hold existant. Aucun message n'a été envoyé à Stripe ou à un tiers pendant cette intervention.

## 6. Essais nécessaires à la clôture

1. Depuis un environnement autorisant l'API, refaire le prévol TEST et vérifier réellement le compte attendu. Relever versions REST et webhooks, moyens activés et proposés, configuration de capture ; ne rien modifier pour rendre artificiellement B-P2 atteignable.
2. Préparer une obligation QA distincte en base Sandbox et une seule tentative payable. Protéger les commandes existantes, notamment B-DISPUTE. Avant chaque mutation, vérifier les identités et l'absence d'autre tentative payable ; ne pas appeler la reprise sur un état susceptible d'activer l'annulation préexistante.
3. Dans Checkout hébergé, exercer 3DS : abandon par navigation, Fail/annulation bancaire et reprise ; conserver lectures avant/pendant/après, mêmes Session/PI, événements authentiques et résultats HTTP backend effectivement capturés. Aucun PI autonome ni `stripe trigger` comme preuve B-P2.
4. Si des moyens à action externe sont déjà autorisés pour ce compte et ce devis, examiner leur parcours dans la même discipline. Ne pas activer un nouveau moyen ou changer les règles financières pour provoquer un état. Collecter `next_action.type` et contrat officiel associé. Si aucun chemin pris en charge ne produit B-P2, demander une clarification Stripe avec identifiants Sandbox et versions ; ne pas déclarer l'état impossible sur cette seule base.
5. Pour un B-P2 réellement observé : plusieurs relevés Session/PI horodatés, événements originaux, Request-Id et réponses backend ; aucun crédit ni échéance avant succès. Tester la stratégie approuvée : revue clairement affichée, aucun lien inventé, aucune annulation/remplacement, aucun second paiement.
6. Après validation métier, tests locaux déterministes de la réponse et de l'interface pour B-P2, `next_action` absent/inconnu et erreurs Stripe. Ces tests vérifient l'application et restent explicitement synthétiques. L'assertion actuelle « URL ou recovery_action obligatoire » doit refléter une revue opérateur seulement si cette nouvelle cible a été approuvée ; ne pas rendre le test vert en affaiblissant arbitrairement le critère.
7. Vérifier concurrence des reprises, événements doublés/désordonnés, succès pendant revue et webhook tardif : une confirmation, un audit de confirmation et une échéance, date fournisseur + 30 jours. Vérifier absence de perte d'historique, zéro changement des snapshots et des échéances existantes, aucun événement de remboursement ou action de litige déclenché.

Critère de clôture : preuve fournisseur du parcours applicable ou clarification officielle suffisante sur sa portée, stratégie explicitement approuvée, puis implémentation et vérifications distinctes. **Ce rapport ne clôture pas B-P2 ni le Lot B.**

## Périmètre de l'intervention

Ajouts limités à ce rapport et à la preuve de prévol réseau. Aucun code métier, test existant, fichier `.env`, schéma, règle financière, historique ou journal existant modifié. Aucun test de paiement nouveau exécuté ; aucun remboursement, réponse au litige, expiration ou annulation demandé. Arrêt après investigation et recommandation, conformément à la mission.
