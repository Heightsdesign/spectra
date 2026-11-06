"use client";
import { useEffect, useState, type FormEvent } from 'react';
import type { Language } from '@/lib/i18n';
import { checkoutMessages } from '@/lib/checkout';
import { submissionRequest } from '@/lib/submissions';

type Preparation={version:number;parcel:Record<string,number|null>;terms_accepted:boolean};
const fields=['weight_g','length_mm','width_mm','height_mm'] as const;
export function ReturnParcelPanel({submissionId,lang,disabled}:{submissionId:string;lang:Language;disabled:boolean}) {
 const t=checkoutMessages[lang];const fr=lang==='FR';
 const [record,setRecord]=useState<Preparation|null>(null);const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');const [reload,setReload]=useState(0);
 const path=`/internal/intake/submissions/${encodeURIComponent(submissionId)}/return-parcel`;
 useEffect(()=>{let active=true;submissionRequest<Preparation>(path,'GET',undefined,fetch,'').then(value=>{
  if(!Number.isInteger(value.version)||!value.parcel)throw Error();if(active){setRecord(value);setNotice('');}
 }).catch(()=>{if(active)setNotice(t.error);});return()=>{active=false;};},[path,reload,t.error]);
 async function save(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(!record||busy)return;const data=new FormData(event.currentTarget);
  setBusy(true);setNotice('');
  try{setRecord(await submissionRequest<Preparation>(path,'PUT',{version:record.version,parcel:Object.fromEntries(fields.map(field=>[field,data.get(field)?Number(data.get(field)):null])),reason:data.get('reason')},fetch,''));setNotice(fr?'Enregistré. Les devis précédents doivent être actualisés.':'Saved. Previous quotes must be refreshed.');}
  catch{setNotice(t.error);}finally{setBusy(false);}
 }
 return <section className="intake-section return-parcel-panel"><h2>{fr?'Préparation du colis de retour — équipe':'Return parcel preparation — staff'}</h2>
  <p>{fr?'Renseignez ici le poids et les dimensions du colis lorsque disponibles. Ce relevé ne vaut pas autorisation d’expédition. Les termes commerciaux acceptés figent cette préparation.':'Record parcel weight and dimensions here when available. This does not authorize dispatch. Accepted commercial terms lock this preparation record.'}</p>
  {notice&&<p role="status">{notice}</p>}
  <button type="button" className="button button-outline" disabled={busy||disabled} onClick={()=>setReload(n=>n+1)}>{t.reload}</button>
  {record&&<form key={record.version} onSubmit={event=>void save(event)}><fieldset disabled={busy||disabled||record.terms_accepted}>
   <div className="intake-fields">{fields.map(field=><label className="intake-field" key={field}>{t[field]}<input name={field} type="number" min={1} max={field==='weight_g'?100000:5000} defaultValue={record.parcel[field]??''}/></label>)}</div>
   <label>{fr?'Motif du relevé':'Reason for recording'}<input name="reason" required maxLength={200}/></label>
   <button className="button button-outline">{t.save}</button>
  </fieldset>{record.terms_accepted&&<p>{fr?'Termes acceptés : préparation figée.':'Accepted terms: preparation is locked.'}</p>}</form>}
 </section>;
}
