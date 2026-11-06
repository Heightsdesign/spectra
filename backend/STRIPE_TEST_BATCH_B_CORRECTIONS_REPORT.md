# SELBY — Lot B : corrections ciblées et validation locale

Date : 6 novembre 2026. Arrêt après les validations locales ; aucun scénario Stripe Sandbox lancé.

## Résultats

| Validation | Résultat | Preuve |
|---|---|---|
| Lot B original, 33 cas | **32 réussites, 1 échec B-P2** | `validation_artifacts/stripe_batch_b/20261106T093007Z_4a1a7f70/results.json` |
| Lot A original, 53 cas | **53 réussites** | `validation_artifacts/stripe_batch_a/20261106T092305Z_8e5714a5/results.json` |
| Rejeu historique après restriction, six variantes | **6 réussites** | `validation_artifacts/stripe_batch_b/20261106T092826Z_84536ddb/results.json` |
| Concurrence restriction / déclaration, deux ordres | **2 réussites** | `validation_artifacts/stripe_batch_a/20261106T093004Z_6e556c16/results.json` |
| Tests frontend | **101 réussites** | `npm.cmd test` |
| Typage / ESLint | **réussite / réussite** | `npm.cmd run typecheck`, `npm.cmd run lint` |
| Navigateur Next + Chrome, API en mémoire | **18 scénarios réussis** | `../frontend/.visual-review/order-workspace-v1/validation.json` |

Les six tests historiques supplémentaires sont exclus du lancement B standard pour conserver ses 33 cas, et exécutés avec `--historical-only`. Les deux tests de concurrence sont lancés séparément avec le lanceur A et `--shipment-corrections`. Aucun échec n'est masqué par un xfail.

## Anomalies corrigées

### B-P1 — autorisation de déclaration

`app/commercial_api.py`, `declare_shipment` vérifie désormais `restricted(db, accepted.quote_id)` avant une nouvelle insertion et retourne HTTP 409 `payment_financial_restriction`. Le contrôle s'exécute sous le verrou de la commande déjà acquis par `owned()`, partagé avec le traitement des webhooks. Il n'est pas conditionné à l'activation de Stripe.

Le contrôle suit la recherche de la déclaration historique : un rejeu identique reste idempotent, un contenu différent conserve HTTP 409 `idempotency_conflict`. Aucun paiement, échéance, snapshot ou déclaration historique n'est modifié.

Les six variantes passent : remboursement partiel, remboursement total, litige ouvert, remboursement échoué, litige clos et blocage manuel. Les assertions vérifient aussi l'absence de nouvelle déclaration et d'audit de déclaration lors du refus. Six cas supplémentaires vérifient le rejeu après chacune de ces restrictions, les dates et identifiants des déclarations, le nombre d'audits et l'identité financière historique.

La concurrence utilise deux connexions PostgreSQL et les routes HTTP réelles, avec fournisseur simulé. Le premier traitement est suspendu après acquisition du verrou ; le second atteint sa tentative de verrouillage avant libération :

- Webhook premier : restriction enregistrée, déclaration refusée 409, aucune déclaration créée.
- Déclaration première : déclaration autorisée 201, puis restriction ; nouvelle clé refusée 409, rejeu historique autorisé sans doublon.

Les paiements, échéances et empreintes des snapshots restent identiques dans les deux ordres. Un premier essai du nouveau test avait un filtre de nom de table incorrect et échouait à synchroniser les requêtes ; le filtre a été corrigé, puis les deux cas ont été réexécutés avec succès. Il ne s'agissait pas d'un échec applicatif.

### B-P3 — textes FR / EN

`frontend/src/lib/commercial.ts` : `Tentative annul?e` devient `Tentative annulée`. Les libellés de création, attente, action requise, échec, annulation, expiration, paiement vérifié et restrictions ont été revus dans les deux langues. Un test vérifie leur présence, les libellés d'annulation FR/EN et l'absence de caractères corrompus ; la parité des clés reste couverte. Les snapshots persistés ne sont pas retouchés.

### Page de suivi

`OrderWorkspace` relit uniquement `/commercial-state` au retour au focus et fusionne ce résultat dans les données existantes. Après `payment_financial_restriction`, la déclaration relit également cet état ; le paiement traite aussi le code existant `payment_already_verified_or_restricted`.

Ces lectures ne réinitialisent ni les formulaires, ni la fenêtre ouverte, ni les indicateurs de saisies non enregistrées. Le test navigateur vérifie une restriction sur une page déjà payée, le maintien du suivi saisi au focus puis après 409 et l'absence de déclaration créée. Les autorisations restent contrôlées par le backend. Si la relecture échoue, les saisies restent présentes ; une action affichée sur un état périmé reste soumise au refus serveur.

## B-P2 — diagnostic uniquement, non-conformité conservée

