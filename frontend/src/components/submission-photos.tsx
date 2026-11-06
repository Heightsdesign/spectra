"use client";
/* eslint-disable @next/next/no-img-element -- private originals and local blob previews must bypass the shared image optimizer. */
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { Language } from '@/lib/i18n';
import { submissionRequest, type Entry, type Submission } from '@/lib/submissions';
import { photoData, photoFileError, photoPath, uploadPhoto } from '@/lib/submission-photos';

const messages={
 FR:{title:'Photos client avant envoi (facultatives)',hint:'Ces photos ne sont pas des preuves d’inspection SELBY et ne vérifient pas l’identité de la carte. Enregistrez chaque copie séparément ci-dessous.',copy:'Copie déclarée',front:'Recto',back:'Verso',choose:'Choisir un fichier',camera:'Prendre une photo',upload:'Enregistrer la photo',remove:'Retirer la photo',pending:'Aperçu local — photo non enregistrée.',progress:'Envoi',processing:'Validation et enregistrement…',error:'Envoi non confirmé. Rechargez pour vérifier, réessayez ou continuez sans photo.',limits:'JPEG ou PNG, 8 Mo maximum, 20 mégapixels maximum.',saved:'Photo enregistrée.',unavailable:'Aperçu indisponible. La déclaration reste utilisable.'},
 EN:{title:'Customer pre-shipment photos (optional)',hint:'These are not SELBY inspection evidence and do not verify card identity. Attach each declared copy separately below.',copy:'Declared copy',front:'Front',back:'Back',choose:'Choose a file',camera:'Take a photo',upload:'Save photo',remove:'Remove photo',pending:'Local preview — photo not saved.',progress:'Uploading',processing:'Validating and saving…',error:'Upload could not be confirmed. Reload to check, retry, or continue without photos.',limits:'JPEG or PNG, maximum 8 MiB and 20 megapixels.',saved:'Photo saved.',unavailable:'Preview unavailable. The declaration remains usable.'},
};

