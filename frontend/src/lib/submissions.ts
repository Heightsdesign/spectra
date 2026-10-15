import type { Language } from './i18n.ts';
export const submissionMessages = {
 FR: { title:'Mes soumissions', new:'Nouvelle soumission', empty:'Aucune soumission.', draft:'Brouillon', submitted:'Confirmée', cards:'Cartes', created:'Création', game:'Jeu', card_name:'Nom de la carte', expansion:'Extension', card_number:'Numéro', language:'Langue', quantity:'Quantité', notes:'Notes (facultatif)', add:'Enregistrer la carte', edit:'Modifier', remove:'Supprimer', save:'Enregistrer les notes', saved:'Progression enregistrée.', review:'Vérifier la soumission', confirm:'Confirmer la soumission', warning:'Vérifiez toutes les cartes. Après confirmation, la soumission ne pourra plus être modifiée.', back:'Retour au compte', cancel:'Annuler / retour', loading:'Chargement…', unavailable:'Impossible de charger ou enregistrer la soumission. Réessayez.', submission_conflict:'Cette soumission a changé. Rechargez-la avant de réessayer.', submission_immutable:'Cette soumission est confirmée.', submission_empty:'Ajoutez au moins une carte.', invalid_input:'Vérifiez les champs.', authentication_required:'Votre session a expiré. Reconnectez-vous.', csrf_failed:'Rechargez la page et réessayez.', submission_not_found:'Soumission introuvable.', entry_limit:'Maximum de 100 entrées.', reload:'Recharger', more:'Afficher la suite' },
 EN: { title:'My submissions', new:'New submission', empty:'No submissions yet.', draft:'Draft', submitted:'Submitted', cards:'Cards', created:'Created', game:'Game', card_name:'Card name', expansion:'Set / expansion', card_number:'Card number', language:'Language', quantity:'Quantity', notes:'Notes (optional)', add:'Save card', edit:'Edit', remove:'Remove', save:'Save notes', saved:'Progress saved.', review:'Review submission', confirm:'Confirm submission', warning:'Review every card. After confirmation, this submission cannot be edited.', back:'Back to account', cancel:'Cancel / back', loading:'Loading…', unavailable:'Unable to load or save the submission. Please retry.', submission_conflict:'This submission has changed. Reload it before trying again.', submission_immutable:'This submission is confirmed.', submission_empty:'Add at least one card.', invalid_input:'Check the fields.', authentication_required:'Your session expired. Please sign in again.', csrf_failed:'Reload this page and try again.', submission_not_found:'Submission not found.', entry_limit:'Maximum of 100 entries.', reload:'Reload', more:'Show more' },
} as const satisfies Record<Language, Record<string,string>>;
export const games = { pokemon:'Pokémon', 'one-piece':'One Piece', 'dragon-ball':'Dragon Ball', naruto:'Naruto' };
export type Entry = { id:string; game:string; card_name:string; expansion:string; card_number:string; language:string; quantity:number; notes:string; processing_tier:string; upgrade_ids:string[] };
export type Submission = { id:string; reference:string; status:'draft'|'submitted'; notes:string; version:number; created_at:string; updated_at:string; confirmed_at:string|null; card_count:number; entries:Entry[] };
export async function submissionRequest<T = Submission | Submission[]>(path:string, method='GET', payload?:object, request:typeof fetch=fetch, base="/api/submissions"):Promise<T> {
 const headers:Record<string,string> = {'Content-Type':'application/json','X-Spectra-Client':'1'};
 if(method !== 'GET') {
  const csrf = await request('/api/auth/csrf', {cache:'no-store'});
  if(!csrf.ok) throw new Error(csrf.status === 401 ? 'authentication_required' : 'unavailable');
  headers['X-CSRF-Token'] = (await csrf.json()).csrf_token;
 }
 const response=await request(`${base}${path}`,{method,headers,body:payload ? JSON.stringify(payload):undefined,cache:'no-store'});
 const result=await response.json();
 if(!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail:'invalid_input');
 return result;
}
