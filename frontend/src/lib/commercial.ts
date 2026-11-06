import type { PriceLine } from './pricing.ts';

export type CommercialState = {
 payment_review_required?:boolean; financial_restrictions?:string[]; charging_enabled:boolean; accepted_quote_id?:string|null; payment_status:'quote_not_accepted'|'awaiting_payment'|'verified'|'creating'|'pending'|'action_required'|'failed'|'cancelled'|'expired'|'restricted';
 verified_payment_at:string|null;dispatch_deadline:string|null;indicators:string[];
 shipment_declarations:{id:string;carrier:string;tracking:string;declared_dispatch_at:string|null;recorded_at:string;verification:'customer_declared_only'}[];
 parcel_receipts:{id:string;reference:string;received_at:string}[];
};
export type SupplementQuote = {
 id:string;physical_card_id:string;status:string;payment_status:string;payment_review_required?:boolean;charging_enabled?:boolean;financial_restrictions?:string[];
 snapshot:{commercial_terms_version:string;lines:PriceLine[];checkout:{currency:'EUR';final_payable_minor:number;tax_total_minor:number;net_total_minor:number;shipping:{charge_minor:number;service:{name:{FR:string;EN:string}}};return_address:{country:string;city:string;line1:string}}};
};
export function canDeclareShipment(state:CommercialState):boolean {
 return state.payment_status==='verified'&&state.verified_payment_at!==null&&state.dispatch_deadline!==null;
}
export function supplementaryConsent(accepted:boolean) {
 if(!accepted)throw Error('explicit_terms_required');
 return {accept_terms:true};
}
export const commercialMessages = {
 FR:{operatorReview:'Paiement en attente — vérification par SELBY nécessaire. Vous pouvez actualiser ou contacter SELBY.',refunded:'Remboursement intégral — examen requis',partially_refunded:'Remboursement partiel — examen requis',commercial_hold:'Blocage commercial',dispute_review:'Litige — examen requis',financial_review:'Examen financier requis',creating:'Création du paiement',pending:'Paiement en cours de vérification',action_required:'Action requise — reprendre Checkout',failed:'Tentative échouée — réessayer Checkout',cancelled:'Tentative annulée',expired:'Session expirée — réessayer',restricted:'Paiement soumis à une restriction — contactez SELBY',title:'Paiement et envoi',quote_not_accepted:'Devis non accepté',awaiting_payment:'Devis accepté · paiement en attente',verified:'Paiement vérifié',awaiting_verified_payment:'Attente du paiement vérifié',awaiting_customer_dispatch:'Attente de votre envoi',customer_shipment_declared:'Envoi déclaré par le client',dispatch_deadline_approaching:'Échéance d’expédition proche',dispatch_deadline_passed:'Échéance d’expédition dépassée',parcel_received:'Colis reçu · rapprochement distinct',manual_review_required:'Examen manuel nécessaire',deadline:'Échéance d’expédition',expectation:'Les 30 jours commencent après le paiement vérifié. Un retard ne déclenche ni annulation, ni pénalité, ni remboursement automatique.',declaration:'Déclarer un envoi',declaredDate:'Date d’expédition déclarée (facultative)',carrier:'Transporteur (facultatif)',tracking:'Suivi (facultatif)',save:'Enregistrer la déclaration',unverified:'Déclaration du client uniquement : aucune preuve d’acceptation par le transporteur ou de réception physique.',supplements:'Devis complémentaires pour cartes supplémentaires',consent:'J’accepte ce devis complémentaire et sa version des conditions. Aucun paiement ne sera effectué.',accept:'Accepter le devis complémentaire',paymentUnavailable:'Paiement indisponible pour cette commande',error:'Impossible de charger ou enregistrer les informations commerciales. Rechargez avant de réessayer.',shipping:'Retour supplémentaire',tax:'Taxes applicables',total:'Montant payable',received:'Réception enregistrée',refresh:'Actualiser'},
 EN:{operatorReview:'Payment pending — SELBY verification required. You can refresh or contact SELBY.',refunded:'Fully refunded — review required',partially_refunded:'Partially refunded — review required',commercial_hold:'Commercial hold',dispute_review:'Dispute review required',financial_review:'Financial review required',creating:'Creating payment',pending:'Payment verification pending',action_required:'Action required — resume Checkout',failed:'Attempt failed — retry Checkout',cancelled:'Attempt cancelled',expired:'Session expired — retry',restricted:'Payment restricted — contact SELBY',title:'Payment and dispatch',quote_not_accepted:'Quote not accepted',awaiting_payment:'Quote accepted · payment pending',verified:'Payment verified',awaiting_verified_payment:'Awaiting verified payment',awaiting_customer_dispatch:'Awaiting customer dispatch',customer_shipment_declared:'Customer shipment declared',dispatch_deadline_approaching:'Dispatch deadline approaching',dispatch_deadline_passed:'Dispatch deadline passed',parcel_received:'Parcel received · reconciliation is separate',manual_review_required:'Manual review required',deadline:'Dispatch deadline',expectation:'The 30 days begin after verified payment. A late dispatch does not trigger automatic cancellation, forfeiture or refund.',declaration:'Declare a shipment',declaredDate:'Customer-declared dispatch date (optional)',carrier:'Carrier (optional)',tracking:'Tracking (optional)',save:'Save declaration',unverified:'Customer declaration only: it is not verified carrier acceptance or physical receipt.',supplements:'Supplementary quotes for additional cards',consent:'I accept this supplementary quote and its terms version. No payment will be taken.',accept:'Accept supplementary quote',paymentUnavailable:'Payment unavailable · TEST configuration required',error:'Unable to load or save commercial information. Refresh before trying again.',shipping:'Additional return shipping',tax:'Applicable taxes',total:'Amount payable',received:'Receipt recorded',refresh:'Refresh'},
} as const;

export function checkoutInput(quoteId:string) { return {quote_id:quoteId}; }

// Review is presentation only. A later verified/restricted state takes precedence.
export function needsPaymentReview(state:{payment_status:string;payment_review_required?:boolean}):boolean {
 return state.payment_status==='action_required'&&state.payment_review_required===true;
}
export function canStartCheckout(state:{payment_status:string;payment_review_required?:boolean;charging_enabled?:boolean}):boolean {
 return Boolean(state.charging_enabled)&&!needsPaymentReview(state);
}
export function paymentStatusLabel(state:{payment_status:string;payment_review_required?:boolean},lang:'FR'|'EN'):string {
 return needsPaymentReview(state)?commercialMessages[lang].operatorReview:commercialMessages[lang][state.payment_status as keyof typeof commercialMessages.FR]??state.payment_status;
}
