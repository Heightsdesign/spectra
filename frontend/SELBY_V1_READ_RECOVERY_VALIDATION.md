# SELBY — Intervention A : correction ciblée de l'alerte V1

6 novembre 2026. Intervention terminée et validée localement avant le démarrage du scénario Stripe B-DISPUTE.

## Résultat

L'erreur de lecture disparaît après récupération réussie de la portée concernée. Les réponses obsolètes ne peuvent plus réafficher une ancienne erreur, effacer une erreur plus récente ou remplacer une restriction commerciale plus récente. Les saisies non enregistrées et les erreurs métier restent conservées.

Modification applicative limitée à `src/components/order-workspace.tsx` :

- Erreurs de lecture distinctes de l'état d'erreur d'action existant, avec portées chargement complet et état commercial.
- Générations de requêtes par portée et contexte lié à la commande, invalidé au démontage/changement d'identifiant.
- Chargement complet conservant une réponse commerciale plus récente, sans masquer une panne du résumé/devis par un simple succès commercial.
- Échecs de relecture après action traités comme erreurs de lecture, sans les convertir en erreurs métier persistantes.
- Aucune réinitialisation des formulaires, des photos en attente, de `dirty` ou de la fenêtre ouverte pour récupérer une lecture.

Aucun fichier `backend/app`, fichier `.env`, règle financière ou logique de reprise B-P2 modifié. Aucun appel Stripe ni accès PostgreSQL pendant cette intervention.

## Validation finale

| Vérification | Résultat |
|---|---|
| `npm.cmd test` | **101 tests réussis** |
| `npm.cmd run typecheck` | Réussi |
| `npm.cmd run lint -- --ignore-pattern '.next-stripe-b1r-qa/**'` | Réussi, zéro avertissement |
| Navigateur Next + Chrome avec API en mémoire | **32 scénarios réussis**, dont 14 nouveaux scénarios de récupération/non-régression |
| Empreintes backend et `.env` | 58 fichiers identiques au relevé documentaire antérieur |
| Arrêt du banc navigateur A | Ports 18581, 18582 et 18583 fermés |

Commande navigateur :

```powershell
$env:SELBY_ORDER_BROWSER_OUTPUT='.visual-review/v1-read-recovery'
node tests/order-workspace-browser.mjs
```

Les nouveaux cas vérifient la récupération au focus et au polling, les deux ordres succès/échec retardés des lectures commerciales et complètes, la conservation d'une restriction plus récente, les erreurs de portée différente, les saisies et l'erreur métier 409 dans une fenêtre d'expédition, l'anglais et l'échec tardif après démontage. Le test de rejet financier conserve le texte d'erreur et la saisie après un GET réussi. Les protections de navigation, consentement, idempotence de clic et réception physique déjà testées restent conformes.

Le premier lancement Chrome a échoué dans le sandbox ; le banc a ensuite été lancé avec l'autorisation nécessaire. Un premier essai des nouveaux cas a révélé un mauvais sélecteur de test : le bouton d'expédition TEST est de style outline. Le test vérifie désormais l'action visible par son texte et sa disponibilité. La version finale passe intégralement.

Le lint global sans exclusion parcourt l'ancien répertoire de compilation `.next-stripe-b1r-qa` et échoue sur ses fichiers générés. La validation finale exclut explicitement ce seul répertoire ; aucune configuration ESLint ni dépendance n'a été modifiée pour masquer une erreur source.

Preuves : [.visual-review/v1-read-recovery/validation.json](.visual-review/v1-read-recovery/validation.json) et [checks.json](.visual-review/v1-read-recovery/checks.json). Les interactions de paiement du banc sont entièrement simulées : une initiation simulée, zéro paiement réel, zéro requête Stripe et aucune base.

**B-P2 reste ouvert. Le présent correctif ne crée aucune récupération ou tentative de paiement supplémentaire.**
