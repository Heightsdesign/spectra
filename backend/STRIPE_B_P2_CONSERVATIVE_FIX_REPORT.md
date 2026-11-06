# SELBY — Lot B / B-P2 — Correctif conservateur

Date : 6 novembre 2026. Référence : [investigation B-P2](STRIPE_SANDBOX_B_P2_INVESTIGATION.md).

**Correctif local implémenté et validé par tests déterministes. B-P2 reste ouvert : aucune validation fournisseur de l'atteignabilité de `complete/unpaid + requires_action` n'est apportée par ces tests.**

## Modifications

### API et rapprochement

Dans `app/stripe_checkout.py`, la branche existante de `start_checkout` conserve le statut financier `action_required` pour une Session `complete/unpaid` dont le PI est `requires_action`. La réponse comporte désormais une indication de présentation :

```json
{
  "status": "action_required",
  "url": null,
  "payment_review_required": true
}
```

Les autres réponses Checkout portent `payment_review_required: false`. Aucun `next_action`, client secret ou lien de remplacement n'est exposé. L'indication ne promet pas qu'un dossier opérateur a été créé ni qu'une notification a été envoyée.

Au traitement d'un événement Stripe, si les objets canoniques relus indiquent exactement `complete/unpaid + requires_action`, seule l'ancienne URL de navigation `StripeAttempt.checkout_url` est effacée. Les transitions financières, restrictions, preuves d'événements et critères de confirmation existants restent inchangés. Cela permet d'afficher la revue après un webhook, même sans POST de reprise préalable.

Le nouveau helper `payment_review_required` déduit l'indication de l'état local `action_required` et de l'absence d'URL de navigation. Par prudence, une action sans URL conservée est donc présentée en revue même si le moyen de paiement précis n'est pas connu. Aucun nouveau statut financier, marqueur de hold ou champ de base n'est ajouté.

Cette indication est disponible dans :

- POST `stripe-checkout` ;
- GET `payments/{quote_id}` dans `app/stripe_api.py` ;
- l'état commercial principal dans `app/commercial.py` ;
- les devis complémentaires dans `app/commercial_api.py`.

Pour les réponses commerciales, `charging_enabled` devient faux lorsque la revue est requise : c'est la disponibilité de l'action présentée au client. La route Checkout conserve les protections de tentative et d'idempotence existantes ; plusieurs POST B-P2 renvoient la même situation sans nouvelle tentative payable. Il n'y a aucun blocage financier `restricted`.

Un succès fournisseur ultérieur continue de suivre le rapprochement normal. Une fois le paiement vérifié, l'indication de revue est fausse ; elle ne bloque pas la confirmation. Un état restreint conserve également sa présentation préexistante.

### Frontend FR/EN

`src/lib/commercial.ts` définit le champ optionnel, les helpers partagés et les messages :

- FR : « Paiement en attente — vérification par SELBY nécessaire. Vous pouvez actualiser ou contacter SELBY. »
- EN : « Payment pending — SELBY verification required. You can refresh or contact SELBY. »

La vue de paiement principale est isolée dans `src/components/order-payment.tsx`, utilisée par `order-workspace.tsx`, afin de vérifier son rendu réel en tests. En revue, aucun bouton de paiement/reprise ni invitation à reprendre Checkout n'est affiché ; l'actualisation et le détail du devis restent disponibles. Le gestionnaire de paiement applique aussi le garde partagé contre une indication `charging_enabled` obsolète.

`paid-order-panel.tsx` applique le même affichage au paiement principal et aux devis complémentaires. L'actualisation périodique existante reste active ; elle couvre également les paiements complémentaires en attente. Une actualisation manuelle reste disponible pour un complément en revue, y compris dans l'affichage des seuls compléments. La reprise d'une Session ouverte reste disponible comme auparavant.

## Tests et résultats

Tous les appels Stripe des tests backend sont simulés, avec transport réel interdit. PostgreSQL utilise les bases locales existantes : schémas déjà en révision `0015`, aucune migration autorisée par le banc.

| Contrôle final | Résultat |
|---|---|
| Régression backend Lot B, `validation_tests/stripe_batch_b/test_batch_b.py` | **46 réussites** |
| Dont variantes B-P2 | **8 réussites** : action absente, `null`, `use_stripe_sdk`, type inconnu, avec/sans webhook préalable |
| Frontend `npm test` | **105 réussites**, dont 4 nouveaux tests de revue |
| Frontend `npm run typecheck` | **Réussi**, TypeScript sans erreur |
| ESLint hors build QA généré | **Réussi**, zéro avertissement |
| Compilation Python des quatre modules applicatifs modifiés et du test Lot B | **Réussie** |

Les variantes B-P2 vérifient :

