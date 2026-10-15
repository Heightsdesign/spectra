import type { Order } from './checkout';
import type { Language } from './i18n.ts';

export type Localized = Record<Language, string>;
export type Tier = { name:Localized; description:Localized; price_adjustment_minor:number; estimated_turnaround:Localized|null; available:boolean; display_order:number };
export type Upgrade = { name:Localized; description:Localized; price_minor:number; group:string; available:boolean; display_order:number; incompatible_with:string[]; allowed_tiers:string[]|null };
export type Catalog = { version:string; name:string; currency:'EUR'; development_only:boolean; base_price_minor:number; tiers:Record<string,Tier>; upgrades:Record<string,Upgrade>; groups:Record<string,{min_selected:number;max_selected:number}>; discount_scope:'base'|'all'; tax_mode:'exclusive'|'inclusive'|'exempt'; tax_rate_bps:number; tax_description:Localized };
export type PriceLine = { entry_id:string; card_name:string; quantity:number; processing_tier:string; tier_name:Localized; estimated_turnaround:Localized|null; base_unit_minor:number; speed_unit_minor:number; upgrades:{id:string;name:Localized;description:Localized;unit_minor:number}[]; unit_minor:number; subtotal_minor:number; discount_minor:number; net_minor:number; tax_minor:number; total_minor:number };
export type Quote = { id:string; status:'valid'|'expired'|'invalidated'|'catalog_changed'|'accepted'|'superseded'|'unavailable'; pricing_configuration_version:string; created_at:string; expires_at:string; accepted_at:string|null; snapshot:{ checkout?:Order; volume_bracket?:{id:string;min_quantity:number;unit_price_minor:number}|null; currency:'EUR'; development_only:boolean; quantity:number; lines:PriceLine[]; subtotal_minor:number; discount_minor:number; net_minor:number; tax_minor:number; total_minor:number; discount:{id:string;min_quantity:number;rate_bps:number}|null; discount_scope:'base'|'all'; tax_mode:'exclusive'|'inclusive'|'exempt'; tax_rate_bps:number; tax_description:Localized } };

