import type { Submission } from './submissions.ts';
import type { Order } from './checkout.ts';
import type { Quote } from './pricing.ts';
import type { CommercialState } from './commercial.ts';

export const orderSteps = ['cards', 'service', 'return', 'quote', 'payment'] as const;
export type OrderStep = typeof orderSteps[number];
export type OrderData = { item: Submission; order: Order; quote: Quote | null; commercial: CommercialState };
export function acceptedQuote(quotes: Quote[], acceptedId?: string | null): Quote | null {
  if (acceptedId) return quotes.find(q => q.id === acceptedId && q.status === 'accepted') ?? null;
  return quotes.find(q => q.status === 'accepted') ?? quotes.find(q => q.status === 'valid') ?? quotes[0] ?? null;
}
export function resumeStep(data: OrderData): OrderStep {
  if (data.commercial.accepted_quote_id || data.order.terms_accepted || data.quote?.status === 'accepted') return 'payment';
  if (data.item.status === 'submitted') return data.order.readiness.ready ? 'quote' : 'return';
  if (!data.item.entries.length) return 'cards';
  if (data.item.entries.some(e => !e.processing_tier || !e.upgrade_ids.length)) return 'service';
  if (!data.order.readiness.ready) return 'return';
  return 'quote';
}
export function canVisitStep(step: OrderStep, data: OrderData): boolean {
  if (step === 'cards') return true;
  if (!data.item.entries.length) return false;
  if (step === 'payment') return Boolean(data.commercial.accepted_quote_id || data.quote?.status === 'accepted' || data.order.terms_accepted);
  return true;
}
export function canAcceptQuote(data: OrderData, time = Date.now()): boolean {
  const q = data.quote;
  return Boolean(data.item.status === 'submitted' && q?.status === 'valid' && Date.parse(q.expires_at) > time
    && q.snapshot.commercial_terms_version && q.snapshot.checkout?.readiness.ready
    && (!q.snapshot.development_only || (q.snapshot.stripe_test_only && q.snapshot.checkout.stripe_test_only)));
}
export function isTracking(data: OrderData): boolean {
  return data.commercial.payment_status === 'verified'
    || (data.commercial.payment_status === 'restricted' && data.commercial.verified_payment_at !== null);
}
export function nextAction(state: CommercialState): 'restricted' | 'received' | 'declared' | 'dispatch' | 'payment' {
  if (state.payment_status === 'restricted') return 'restricted';
  if (state.parcel_receipts.length) return 'received';
  if (state.shipment_declarations.length) return 'declared';
  return state.payment_status === 'verified' ? 'dispatch' : 'payment';
}
export const orderMessages = {
  FR: {
    title:'Votre commande', cards:'Mes cartes', service:'Service', return:'Retour', quote:'Devis', payment:'Paiement', step:'Étape', of:'sur', next:'Continuer', back:'Précédent', account:'Mes commandes', resume:'Reprendre la commande', open:'Voir la commande',
    loading:'Chargement de votre commande…', error:'Impossible de charger la commande. Vos données enregistrées sont conservées.', retry:'Réessayer', summary:'Votre récapitulatif', count:'Cartes', total:'Montant payable', undetermined:'À déterminer', estimate:'Le montant sera confirmé lorsque le devis sera complet.',
    add:'Ajouter une carte', library:'Choisir dans mes cartes', empty:'Votre sélection commence ici.', emptyHint:'Ajoutez une carte ou retrouvez celles de votre collection.', edit:'Modifier', remove:'Retirer', saveCard:'Enregistrer la carte', details:'Détails et photos', optional:'Facultatif', saved:'Modifications enregistrées.',
    unsaved:'Des modifications ne sont pas enregistrées.', leaveTitle:'Conserver vos modifications ?', leaveHint:'Revenez au formulaire pour les enregistrer, ou abandonnez uniquement les modifications non sauvegardées.', stay:'Revenir au formulaire', discard:'Abandonner les modifications', close:'Fermer', locked:'Commande confirmée : les cartes et les services sont consultables uniquement.', mixed:'Plusieurs services', perCard:'Personnaliser par carte',
    serviceHint:'Choisissez le service et la présentation de vos cartes.', saveService:'Enregistrer et continuer', mixedHint:'Les choix propres à chaque carte sont conservés. Leur remplacement global exige votre accord.', replace:'Remplacer les choix de toutes les cartes', returnHint:'Préparez le retour de vos cartes. La valeur déclarée est distincte des frais de grading.', newAddress:'Ajouter une adresse', saveAddress:'Enregistrer cette adresse', returnLocked:'Le retour fait partie du devis accepté et ne peut plus être modifié.', returnBlocked:'Complétez ces éléments pour obtenir un devis payable.',
    confirmTitle:'1. Confirmer la commande', confirmHint:'Cette opération fige les cartes et les services. Elle n’accepte pas le devis et ne déclenche aucun paiement.', confirm:'Confirmer la commande', acceptTitle:'2. Accepter le devis', acceptHint:'Vous acceptez le montant et la version des conditions affichés. Le paiement reste une étape distincte.', accept:'Accepter le devis', consent:'J’accepte le montant du devis et les conditions', confirmed:'Commande confirmée', accepted:'Devis accepté', generate:'Générer le devis', recalculate:'Recalculer le devis', quoteHint:'Vérifiez votre sélection et le montant avant de vous engager.', quoteDetails:'Détail du devis et conditions', noQuote:'Aucun devis enregistré.', legacy:'Ce devis historique ne contient pas de montant payable complet. Aucun paiement ne peut être proposé.', expired:'Ce devis a expiré ou doit être recalculé. Les conditions ne peuvent pas être acceptées en l’état.',
    grading:'Grading', shipping:'Retour', tax:'Taxes', pay:'Payer avec Stripe TEST', payHint:'Vous allez ouvrir Stripe Checkout en mode TEST. SELBY confirmera le paiement après vérification serveur.', pending:'Vérification du paiement', pendingHint:'Vous pouvez quitter cette page et revenir. Seule la confirmation vérifiée par SELBY valide le paiement.', paid:'Paiement vérifié', payUnavailable:'Le paiement est indisponible pour cette commande.', refresh:'Actualiser le statut', tracking:'Suivi de commande', nextAction:'Prochaine étape', paidAmount:'Montant payé', deadline:'Échéance d’expédition',
    dispatch:'Préparer votre envoi', dispatchHint:'Déclarez votre envoi après l’avoir effectué. La date limite est calculée à partir du paiement vérifié.', declare:'Déclarer mon envoi', declared:'Envoi déclaré', declaredHint:'Votre déclaration est enregistrée. La réception par SELBY reste à confirmer.', received:'Colis reçu', receivedHint:'Une réception a été enregistrée. Le rapprochement des cartes reste une opération distincte.', restricted:'Examen requis', restrictedHint:'Cette commande comporte une restriction financière. Contactez SELBY avant toute nouvelle action.', progress:'Progression de votre commande', noProduction:'La progression du grading carte par carte n’est pas disponible dans cet espace.', shipment:'Retour et historique', cardsDetails:'Cartes et services', processing:'Traitement des cartes', unavailable:'Information non disponible',
    test:'FICTIF — STRIPE TEST', testHint:'Montants, fiscalité, suivi et couverture simulés. Aucun service réel. N’envoyez aucune carte.', testNext:'Parcours TEST : aucune expédition réelle attendue.', actionError:'L’action n’a pas été confirmée. Vos données sont conservées. Vérifiez le statut avant de réessayer.', duePolicy:'Le délai est de 30 jours après paiement vérifié. Aucun retard ne déclenche automatiquement de pénalité, d’annulation ou de remboursement.', acceptedAt:'Accepté le', version:'Version des conditions', shipmentHint:'Une déclaration client ne constitue ni une preuve transporteur ni une réception physique.', supplemental:'Demandes complémentaires', notes:'Notes sur la commande', editCard:'Modifier la carte', allSaved:'Données enregistrées', noAction:'Aucune action requise pour le moment.',
  },
  EN: {
    title:'Your order', cards:'My cards', service:'Service', return:'Return', quote:'Quote', payment:'Payment', step:'Step', of:'of', next:'Continue', back:'Previous', account:'My orders', resume:'Resume order', open:'View order',
    loading:'Loading your order…', error:'Unable to load this order. Your saved data is preserved.', retry:'Try again', summary:'Your summary', count:'Cards', total:'Payable amount', undetermined:'To be determined', estimate:'The amount will be confirmed when the quote is complete.',
    add:'Add a card', library:'Choose from my cards', empty:'Your selection starts here.', emptyHint:'Add a card or select one from your collection.', edit:'Edit', remove:'Remove', saveCard:'Save card', details:'Details and photos', optional:'Optional', saved:'Changes saved.',
    unsaved:'You have unsaved changes.', leaveTitle:'Keep your changes?', leaveHint:'Return to the form to save them, or discard only your unsaved changes.', stay:'Return to form', discard:'Discard changes', close:'Close', locked:'Order confirmed: cards and services are read-only.', mixed:'Multiple services', perCard:'Customize per card',
    serviceHint:'Choose the service and presentation for your cards.', saveService:'Save and continue', mixedHint:'Individual card choices are preserved. Replacing them all requires your consent.', replace:'Replace the choices for every card', returnHint:'Prepare your return delivery. Declared value is separate from grading fees.', newAddress:'Add an address', saveAddress:'Save this address', returnLocked:'Return details belong to the accepted quote and cannot be changed.', returnBlocked:'Complete these items to obtain a payable quote.',
    confirmTitle:'1. Confirm order', confirmHint:'This locks the cards and services. It does not accept a quote or take a payment.', confirm:'Confirm order', acceptTitle:'2. Accept quote', acceptHint:'You accept the displayed amount and terms version. Payment remains a separate step.', accept:'Accept quote', consent:'I accept the quote amount and the terms', confirmed:'Order confirmed', accepted:'Quote accepted', generate:'Generate quote', recalculate:'Recalculate quote', quoteHint:'Review your selection and amount before committing.', quoteDetails:'Quote details and terms', noQuote:'No saved quote.', legacy:'This historical quote has no complete payable amount. Payment cannot be offered.', expired:'This quote has expired or needs recalculation. Its terms cannot be accepted as shown.',
    grading:'Grading', shipping:'Return', tax:'Tax', pay:'Pay with Stripe TEST', payHint:'You will open Stripe Checkout in TEST mode. SELBY confirms payment after server verification.', pending:'Verifying payment', pendingHint:'You can leave and return. Only SELBY’s verified confirmation validates payment.', paid:'Payment verified', payUnavailable:'Payment is unavailable for this order.', refresh:'Refresh status', tracking:'Order tracking', nextAction:'Next step', paidAmount:'Amount paid', deadline:'Dispatch deadline',
    dispatch:'Prepare your shipment', dispatchHint:'Declare your shipment after sending it. The deadline starts at verified payment.', declare:'Declare my shipment', declared:'Shipment declared', declaredHint:'Your declaration is recorded. Receipt by SELBY is still to be confirmed.', received:'Parcel received', receivedHint:'A receipt has been recorded. Card reconciliation remains a separate operation.', restricted:'Review required', restrictedHint:'This order has a financial restriction. Contact SELBY before taking further action.', progress:'Order progress', noProduction:'Card-by-card grading progress is not available in this space.', shipment:'Return and history', cardsDetails:'Cards and services', processing:'Card processing', unavailable:'Information unavailable',
    test:'FICTIONAL — STRIPE TEST', testHint:'Simulated prices, tax, tracking and coverage. No real service. Do not ship cards.', testNext:'TEST journey: no real shipment expected.', actionError:'The action was not confirmed. Your data is preserved. Check the status before trying again.', duePolicy:'The deadline is 30 days after verified payment. Late dispatch does not automatically trigger a penalty, cancellation or refund.', acceptedAt:'Accepted on', version:'Terms version', shipmentHint:'A customer declaration is neither carrier evidence nor physical receipt.', supplemental:'Additional requests', notes:'Order notes', editCard:'Edit card', allSaved:'Saved data', noAction:'No action needed at this time.',
  },
} as const;