- réponse explicite de revue, sans URL ni secret, état commercial conservé à `action_required` et aucune restriction financière ajoutée ;
- détection par webhook avant toute reprise, ou par POST sans webhook préalable ;
- trois POST successifs sur la même tentative, une seule Session créée et aucun appel simulé d'annulation/remplacement ;
- zéro paiement, échéance et audit de confirmation avant succès ;
- succès ultérieur sur le même PI, puis événements de succès doublés et événement `requires_action` retardé/rejoué ;
- une seule confirmation, un seul audit de confirmation et une seule échéance, sans changement lors des rejeux ;
- échéance exactement égale à `verified_at + 30 jours`, indication de revue supprimée après confirmation.

Le banc exporte les libellés des vrais helpers frontend, dont la revue FR/EN et l'indisponibilité de la reprise. Les nouveaux tests frontend vérifient en outre le rendu React de la vue principale dans les deux langues : message SELBY, bouton d'actualisation, absence de bouton/invitation de reprise. Les helpers sont vérifiés pour une Session ouverte, une permission de paiement obsolète et les états ultérieurs vérifié/restreint. Il ne s'agit pas d'une validation navigateur de bout en bout.

### Commandes de validation

Depuis `backend`, avec `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` et `SELBY_STRIPE_BATCH_B_RUN_ID=b_p2_conservative_fix_final_evidence` :

```text
.venv/Scripts/python.exe -m pytest validation_tests/stripe_batch_b/test_batch_b.py --confcutdir=validation_tests/stripe_batch_b -c pytest.ini -p no:cacheprovider -q --tb=short --basetemp=validation_artifacts/stripe_sandbox_b_p2/fix-final-evidence-tmp
```

Depuis `frontend` :

```text
npm test
npm run typecheck
node node_modules/eslint/bin/eslint.js . --ignore-pattern=.next-stripe-b1r-qa/** --max-warnings=0
```

`npm run lint` sans exclusion échoue sur les fichiers générés préexistants de `.next-stripe-b1r-qa` : 309 erreurs et 1 991 avertissements. La commande finale exclut uniquement ce build QA en plus des exclusions déjà configurées ; aucune règle ESLint ni source applicative n'est désactivée. La configuration lint n'a pas été modifiée.

Deux avertissements backend non bloquants subsistent : dépréciation Starlette/httpx du TestClient et option `cache_dir` inconnue lorsque le plugin cache est désactivé. Aucun outil/configuration de typage ou lint Python n'est défini dans le périmètre backend consulté ; la compilation Python est un contrôle syntaxique, pas une vérification statique de types. Ruff n'est pas installé dans le virtualenv et n'a pas été installé pour cette intervention.

### Preuves et isolation

Preuves finales : `validation_artifacts/stripe_batch_b/b_p2_conservative_fix_final_evidence/`, notamment `isolation.json`, `ui-cases.json` et `findings.json`.

Le contrôle final confirme :

- `development_unchanged: true` : empreintes complètes de `spectra` conservées ;
- `test_data_and_schema_unchanged: true` : données existantes et schéma de `spectra_test` conservés après rollback de toutes les fixtures ;
- `application_sources_unchanged: true` pendant la passe de tests ;
- `forbidden_sql_or_migration_attempts: []` et `real_stripe_http_attempts: 0`.

Le scénario synthétique B-P2 rouge a été remplacé par les assertions de revue expressément autorisées. Deux assertions de réponses complètes pour annulation/expiration ont été adaptées au champ API additionnel faux, sans modifier leur scénario ou comportement. Les règles et scénarios B-DISPUTE n'ont pas été modifiés ; leurs objets existants sont couverts par les empreintes d'isolation.

## Limites et maintien de B-P2 ouvert

L'indication reflète le dernier rapprochement local. Un GET commercial n'interroge pas Stripe ; une transition fournisseur doit être observée par le webhook ou la route de reprise existante avant d'être reflétée. Aucune migration de données historiques ou nouvelle tâche de surveillance n'est créée.

Aucune récupération via Stripe.js, aucun client secret, aucune URL déduite et aucune nouvelle tentative payable n'ont été ajoutés. Les délais, horodatages, règles financières, snapshots acceptés, historiques et journaux existants sont préservés. Aucune intervention réelle sur Stripe, aucun remboursement, aucune réponse au litige ni annulation de PI n'a été effectué.

La branche préexistante d'annulation des PI `requires_payment_method` associés à une Session terminée, signalée dans l'investigation, reste inchangée et hors du correctif B-P2. Les tests de cette branche restent des simulations, sans preuve d'autorisation par Stripe. Le présent correctif ne nécessite pas de modifier ce mécanisme financier et ne constitue pas sa validation fournisseur.

**B-P2 reste ouvert jusqu'à la validation fournisseur prévue dans l'investigation.** Le passage au vert des tests déterministes valide uniquement la réponse conservatrice de SELBY, pas l'atteignabilité ni une capacité de récupération réelle de Stripe.
