# SELBY — Parcours de commande UX/UI V1

## Périmètre livré

1. Espace compte avec vues distinctes Mes commandes / Mes cartes et reprise par référence.
2. Assistant à cinq étapes : Mes cartes, Service, Retour, Devis, Paiement.
3. Modales accessibles pour ajout/édition de carte, sélection de bibliothèque, nouvelle adresse et déclaration d'envoi.
4. Confirmation de commande et acceptation du devis séparées, avec conséquences explicites et consentement non précoché.
5. Tableau distinct après paiement vérifié ; maintien de l'historique de paiement lorsqu'une restriction apparaît ensuite.

Le récapitulatif est compact sur desktop, initialement replié sur mobile. Aucun total définitif
n'est affiché si le serveur ne fournit pas un montant payable complet, ou si une saisie non sauvegardée
rend le récapitulatif obsolète. Les devis invalidés restent consultables dans les détails, sans présenter
leurs anciens montants comme l'offre actuelle.

Les étapes restent montées pour conserver les saisies. Les sorties, fermetures et changements d'étape
avec modifications non enregistrées demandent une décision explicite ; rechargement/fermeture du navigateur
utilisent également son avertissement natif. Les photos locales non enregistrées sont prises en compte.
Une reprise après rechargement utilise les données du serveur et le paramètre `step`, contrôlé par l'état réel.
Les brouillons non enregistrés ne sont pas stockés durablement dans le navigateur.

## Architecture

- `OrderWorkspace` charge commande, récapitulatif, devis et état commercial avec les API existantes.
- `order-flow.ts` détermine la navigation et les états d'affichage sans conférer d'autorisation métier.
- Les choix de services, le formulaire de retour, le catalogue, la bibliothèque, les photos et les devis
  complémentaires réutilisent leurs composants/API métier.
- Le snapshot accepté fournit les informations contractuelles ; aucun recalcul de paiement dans le frontend.
- Le retour de Stripe ne valide rien. Les statuts proviennent du backend ; les états en cours sont interrogés toutes les 5 secondes.
- Les appels de création de session ont un verrou immédiat contre les doubles clics. Les requêtes conservent CSRF et versions.
- Les modales utilisent `dialog`, un nom accessible, une boucle Tab, Échap, l'isolation native et le retour du focus.
- `commercial-display.ts` répare uniquement des libellés synthétiques connus à l'affichage, sans modifier les objets reçus.

## Fichiers ajoutés

- `src/components/order-workspace.tsx`
- `src/components/order-dialog.tsx`
- `src/lib/order-flow.ts`
- `src/lib/commercial-display.ts`
- `src/app/order-workspace.css`
- `tests/order-flow.test.mjs`
- `tests/order-render.test.mjs`
- `tests/order-workspace-browser.mjs`
- `tests/order-workspace-build.mjs`
- `SELBY_ORDER_UX_V1.md`

## Fichiers adaptés

- `src/components/submissions.tsx` : liste et entrée dans l'assistant.
- `src/components/account-area.tsx` : navigation commandes/bibliothèque.
- `src/components/pricing-panel.tsx` : exports réutilisables et présentation des libellés.
- `src/components/checkout-panel.tsx` : formulaire de retour intégrable, libellés et absence de lien de sortie redondant.
- `src/components/paid-order-panel.tsx` : mode demandes complémentaires uniquement, repliable.
- `src/components/submission-photos.tsx` : signalement des fichiers non sauvegardés et protection du changement de copie.
- `src/components/header.tsx`, `src/components/footer.tsx` : identité SELBY du parcours.
- `src/lib/pricing.ts`, `src/lib/checkout.ts`, `src/lib/commercial.ts` : textes FR/EN corrigés.
- `src/app/account/layout.tsx` : titre SELBY ; `src/app/globals.css` : import des styles dédiés.
- `next.config.ts` : dossier de compilation isolé optionnel pour les validations, sans changement des routes API.
- `.gitignore`, `eslint.config.mjs` : exclusion des sorties de compilation des tests.
- `tests/paid-order-browser.mjs`, `tests/stripe-checkout-browser.mjs` : entrées compatibles vers la nouvelle suite navigateur.

## Vérification

Depuis `frontend` :

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
node tests/order-workspace-browser.mjs
node tests/order-workspace-build.mjs
```

La suite navigateur démarre Next et Chrome headless sur les ports 18581–18583, avec une API HTTP
simulée uniquement en mémoire. Elle n'utilise ni PostgreSQL ni Stripe. Les changements de statuts
dans cette fixture ne représentent aucun paiement enregistré dans SELBY.

Résultats : 100 tests unitaires/rendu et 17 scénarios navigateur passent, ainsi que TypeScript et ESLint global.
La compilation optimisée est vérifiée dans `.next-order-ux-build` avec `SELBY_FRONTEND_TEST_DIST_DIR`.
Les captures et le rapport navigateur se trouvent dans `.visual-review/order-workspace-v1/`.
Les cas couvrent les services mixtes, les formulaires interrompus, Tab/Échap/focus, les deux engagements,
les erreurs lecture/écriture, les devis acceptés/historiques, les états Stripe, les restrictions,
la séparation déclaration/réception, les langues FR/EN, le mobile et le périmètre fictif.

## Limites et garanties

- Aucun fichier backend métier, migration, schéma, donnée PostgreSQL ou réglage Stripe n'est modifié.
- Aucun paiement supplémentaire, réel ou TEST, n'est exécuté. L'E2E Stripe réel reste une validation manuelle distincte.
- Le suivi du grading carte par carte demeure indisponible car les API client existantes ne l'exposent pas.
  La réception d'un colis ne devient jamais une preuve de rapprochement ou de traitement des cartes.
- L'accès au clavier est testé dans Chrome ; aucune session avec un lecteur d'écran réel ou sur un appareil mobile physique n'a été exécutée.
- Les anciens textes fictifs persistés sont seulement réparés pour l'affichage ; les snapshots et la configuration PostgreSQL restent inchangés.
- La version installée de Next a signalé un avertissement de sécurité pendant les commandes de validation.
  Aucune dépendance n'a été mise à jour dans cette refonte.