Le cas synthétique `Session complete/unpaid` et `PaymentIntent requires_action` renvoie toujours `200 {status: action_required, url: null}`. Aucune URL ni action de récupération exploitable n'est fournie ; le message invite encore à reprendre Checkout. Le test reste rouge. Aucun nouveau code d'annulation, de remplacement de tentative ou de reprise n'a été ajouté et `stripe_checkout.py` n'a pas été modifié.

Vérification documentaire, documentation Stripe consultée le 6 novembre 2026 :

- Une Session `complete` peut encore avoir un paiement en cours ; `complete/unpaid` n'est donc pas en soi contradictoire. L'URL hébergée n'est disponible que pour une Session active. [Objet Checkout Session](https://docs.stripe.com/api/checkout/sessions/object).
- Ces descriptions ne démontrent pas que la combinaison précise avec `requires_action` soit atteignable avec les moyens de paiement et la version API de SELBY. Le simulateur impose librement ces états ; une reproduction fournisseur reste nécessaire.
- L'annulation directe d'un PaymentIntent lié à Checkout n'est actuellement documentée que pour `requires_capture`. Les autres cas renvoient vers l'expiration de la Session. [Annulation d'un PaymentIntent](https://docs.stripe.com/api/payment_intents/cancel).
- L'expiration n'est permise que pour une Session `open`, ce qui ne résout pas directement une Session déjà `complete`. [Expiration d'une Session](https://docs.stripe.com/api/checkout/sessions/expire).

Conséquence du diagnostic : la branche existante de reprise d'échec asynchrone (`requires_payment_method`) simule une annulation directe avant remplacement. Sa réussite locale ne démontre pas sa validité Stripe Checkout. Cette limite préexistante est documentée sans modification de politique. Les contrats devront être revérifiés avec la version API réellement utilisée avant toute validation de cette stratégie.

Stratégies à soumettre à validation supplémentaire :

1. Relire les objets canoniques, attendre une transition fournisseur et proposer une revue opérateur explicite si l'état persiste. Cette voie conserve une seule tentative payable, mais nécessite un message et une sortie UX approuvés.
2. Si Stripe confirme une action client supportée pour ce type précis de paiement Checkout, définir une récupération de la même tentative avec le SDK ou le parcours officiellement prévu. Ne pas extrapoler un contrat PaymentIntent autonome à Checkout, ni exposer un secret ou inventer une URL de reprise.
3. Envisager un remplacement uniquement après preuve fournisseur que l'ancienne tentative ne peut plus aboutir et après validation d'une stratégie de verrouillage et d'idempotence évitant deux paiements. L'annulation ou l'expiration forcée ne constitue pas une solution automatiquement autorisée.
4. Si la combinaison n'est pas reproductible et est confirmée incompatible par Stripe pour cette intégration, préciser le modèle du simulateur tout en conservant un traitement prudent des états inattendus. Ne pas supprimer le test rouge sur la seule base de cette hypothèse.

## Isolation, régressions et limites

Les rapports `isolation.json` des exécutions citées attestent : base de développement inchangée, schéma inchangé en révision 0015, zéro tentative HTTP Stripe réelle et aucune tentative SQL interdite ou migration. Le lot B et les six tests historiques utilisent des transactions annulées et conservent toute la base de test inchangée.

Les tests de concurrence du lot A et les nouveaux tests de concurrence utilisent des commits indépendants : leurs commandes synthétiques restent uniquement dans la base locale de test, comme le prévoit le banc existant. Elles sont identifiées dans `retained_synthetic_concurrency_fixtures`. Aucune purge n'est exécutée. Les deux commandes payées de développement restent intactes, couvertes par l'empreinte avant/après de la base de développement.

Stripe LIVE reste bloqué par les gardes de configuration testées au lot A et par le blocage du transport réel des bancs. Aucun réglage Stripe ni fichier `.env` n'a été modifié. Les événements de remboursement, litige et expiration sont exclusivement des objets synthétiques en mémoire. Aucun remboursement, litige, expiration forcée ou appel financier réel n'a été exécuté, même en TEST.

Aucune régression détectée dans les 53 cas A, les 32 cas B conformes, les huit cas backend supplémentaires et les tests frontend exécutés. La suite backend globale n'est pas revendiquée : ses fixtures standard lancent Alembic et certains bancs purgent des données ; les bancs isolés ont été utilisés pour respecter l'interdiction de migration et de purge. Les avertissements pytest/FastAPI et Node observés ne sont pas des échecs de validation.

Restent à vérifier en Stripe Sandbox, uniquement après accord distinct : atteignabilité de B-P2, authentification 3DS réelle et abandon du challenge, états et reprises réels des Sessions, cohérence de la branche d'annulation préexistante avec Checkout, délais et livraison réels des webhooks. Les simulations et le navigateur avec API en mémoire ne démontrent aucune de ces propriétés fournisseur.

**Arrêt local. Le lot B n'est pas déclaré entièrement conforme tant que B-P2 reste sans stratégie validée.**
