export const QR_PREFIX = 'SP:PC:1:';
export const MAX_LABEL_BATCH = 250;
export type LabelProfile = '50x30' | '70x40';
export const labelCopy = {
  EN: { title:'Physical card labels', print:'Print label', reprint:'Reprint label', preview:'PDF preview', download:'Download PDF', open:'Open PDF / print', batch:'Prepare selected labels', reprintBatch:'Reprint selected labels', all:'Select all', clear:'Clear selection', selected:'Selected cards', profile:'Label profile', close:'Close preview', loading:'Preparing PDF…', error:'Could not prepare labels. Refresh and retry.', select:'Select label', empty:'Select at least one physical card.', limit:'Maximum 250 labels per batch. Reduce the selection.', calibration:'Calibration PDF', notice:'PDF preparation does not confirm physical printing. Print at actual size (100%), one page per label, with no scaling. Verify media and driver settings before printing.', unknown:'A selected card is missing or belongs to another submission. Refresh the inventory.', busy:'Label generation is busy. Retry shortly.', auth:'Your staff session is unavailable. Sign in again.', conflict:'Card relationships are inconsistent. Request an operational review.', unverified:'50 × 30 mm and 70 × 40 mm are layout profiles; printer/media compatibility requires a physical test.' },
  FR: { title:'Étiquettes des cartes physiques', print:'Imprimer l’étiquette', reprint:'Réimprimer l’étiquette', preview:'Aperçu PDF', download:'Télécharger le PDF', open:'Ouvrir le PDF / imprimer', batch:'Préparer les étiquettes sélectionnées', reprintBatch:'Réimprimer la sélection', all:'Tout sélectionner', clear:'Effacer la sélection', selected:'Cartes sélectionnées', profile:'Format d’étiquette', close:'Fermer l’aperçu', loading:'Préparation du PDF…', error:'Impossible de préparer les étiquettes. Actualisez et réessayez.', select:'Sélectionner l’étiquette', empty:'Sélectionnez au moins une carte physique.', limit:'250 étiquettes maximum par lot. Réduisez la sélection.', calibration:'PDF de calibration', notice:'La préparation du PDF ne confirme pas l’impression physique. Imprimez en taille réelle (100 %), une page par étiquette, sans mise à l’échelle. Vérifiez le support et le pilote avant impression.', unknown:'Une carte sélectionnée est absente ou appartient à une autre soumission. Actualisez l’inventaire.', busy:'La génération est occupée. Réessayez dans un instant.', auth:'Votre session du personnel est indisponible. Reconnectez-vous.', conflict:'Les relations de la carte sont incohérentes. Demandez une vérification opérationnelle.', unverified:'50 × 30 mm et 70 × 40 mm sont des formats de mise en page ; leur compatibilité avec l’imprimante et le support doit être testée physiquement.' },
};
export function canonicalScan(value: string) {
  let text = value.replace(/^[ \r\n\t]+|[ \r\n\t]+$/g, '').toUpperCase();
  if (text.startsWith(QR_PREFIX)) text = text.slice(QR_PREFIX.length);
  if (!/^PC-[0-9A-F]{32}$/.test(text)) throw new Error('invalid_card_reference');
  return text;
}
export function labelReferences(values: string[]) {
  if (!values.length) throw new Error('empty_selection');
  if (values.length > MAX_LABEL_BATCH) throw new Error('batch_limit');
  return [...new Set(values.map(value => canonicalScan(value)))].sort();
}
export function labelError(error: unknown, language: 'FR'|'EN') {
  const t=labelCopy[language];
  return ({empty_selection:t.empty,batch_limit:t.limit,invalid_input:t.limit,card_not_found:t.unknown,card_not_in_submission:t.unknown,labels_busy:t.busy,authentication_required:t.auth,staff_required:t.auth,trace_inconsistent:t.conflict} as Record<string,string>)[error instanceof Error?error.message:''] ?? t.error;
}
export async function labelPdf(path: string, payload?: { references:string[]; profile:LabelProfile }, request:typeof fetch=fetch) {
  const headers:Record<string,string>={};
  if (payload) {
    const csrf=await request('/api/auth/csrf',{cache:'no-store'});
    if(!csrf.ok) throw new Error('authentication_required');
    headers['Content-Type']='application/json'; headers['X-Spectra-Client']='1'; headers['X-CSRF-Token']=(await csrf.json()).csrf_token;
  }
  const response=await request('/internal/labels'+path,{method:payload?'POST':'GET',headers,body:payload?JSON.stringify(payload):undefined,cache:'no-store'});
  if(!response.ok) { const data=await response.json(); throw new Error(typeof data.detail==='string'?data.detail:'label_error'); }
  if(!(response.headers.get('Content-Type')??'').includes('application/pdf')) throw new Error('label_error');
  return response.blob();
}
