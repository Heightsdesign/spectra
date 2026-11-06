# SELBY — Alerte V1 persistante : diagnostic et proposition

Date : 6 novembre 2026. **Diagnostic documentaire uniquement ; aucun fichier frontend modifié.**

Ce document reprend le diagnostic du [rapport des remboursements B2](STRIPE_SANDBOX_B2_REFUNDS_REPORT.md), le code actuel et les preuves du test navigateur contrôlé réalisé pendant la préparation B2. Aucun nouveau test navigateur, service QA, accès base ou appel API Stripe n'est lancé pour ce travail.

## 1. Scénario reproductible

Précondition : une page de suivi QA déjà chargée, avec des données commerciales valides. Le test enregistré utilisait la commande B-REFUND-FULL avant remboursement, alors en `verified`. Aucun nouveau paiement n'est nécessaire pour reproduire ce défaut ; une API simulée dans un test navigateur convient.

1. Intercepter **une seule requête GET** `/api/submissions/{id}/commercial-state` déclenchée par le retour au focus, et simuler une erreur réseau.
2. Donner le focus à la page. L'alerte « Impossible de charger la commande. Vos données enregistrées sont conservées. » apparaît, tandis que les données précédemment chargées restent visibles.
3. Retirer l'interception ; redonner le focus. La même lecture réussit HTTP 200 et renvoie l'état commercial correct.
4. Constater que **l'alerte persiste après la récupération réussie**.
5. Cliquer sur « Actualiser le statut ». L'alerte disparaît et la lecture réussit ; le paiement et l'échéance restent uniques et inchangés.

Preuves existantes :

- [Diagnostic structuré](validation_artifacts/stripe_sandbox_b2/preparation/v1-diagnostic.json).
- [Panne GET injectée](validation_artifacts/stripe_sandbox_b2/preparation/diagnostic-injected-read-failure.json).
- [Alerte après panne](validation_artifacts/stripe_sandbox_b2/preparation/V1-diagnostic-read-failed.png).
- [Alerte encore présente après succès](validation_artifacts/stripe_sandbox_b2/preparation/V1-diagnostic-error-persists-after-success.png).
- [Disparition après actualisation manuelle](validation_artifacts/stripe_sandbox_b2/preparation/V1-diagnostic-manual-refresh-clears.png).
- `validation_artifacts/stripe_sandbox_b2/preparation/v1-api.jsonl` : lectures navigateur HTTP 200 après la panne contrôlée, notamment à 12:03:49.481 et 12:04:20.211 UTC.

La panne injectée est synthétique, limitée à un GET local. Ce test n'a ni injecté de webhook, ni modifié le paiement.

## 2. Cause technique

Dans [OrderWorkspace](../frontend/src/components/order-workspace.tsx), l'état `error` est partagé entre les erreurs de lecture et les erreurs d'action :

| Chemin actuel | En échec | En succès |
|---|---|---|
| Chargement complet `load()`, ligne 48, appelé au montage et par le polling | Les appelants positionnent `setError(t.error)` aux lignes 68 et 85 | Met à jour `data`, sans retirer l'erreur de lecture précédente |
| Relecture commerciale `refreshCommercial()`, ligne 73, appelée au focus | L'appelant positionne `setError(t.error)`, ligne 78 | Fusionne `commercial`, sans retirer l'erreur précédente |
| Actualisation manuelle, lignes 146–148 | Peut réafficher l'erreur si la requête échoue | Efface explicitement `error` avant la relecture |
| Actions, notamment `act()` et `pay()` | Positionnent également `error` pour les erreurs métier | Utilisent le même état que les lectures |

**Cause prouvée de la persistance :** un succès de lecture ne remet pas à jour l'état d'erreur qui avait été positionné par une lecture précédente. Les données peuvent donc être à jour alors que l'alerte conserve un échec obsolète.

Le chargement complet est un `Promise.all` portant sur commande, résumé, devis et état commercial. La réussite d'un seul GET commercial ne prouve pas que les autres lectures ont récupéré. Un correctif doit distinguer ces portées.

Plusieurs lectures peuvent se chevaucher : montage, focus, polling et actualisation. La correction doit aussi empêcher un ancien échec de réafficher l'alerte après un succès plus récent, ou un ancien succès de masquer un échec plus récent. Les vérifications `mounted` actuelles protègent certaines mises à jour de données, mais ne couvrent pas tous les `catch` au focus/polling.

**Limite :** la cause réseau initiale de l'alerte spontanée observée pendant B1-R n'est pas connue. Les traces disponibles établissent le défaut de persistance, pas la requête exacte ni l'origine de cette panne initiale. Le diagnostic ne conclut pas à un défaut Stripe, à une perte de données ou à un statut financier erroné.

