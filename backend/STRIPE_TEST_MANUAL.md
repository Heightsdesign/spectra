# Premier paiement manuel FICTIF — STRIPE TEST

Les configurations ont été publiées dans PostgreSQL local le 5 novembre 2026.
Le reçu est dans `pricing/fictitious-stripe-test-publication.json`.
Tarifs : Standard 10 EUR/carte, Classic incluse, retour France 5 EUR, taxe synthétique 0 %.
Deux cartes = 2 500 centimes EUR TEST. Aucun transport, couverture ou grading réel.

## 1. Préparer les services

Conserver le listener Stripe déjà opérationnel, sur le même compte TEST que le backend.
S'il faut le relancer, dans un terminal séparé :

```powershell
stripe listen --events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,payment_intent.succeeded,payment_intent.processing,payment_intent.requires_action,payment_intent.payment_failed,payment_intent.canceled,charge.refunded,charge.dispute.created,charge.dispute.updated,charge.dispute.closed,charge.dispute.funds_withdrawn,charge.dispute.funds_reinstated,refund.created,refund.updated,refund.failed --forward-to http://127.0.0.1:8000/api/stripe/webhook
```

Vérifier que `STRIPE_WEBHOOK_SECRET` dans `backend/.env` correspond au secret annoncé
par CE listener. Le garder privé. Les secrets Dashboard et CLI sont distincts.
Ne pas utiliser `stripe trigger` pour ce parcours.

Redémarrer le backend : la nouvelle option d'environnement est mise en cache au démarrage.
Depuis `C:\Users\plher\Documents\spetra\backend` :

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Les options locales attendues sont `AUTH_ENVIRONMENT=development`, `STRIPE_ENABLED=true`,
`STRIPE_MODE=test`, `STRIPE_FICTITIOUS_ENABLED=true`, `AUTH_ORIGIN=http://127.0.0.1:3000`.
Les identifiants Stripe existants restent privés et inchangés.

Dans un autre terminal, depuis `C:\Users\plher\Documents\spetra\frontend` :

```powershell
npm.cmd run dev
```

Si ces serveurs tournent déjà, arrêter leurs anciens processus dans leurs terminaux avant
de les relancer sur les mêmes ports. Ne pas lancer de migration.

## 2. Créer et accepter une nouvelle commande

1. Ouvrir `http://127.0.0.1:3000/account`, se connecter avec un compte client vérifié,
   puis choisir **Créer une commande**. Ne pas réutiliser une ancienne commande.
2. Ajouter deux cartes Pokémon (deux entrées de quantité 1 conviennent).
3. Choisir **Standard** et l'étiquette **Classic**, puis enregistrer les choix.
4. Créer une adresse fictive dans le carnet d'adresses du compte : destinataire
   `Client TEST`, adresse `1 rue du Test`, code postal `75001`, ville `Paris`, pays `FR`.
   Le téléphone est facultatif pour ce service fictif.
5. Dans **Préparer le retour**, sélectionner cette adresse, saisir une valeur totale
   estimée de `100` EUR et choisir **FICTIF — STRIPE TEST : retour France**.
   Enregistrer. La limite de couverture simulée est de 1 000 EUR ; aucun poids ni
   dimension n'est requis pour ce forfait.
6. Vérifier le bandeau FICTIF, le grading à **20 EUR**, le retour à **5 EUR**, la taxe à
   **0 EUR** et le montant payable à **25 EUR**. Aucun blocage ne doit subsister.
7. Confirmer la soumission, puis générer/recalculer le devis. Le statut doit être valide.
8. Vérifier les conditions `FICTIF-STRIPE-TEST-v1-NO-REAL-SERVICE`, cocher le consentement
   et accepter le devis. Cette acceptation ne réalise aucun paiement.
9. Noter l'UUID de commande dans l'URL et l'UUID du devis dans les requêtes réseau.
10. Dans **Paiement et envoi**, cliquer sur **Payer avec Stripe TEST**.

## 3. Payer dans Stripe Checkout

Vérifier le mode TEST et le montant **25 EUR**. Sélectionner le paiement par carte,
puis utiliser `4242 4242 4242 4242`, une expiration future (par exemple `12/34`) et
le CVC `123`. Renseigner les autres champs fictivement si demandés.

Source officielle : https://docs.stripe.com/testing

Valider le paiement et revenir à SELBY. Le paramètre de retour ne prouve pas le paiement.
Laisser le listener ouvert. Attendre les webhooks et le rafraîchissement du statut
(interrogation toutes les 5 secondes pour un paiement en cours).

## 4. Vérifier après le webhook