function PhotoSlot({item,entry,copy,side,lang,disabled,onBusy,onSaved,onPending}:{item:Submission;entry:Entry;copy:number;side:'front'|'back';lang:Language;disabled:boolean;onBusy:(value:boolean)=>void;onSaved:(item:Submission)=>void;onPending?:(key:string,pending:boolean)=>void}) {
 const t=messages[lang];const id=useId();
 const [file,setFile]=useState<File|null>(null);const [preview,setPreview]=useState('');
 const [busy,setBusy]=useState(false);const [progress,setProgress]=useState(0);const [notice,setNotice]=useState('');const [imageFailed,setImageFailed]=useState(false);
 const uploadAbort=useRef<AbortController|null>(null);
 const [canCancel,setCanCancel]=useState(false);
 const photo=entry.pre_shipment_photos?.find(p=>p.copy_number===copy&&p.side===side);
 useEffect(()=>{const key=`${entry.id}:${copy}:${side}`;onPending?.(key,!!file);return()=>onPending?.(key,false);},[entry.id,copy,side,file,onPending]);
 useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview);},[preview]);
 function choose(candidate:File|undefined){if(!candidate)return;const error=photoFileError(candidate);setNotice(error?t.error+' '+t.limits:t.pending);if(error){setFile(null);setPreview('');}else{setFile(candidate);setPreview(URL.createObjectURL(candidate));setImageFailed(false);}}
 async function save(remove=false){
  if(busy)return;setBusy(true);onBusy(true);setNotice('');setProgress(0);
  const controller=new AbortController();uploadAbort.current=controller;setCanCancel(!remove);
  try{
   const result=remove&&photo?await submissionRequest<Submission>(photoPath(item.id,entry.id,photo.id),'DELETE',{version:item.version},fetch,'')
    :file?await uploadPhoto(photoPath(item.id,entry.id),{version:item.version,copy_number:copy,side,filename:file.name,data:await photoData(file)},setProgress,controller.signal):null;
   if(result){setFile(null);setPreview('');setImageFailed(false);setNotice(remove?(lang==='FR'?'Photo retirée.':'Photo removed.'):t.saved);onSaved(result);}
  }catch{setNotice(t.error);}finally{setBusy(false);setCanCancel(false);uploadAbort.current=null;onBusy(false);}
 }
 const source=item.status==='draft'&&file?preview:photo?photoPath(item.id,entry.id,photo.id):'';
 return <div><fieldset className="submission-photo-slot" disabled={disabled||busy}><legend>{t[side]}</legend>
  {source&&!imageFailed&&<img src={source} alt={`${t.title} — ${t.copy} ${copy} — ${t[side]}`} onError={()=>setImageFailed(true)}/>}
  {imageFailed&&<p role="status">{t.unavailable}</p>}
  {photo&&<p>{new Date(photo.uploaded_at).toLocaleString(lang==='FR'?'fr-FR':'en-GB')} · {photo.original_filename}</p>}
  {item.status==='draft'&&<><label htmlFor={`${id}-file`}>{t.choose}<input id={`${id}-file`} type="file" accept="image/jpeg,image/png" onChange={e=>{choose(e.target.files?.[0]);e.target.value='';}}/></label>
   <label htmlFor={`${id}-camera`}>{t.camera}<input id={`${id}-camera`} type="file" accept="image/jpeg,image/png" capture="environment" onChange={e=>{choose(e.target.files?.[0]);e.target.value='';}}/></label>
   {file&&<><p>{t.pending}</p><button type="button" onClick={()=>void save()}>{t.upload}</button><button type="button" onClick={()=>{setFile(null);setPreview('');setNotice('');}}>{lang==='FR'?'Annuler la sélection':'Cancel selection'}</button></>}
   {photo&&<button type="button" onClick={()=>void save(true)}>{t.remove}</button>}
  </>}
  {busy&&<p role="status">{progress<100?`${t.progress}: ${progress}%`:t.processing}<progress max={100} value={progress}/></p>}
  {notice&&item.status==='draft'&&<p role="status">{notice}</p>}
 </fieldset>{busy&&canCancel&&<button type="button" onClick={()=>uploadAbort.current?.abort()}>{lang==='FR'?'Annuler l’envoi':'Cancel upload'}</button>}</div>;
}

export function SubmissionPhotos({item,entry,lang,disabled,onBusy,onSaved,readOnly=false,onPending}:{item:Submission;entry:Entry;lang:Language;disabled:boolean;onBusy:(value:boolean)=>void;onSaved:(item:Submission)=>void;readOnly?:boolean;onPending?:(key:string,pending:boolean)=>void}) {
 const [copy,setCopy]=useState(1);const t=messages[lang];
 const [pending,setPending]=useState<Set<string>>(()=>new Set());
 const report=useCallback((key:string,value:boolean)=>{setPending(previous=>{if(previous.has(key)===value)return previous;const next=new Set(previous);if(value)next.add(key);else next.delete(key);return next;});onPending?.(key,value);},[onPending]);
 const view=readOnly?{...item,status:'submitted' as const}:item;
 return <details className="submission-photos"><summary>{t.title} · {entry.pre_shipment_photos?.length??0}</summary><p>{t.hint}</p><p>{t.limits}</p>
  <label>{t.copy}<select value={copy} disabled={disabled||pending.size>0} onChange={e=>setCopy(Number(e.target.value))}>{Array.from({length:entry.quantity},(_,i)=><option key={i} value={i+1}>{i+1} / {entry.quantity}</option>)}</select></label>
  <div className="form-pair">{(['front','back'] as const).map(side=><PhotoSlot key={`${copy}-${side}`} item={view} entry={entry} copy={copy} side={side} lang={lang} disabled={disabled} onBusy={onBusy} onSaved={onSaved} onPending={report}/>)}</div>
 </details>;
}