## 3. Conséquences pour l'utilisateur

- L'utilisateur peut croire que la commande reste impossible à charger alors que la récupération serveur a réussi.
- L'alerte peut coexister avec « Paiement vérifié » ou avec une restriction financière légitime, rendant l'écran difficile à interpréter.
- Il peut multiplier les actualisations manuelles et douter de l'enregistrement de sa progression.
- Dans la reproduction enregistrée, aucune saisie ni donnée financière n'a été perdue, aucun doublon de paiement ou d'échéance n'a été créé. Les autorisations restent contrôlées par le backend.

Une suppression globale de toute erreur à chaque GET réussi présenterait un autre problème : elle pourrait masquer un conflit, une validation ou une restriction encore pertinente. La proposition ci-dessous évite cet effacement indifférencié.

## 4. Correctif minimal proposé — non appliqué

Limiter la modification à la gestion des erreurs de lecture dans `OrderWorkspace`, sans changement des routes, des règles financières ou du contrat réseau partagé :

1. **Séparer les erreurs de lecture et d'action.** Conserver le traitement des erreurs métier de `act()`/`pay()` ; ajouter une information de portée aux erreurs de lecture : chargement complet ou état commercial.
2. **Retirer une erreur de lecture seulement après récupération de sa portée.** Une lecture commerciale réussie retire son erreur commerciale ; elle ne masque pas une panne du résumé ou des devis. Un chargement complet réussi peut retirer les erreurs qu'il couvre, sous réserve de leur ordre temporel.
3. **Identifier les lectures courantes.** Utiliser des générations de requêtes par portée, ou un mécanisme équivalent local au composant. Une réponse ancienne ne doit ni réafficher ni effacer une erreur plus récente. Ignorer les résultats après démontage ou changement de commande.
4. **Conserver les formulaires.** Aucune remise à zéro de `dirty`, `modal`, des champs, des clés de formulaire ou des photos en attente pour traiter une erreur de lecture. Les contrôles serveur et les messages de restriction restent actifs.

Comportement recherché : alerte visible durant une vraie panne ; disparition automatique après récupération attestée par une réponse serveur pertinente ; maintien des erreurs métier encore pertinentes.

Il ne s'agit pas de masquer une erreur dans un `catch`, de transformer un échec en succès, d'ajouter un paiement de reprise ou de généraliser une nouvelle architecture de chargement. **Aucun patch ni test frontend n'est écrit à cette étape.**

## 5. Tests de non-régression nécessaires lors d'une future correction autorisée

Ces tests sont à ajouter ou adapter dans les suites frontend existantes avec une API simulée ; ils ne nécessitent aucun paiement Stripe réel.

| Test | Résultat attendu |
|---|---|
| Page chargée → échec commercial au focus → succès du même GET au focus | Alerte apparue puis retirée automatiquement ; données commerciales à jour |
| Paiement `pending` → échec d'un polling complet → polling complet réussi | Alerte retirée ; cadence et conditions du polling conservées |
| Chargement initial échoué → actualisation réussie | Page récupérée, bonne étape de reprise, absence d'alerte obsolète |
| Ancien échec arrivant après un succès plus récent, même portée | Aucun réaffichage de l'ancienne erreur |
| Ancien succès arrivant après un échec plus récent, même portée | Erreur récente toujours visible |
| Chargement complet en échec sur résumé/devis → succès commercial seul | Erreur du chargement complet maintenue |
| Erreur commerciale → chargement complet réussi, sans erreur commerciale plus récente | Erreur commerciale retirée car sa portée est couverte |
| Erreur d'action 409/validation → lecture réussie | Erreur métier non effacée par le seul GET ; restriction commerciale toujours rendue correctement |
| Formulaire/modal avec saisie non enregistrée ou photo en attente → échec puis succès de lecture | Saisies, modal, état `dirty` et photos préservés |
| Restriction financière arrivée après ouverture d'une page `verified` | Focus/409 actualisent l'état ; les actions interdites restent soumises au backend |
| Démontage ou changement de commande pendant une lecture | Aucun résultat tardif appliqué à la nouvelle page ; aucun `catch` périmé ne réaffiche l'alerte |
| Messages FR et EN, retry manuel, absence de panne | Libellés cohérents ; actualisation manuelle conservée ; aucune nouvelle alerte |

Après autorisation de correction : exécuter les tests frontend pertinents, le navigateur V1 avec API simulée, le typage et ESLint. Les validations Stripe existantes restent des preuves distinctes ; ne pas lancer de nouveaux paiements pour ce correctif.

**Décision en attente : validation du correctif frontend limité à ce diagnostic. Travail arrêté à la proposition.**