- Le listener doit montrer HTTP **200** pour les événements de cette vraie session SELBY,
  notamment `payment_intent.succeeded` et `checkout.session.completed`.
- SELBY doit afficher le paiement vérifié ; le bouton de paiement disparaît.
- Dans les outils réseau du navigateur, `GET /api/submissions/UUID/commercial-state`
  doit renvoyer `payment_status: "verified"`, `charging_enabled: false`, aucune restriction,
  une date de paiement et une échéance 30 jours UTC après celle-ci.
- Dans Stripe TEST, le paiement doit être réussi, à **2 500 centimes EUR**, avec une
  session `cs_test_...`, un PaymentIntent `pi_...` et les métadonnées SELBY correspondantes.
- Recharger la page ne doit créer aucun paiement ou échéance supplémentaire.

Pour contrôler PostgreSQL avec votre outil SQL habituel, remplacer `UUID_COMMANDE`
ci-dessous par l'UUID de la NOUVELLE commande. Toutes ces requêtes sont en lecture seule :

```sql
BEGIN READ ONLY;
SET LOCAL app.stripe_test_submission = 'UUID_COMMANDE';

SELECT a.quote_id,
       q.snapshot->>'development_only' AS development_only,
       q.snapshot->>'stripe_test_only' AS stripe_test_only,
       q.snapshot->'checkout'->'readiness' AS readiness,
       q.snapshot->'checkout'->>'final_payable_minor' AS snapshot_amount,
       o.amount_minor AS obligation_amount, o.currency,
       p.provider, p.amount_minor AS verified_amount,
       p.provider_payment_id, p.provider_event_id, p.verified_at,
       d.dispatch_deadline,
       (SELECT count(*) FROM verified_payments v WHERE v.quote_id = a.quote_id) AS payment_count,
       (SELECT count(*) FROM dispatch_expectations e WHERE e.quote_id = a.quote_id) AS deadline_count
FROM quote_acceptances a
JOIN submission_quotes q ON q.id = a.quote_id
JOIN payment_obligations o ON o.quote_id = a.quote_id
LEFT JOIN verified_payments p ON p.quote_id = a.quote_id
LEFT JOIN dispatch_expectations d ON d.quote_id = a.quote_id
WHERE a.submission_id = current_setting('app.stripe_test_submission')::uuid;

SELECT t.id, t.quote_id, t.session_id, t.payment_intent_id, t.status
FROM stripe_attempts t
JOIN payment_obligations o ON o.quote_id = t.quote_id
WHERE o.submission_id = current_setting('app.stripe_test_submission')::uuid;

SELECT e.event_id, e.kind, e.restricted, e.data
FROM stripe_evidence e
JOIN payment_obligations o ON o.quote_id = e.quote_id
WHERE o.submission_id = current_setting('app.stripe_test_submission')::uuid
ORDER BY e.created_at;

ROLLBACK;
```

Résultat attendu : montants tous à **2500**, devise **EUR**, fournisseur **stripe_test**,
marqueurs de développement et TEST à **true**, readiness à **true**, une confirmation,
une échéance et une tentative `verified` pour ce premier parcours sans abandon.
Plusieurs preuves webhook de types différents sont normales ; elles ne sont pas des paiements multiples.

Si le statut reste en attente, relever uniquement les UUID et identifiants `cs_test_`, `pi_`,
`evt_`, les codes HTTP et messages d'erreur. Un HTTP 400 lié à cette session SELBY doit
être investigué ; ne pas le traiter comme un événement synthétique attendu.
Un secret de signature incorrect nécessite sa correction puis le redémarrage du backend.
Ne jamais forcer le paiement en SQL ni créer une nouvelle commande pour masquer l'échec.

## Validation technique avant publication

113 tests backend et 80 tests frontend passent ; TypeScript et ESLint des fichiers modifiés passent.
Le lint global échoue sur deux avertissements préexistants dans `paid-order-browser.mjs`
et `stripe-checkout-browser.mjs`, fichiers non modifiés.
Les suites Stripe couvrent notamment signature, montant exact, refus LIVE, idempotence et concurrence.
Le nouveau test vérifie que les exemples de développement ordinaires restent non acceptables,
que la publication et la lecture fictives sont refusées hors périmètre, et que les anciens
enregistrements restent identiques.
La base locale reste à 0015 ; aucun nouveau fichier de migration n'a été ajouté.
Les tests utilisent la base dédiée et leurs schémas isolés, jamais les commandes locales.
Aucune session Stripe réelle ni aucun paiement n'a été créé pendant l'implémentation.
