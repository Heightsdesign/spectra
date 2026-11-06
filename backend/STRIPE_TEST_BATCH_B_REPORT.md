# SELBY — Lot B : rapport des simulations isolées

## Résultat

Exécution complète : `20261105T222802Z_c481a294`, le 5 novembre 2026 UTC.
**33 tests : 25 réussis, 8 échecs, aucun ignoré.** Les huit échecs exposent trois anomalies ; la suite reste rouge et le lot n'est pas déclaré conforme.

Commande exécutée :

```powershell
.venv/Scripts/python.exe validation_tests/stripe_batch_b/run.py
```

Les échecs sont des assertions de protection réellement non satisfaites, sans `xfail` ni correction du code métier. L'exécution prioritaire précédente (`20261105T222416Z_737c0e3b`) reproduisait déjà les six variantes de B-P1.

## Résultats par famille

| Scénario simulé | Résultat et preuve principale |
|---|---|
| Déclaration d'envoi après restriction financière | **6 échecs** : HTTP 201 malgré `restricted` et refus du helper V1 ; une déclaration et un audit créés par variante, puis annulés par rollback. |
| Commande impayée / payée sans restriction | Refus de l'impayée ; création autorisée après paiement vérifié ; rejeu identique sans doublon, contenu divergent refusé. |
| Carte refusée et reprise | État `failed`, aucun paiement ni échéance ; Session ouverte réutilisée puis succès simulé unique. |
| 3D Secure, Session ouverte | `action_required`, aucun crédit ; reprise de la même URL puis succès simulé. |
| 3D Secure, Session terminée mais impayée | **B-P2 : échec** : réponse `action_required` sans URL ni action de récupération exploitable. Aucune confirmation prématurée. |
| Échec asynchrone, Session terminée | Ancien PaymentIntent annulé en mémoire avant remplacement ; reprise après perte simulée de la réponse d'annulation ; une seule confirmation finale. |
| Abandon et retour navigateur | Aucun crédit, aucune échéance ; les paramètres de retour navigateur ne prouvent rien ; reprise de la Session ouverte. |
| Expiration avec / sans PaymentIntent | États déduits des objets canoniques simulés ; remplacement possible sans crédit prématuré. Sans webhook, observation de l'expiration puis remplacement au clic suivant. |
| Webhook retardé, dans les deux ordres | Aucun crédit avant livraison ; paiement daté du succès fournisseur simulé, échéance à +30 jours ; rejeux sans changement des dates ni doublon. Décalage de 60 secondes simulé par horloge contrôlée. |
| Remboursement partiel puis total | Restrictions présentes et persistantes ; montant historique payé conservé à 2 500 EUR centimes ; remboursement cumulé non additionné deux fois. |
| Remboursement échoué / litige ouvert ou clos | Restriction maintenue, y compris litige gagné ou perdu ; aucune levée implicite. |
| Restriction reçue avant le succès | Les événements positifs tardifs ne créent ni confirmation financière ni échéance. |
| Idempotence et intégrité | Un paiement et une échéance par scénario payé ; identifiants, dates et empreinte du snapshot acceptés inchangés après rejeux et restrictions. |
| Restrictions et custody | Aucun droit physique ouvert par la restriction ; raison `original_shipping_financial_restriction` observée. |
| Messages V1 | Helpers TypeScript réels exécutés sur les états API ; **B-P3 : libellé français d'annulation corrompu**. |

## Anomalie prioritaire B-P1 — autorisation API insuffisante

Route concernée : `POST /api/submissions/{id}/shipment-declarations`, fonction `declare_shipment`, `app/commercial_api.py:63`.

Après un paiement vérifié, les six restrictions suivantes conservent la ligne historique `VerifiedPayment` : remboursement partiel, remboursement total, litige, remboursement échoué, litige clos et blocage manuel. L'API commerciale retourne `payment_status=restricted`, le helper V1 `canDeclareShipment` retourne `false`, et `POST /api/submissions/{id}/stripe-checkout` refuse avec HTTP 409.

Pourtant, une nouvelle déclaration d'envoi, soumise par le propriétaire avec session et CSRF valides, reçoit HTTP 201 et crée une déclaration ainsi qu'un audit `customer_shipment_declared`. L'API vérifie le paiement historique, sans vérifier la restriction financière actuelle.

Il s'agit d'un contournement de la restriction de déclaration, sans preuve de contournement de la réception physique ou de custody. Les six reproductions ont été intégralement annulées.

**Correction proposée, non appliquée :** dans la branche de création d'une nouvelle déclaration, sous le verrou existant de commande et avant insertion, vérifier `restricted(db, accepted.quote_id)` ; refuser avec HTTP 409 et une erreur telle que `payment_financial_restriction`. Conserver propriété, CSRF, délais, validation et idempotence.

Contrat proposé à valider : un rejeu strictement identique d'une déclaration historique reste une réponse idempotente sans nouvelle écriture ; un contenu divergent reste refusé. Tester ensuite les six restrictions et la concurrence webhook/déclaration. La course concurrente de ce nouveau contrôle ne peut pas être validée avant implémentation.