// Formatting only. All calculation and rounding happens on the server in minor units.
export function money(minor:number, lang:Language, currency='EUR') {
 return new Intl.NumberFormat(lang==='FR'?'fr-FR':'en-GB',{style:'currency',currency}).format(minor/100);
}
export function ordered<T extends {display_order:number}>(options:Record<string,T>):[string,T][] {
 return Object.entries(options).sort(([a,x],[b,y])=>x.display_order-y.display_order||a.localeCompare(b));
}
export function compatible(catalog:Catalog,tier:string,ids:string[]):boolean {
 if(!catalog.tiers[tier]?.available || new Set(ids).size!==ids.length)return false;
 const counts:Record<string,number>={};
 for(const id of ids){const u=catalog.upgrades[id];if(!u?.available || (u.allowed_tiers&&!u.allowed_tiers.includes(tier)) || (u.incompatible_with??[]).some(i=>ids.includes(i)))return false;counts[u.group]=(counts[u.group]??0)+1;}
 return Object.entries(catalog.groups).every(([key,g])=>(counts[key]??0)>=g.min_selected&&(counts[key]??0)<=g.max_selected);
}
export const pricingMessages = {
 FR: {
  quantityConfiguration:'La configuration s’applique à toutes les cartes de cette entrée. Pour des options différentes, créez des entrées séparées.',
  title:'Services et devis', speed:'Vitesse de traitement', label:'Étiquette du slab', extras:'Options supplémentaires', applyAll:'Appliquer à toutes les cartes', save:'Enregistrer la configuration', configurationSaved:'Configuration enregistrée. Le devis doit être recalculé.',
  example:'Tarifs de développement uniquement — exemples sans valeur commerciale.', payment:'Le paiement n’est pas encore disponible.', independent:'La confirmation de la soumission fige les cartes. Elle ne vaut ni acceptation du devis ni paiement.',
  generate:'Générer / recalculer le devis', review:'Vérifier le devis', noQuote:'Aucun devis enregistré.', base:'Prix de base par carte', speedCharge:'Supplément de traitement par carte', upgradeCharge:'Option par carte', unit:'Prix unitaire', quantity:'Cartes physiques', subtotal:'Sous-total avant remise', discount:'Remise', net:'Total hors taxes', tax:'Taxes', total:'Sous-total grading (hors retour)',
  scopeBase:'Remise appliquée au prix de base.', scopeAll:'Remise appliquée à tous les frais.', discountRule:'Seuil de remise', cards:'cartes', inclusive:'Taxes comprises', exclusive:'Taxes ajoutées', exempt:'Aucune taxe appliquée',
  created:'Créé le', expires:'Expire le', version:'Version tarifaire', turnaround:'Délai estimé', included:'Inclus', unavailableOption:'Indisponible', loading:'Chargement des services…', refresh:'Actualiser les services et le devis',
  consent:'J’accepte les termes et le montant de ce devis. Aucun paiement ne sera effectué.', accept:'Accepter ce devis', acceptedAt:'Termes acceptés le', confirmFirst:'Confirmez la soumission pour pouvoir accepter un devis commercial.',
  valid:'Devis en cours de validité', expired:'Devis expiré — veuillez le recalculer.', invalidated:'La soumission a changé — veuillez recalculer le devis.', catalog_changed:'Les tarifs ont changé — veuillez recalculer le devis.', accepted:'Termes commerciaux acceptés', superseded:'Devis remplacé par les termes acceptés', unavailable:'Devis indisponible',
  pricing_unavailable:'Les services et les tarifs ne sont pas encore configurés. Vous pouvez conserver votre brouillon.', option_unavailable:'Cette option est indisponible. Actualisez les services.', options_incompatible:'Cette combinaison d’options est incompatible.', quote_stale:'Ce devis n’est plus valable. Actualisez et recalculez-le.', example_terms_not_acceptable:'Les exemples de développement ne peuvent pas être acceptés commercialement.', terms_already_accepted:'Les termes de cette soumission ont déjà été acceptés.', confirm_before_acceptance:'Confirmez d’abord la soumission.', submission_conflict:'La soumission a changé. Rechargez la page.', submission_immutable:'Cette soumission est confirmée et ne peut plus être modifiée.', invalid_input:'Vérifiez les options sélectionnées.', authentication_required:'Votre session a expiré. Reconnectez-vous.', csrf_failed:'Rechargez la page et réessayez.', serviceError:'Impossible de charger ou enregistrer le devis. Réessayez.', unsaved:'Enregistrez les changements avant de générer ou accepter un devis.'
 },
 EN: {
  quantityConfiguration:'The configuration applies to every physical card in this entry. Create separate entries for different options.',
  title:'Services and quotes', speed:'Processing speed', label:'Slab label', extras:'Additional options', applyAll:'Apply to all cards', save:'Save configuration', configurationSaved:'Configuration saved. Recalculate the quote.',
  example:'Development rates only — examples without commercial validity.', payment:'Payment is not available yet.', independent:'Submission confirmation freezes the cards. It does not accept a quote or make a payment.',
  generate:'Generate / recalculate quote', review:'Review quote', noQuote:'No saved quote yet.', base:'Base price per card', speedCharge:'Speed surcharge per card', upgradeCharge:'Upgrade per card', unit:'Unit price', quantity:'Physical cards', subtotal:'Subtotal before discount', discount:'Discount', net:'Total excluding tax', tax:'Tax', total:'Grading subtotal (excluding return shipping)',
  scopeBase:'Discount applies to the base grading price.', scopeAll:'Discount applies to all charges.', discountRule:'Discount threshold', cards:'cards', inclusive:'Tax included', exclusive:'Tax added', exempt:'No tax applied',
  created:'Created', expires:'Expires', version:'Pricing version', turnaround:'Estimated turnaround', included:'Included', unavailableOption:'Unavailable', loading:'Loading services…', refresh:'Refresh services and quote',
  consent:'I accept the terms and amount of this quote. No payment will be taken.', accept:'Accept this quote', acceptedAt:'Terms accepted', confirmFirst:'Confirm the submission before accepting a commercial quote.',
  valid:'Quote is valid', expired:'Quote expired — please recalculate.', invalidated:'Submission changed — please recalculate.', catalog_changed:'Prices changed — please recalculate.', accepted:'Commercial terms accepted', superseded:'Quote superseded by accepted terms', unavailable:'Quote unavailable',
  pricing_unavailable:'Services and rates are not configured yet. You can keep your draft.', option_unavailable:'This option is unavailable. Refresh services.', options_incompatible:'These options are incompatible.', quote_stale:'This quote is no longer valid. Refresh and recalculate.', example_terms_not_acceptable:'Development examples cannot be accepted commercially.', terms_already_accepted:'Terms for this submission have already been accepted.', confirm_before_acceptance:'Confirm the submission first.', submission_conflict:'The submission changed. Reload the page.', submission_immutable:'This submission is confirmed and cannot be edited.', invalid_input:'Check the selected options.', authentication_required:'Your session expired. Please sign in again.', csrf_failed:'Reload the page and try again.', serviceError:'Unable to load or save the quote. Please retry.', unsaved:'Save changes before generating or accepting a quote.'
 }
} as const;