Le détail reproductible et les critères d'acceptation figurent dans [STRIPE_TEST_BATCH_B_SHIPMENT_FINDING.md](STRIPE_TEST_BATCH_B_SHIPMENT_FINDING.md).

## Autres anomalies et observations

**B-P2 — reprise sans issue dans un état simulé.** Pour une Session `complete/unpaid` dont le PaymentIntent est `requires_action`, le démarrage de Checkout retourne HTTP 200 avec `{"status":"action_required","url":null}`. Le message V1 invite à reprendre Checkout, mais le traitement de cette réponse ne fournit pas de redirection. Proposer une récupération explicite, après vérification de l'accessibilité et du comportement de cet état dans Sandbox. Ne pas annuler un PaymentIntent ni créer un nouveau paiement automatiquement sans stratégie validée. La possibilité réelle de cet état fournisseur reste non démontrée par ces simulations.

**B-P3 — message français.** `frontend/src/lib/commercial.ts:21` contient `Tentative annul?e` au lieu de `Tentative annulée`. Correction textuelle recommandée, non appliquée.

**Observation statique UX :** `order-workspace.tsx:74` ne déclenche son polling que pour `creating`, `pending` et `action_required`. Une page déjà en `verified` peut donc conserver son ancienne action après une restriction survenue ultérieurement, jusqu'à actualisation. Prévoir une relecture au retour au focus et après un refus financier. Ce comportement n'a pas été reproduit dans un navigateur dans cette exécution ; il renforce la nécessité du contrôle serveur B-P1.

## Isolation et périmètre technique

- Les vraies routes applicatives sont invoquées via FastAPI TestClient. Le transport Stripe est remplacé par des objets en mémoire ; les webhooks traversent la route signée avec un secret exclusivement synthétique.
- Chaque scénario utilise une transaction externe annulée dans `spectra_test`, avec les commits applicatifs confinés dans des savepoints. Aucun purgeur ni fixture de migration standard n'est invoqué.
- Comparaison avant/après de toutes les tables publiques et empreinte du schéma : **base de développement inchangée, base de test inchangée**. Révision déjà présente : `0015` dans les deux bases.
- Les deux commandes payées de développement restent inchangées. Leur base n'a servi qu'à des lectures en transaction configurée en lecture seule.
- **Zéro tentative HTTP Stripe réelle**, zéro tentative SQL interdite ou migration. Aucune commande Stripe CLI utilisée. Les annulations, remboursements, litiges et expirations décrits sont en mémoire uniquement.
- Empreintes des sources `app/*.py` et `frontend/src` TypeScript/TSX/CSS identiques avant/après. Aucun correctif métier ni frontend appliqué.
- Les gardes techniques bloquent la passerelle Stripe réelle, le transport HTTP utilisé par celle-ci, les commandes Alembic et les instructions SQL hors liste autorisée.

## Interface et limites Sandbox

Les fonctions réelles `canDeclareShipment`, `nextAction`, `isTracking` et les messages FR/EN sont exécutés avec Node sur les réponses API synthétiques. Trente états complets sont exportés dans `ui-cases.json`. Cela vérifie les décisions de navigation et libellés, mais ne constitue pas une validation du rendu navigateur, du focus, du clic ou du challenge bancaire.

Restent à vérifier après autorisation distincte : refus de carte réel et reprise Checkout, challenge 3DS réel et abandon de challenge, comportement réel des Sessions ouvertes/terminées/expirées, délais et livraison réelle des webhooks, parcours navigateur V1, puis remboursements partiels/totaux et litiges sur commandes exclusivement dédiées. La vérification de ces opérations Stripe Sandbox n'a pas été effectuée et ne doit pas être déduite des succès simulés.

La séparation TEST/LIVE n'est pas réauditée exhaustivement ici : la configuration du banc est synthétique TEST et tout accès Stripe réel est bloqué. Les vérifications dédiées du lot A restent une preuve distincte.

## Fichiers et preuves

Ajoutés pour ce lot :

- `validation_tests/stripe_batch_b/conftest.py` : isolation, empreintes, transport simulé, fixtures transactionnelles, exécution des helpers V1.
- `validation_tests/stripe_batch_b/test_batch_b.py` : 33 cas paramétrés et assertions de protection.
- `validation_tests/stripe_batch_b/run.py` : lanceur indépendant sans fixture de migration/purge.
- `STRIPE_TEST_BATCH_B_SHIPMENT_FINDING.md` et le présent rapport.

Preuves de l'exécution complète : `validation_artifacts/stripe_batch_b/20261105T222802Z_c481a294/` : `results.json`, `findings.json`, `isolation.json`, `ui-cases.json`. Les preuves contiennent des empreintes et identifiants synthétiques, aucun secret Stripe.

**Arrêt avant toute opération financière réelle. B-P1 doit faire l'objet d'une validation de correction avant modification du code métier.**
