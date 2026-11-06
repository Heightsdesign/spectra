"use client";
/* eslint-disable @next/next/no-img-element -- private originals and local blob previews must not enter the public image optimizer. */
import {useEffect,useState,type FormEvent} from 'react';
import Link from 'next/link';
import {CatalogFields} from './catalog-fields';
import {libraryRequest,libraryMessages,copyAsEntry,type LibraryCopy,type CopyPage} from '@/lib/library';
import {submissionMessages} from '@/lib/submissions';
import {photoData,photoFileError,uploadPhoto} from '@/lib/submission-photos';
import type {Language} from '@/lib/i18n';

function LibraryPhotos({copy,lang,onSaved}:{copy:LibraryCopy;lang:Language;onSaved:(copy:LibraryCopy)=>void}){
 const t=libraryMessages[lang];const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');const [progress,setProgress]=useState(0);
 const [file,setFile]=useState<{side:'front'|'back';file:File}|null>(null);const [preview,setPreview]=useState('');
 useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview);},[preview]);
 function choose(side:'front'|'back',candidate?:File){if(!candidate)return;if(photoFileError(candidate)){setNotice(lang==='FR'?'JPEG/PNG, 8 Mio maximum.':'JPEG/PNG, maximum 8 MiB.');return;}setFile({side,file:candidate});setPreview(URL.createObjectURL(candidate));setNotice('');}
 async function save(removeId?:string){if(busy)return;setBusy(true);setNotice('');setProgress(0);try{
  const base=`/copies/${copy.id}/photos`;
  const result=removeId?await libraryRequest<LibraryCopy>(`${base}/${removeId}`,'DELETE',{version:copy.version})
   :file?await uploadPhoto<LibraryCopy>(`/api/library${base}`,{version:copy.version,copy_number:1,side:file.side,filename:file.file.name,data:await photoData(file.file)},setProgress):null;
  if(result){onSaved(result);setFile(null);setPreview('');}
 }catch{setNotice(t.error);}finally{setBusy(false);}}
 return <details><summary>{t.photos} · {copy.pre_shipment_photos.length}</summary><p>{t.hint}</p><fieldset disabled={busy||!copy.available}><legend>{t.photos}</legend>
  <div className="form-pair">{(['front','back'] as const).map(side=>{const photo=copy.pre_shipment_photos.find(p=>p.side===side);return <div key={side}><h4>{side==='front'?(lang==='FR'?'Recto':'Front'):(lang==='FR'?'Verso':'Back')}</h4>
   {photo&&<><img width={180} src={`/api/library/copies/${copy.id}/photos/${photo.id}`} alt={`${t.photos} ${side}`}/><button type="button" onClick={()=>void save(photo.id)}>{t.removePhoto}</button></>}
   <label>{t.upload}<input type="file" accept="image/jpeg,image/png" onChange={e=>{choose(side,e.target.files?.[0]);e.target.value='';}}/></label>
   <label>{t.camera}<input type="file" accept="image/jpeg,image/png" capture="environment" onChange={e=>{choose(side,e.target.files?.[0]);e.target.value='';}}/></label>
  </div>;})}</div>
  {file&&<><img width={180} src={preview} alt={t.photos}/><button type="button" onClick={()=>void save()}>{t.upload}</button><button type="button" onClick={()=>{setFile(null);setPreview('');}}>{t.cancel}</button></>}
 </fieldset>{busy&&<progress max={100} value={progress}/>}<p role="status">{notice}</p></details>;
}

export function CardLibrary({lang,onChoose,disabled=false,refreshKey=0}:{lang:Language;onChoose?:(copy:LibraryCopy)=>void;disabled?:boolean;refreshKey?:number}){
 const t=libraryMessages[lang];const s=submissionMessages[lang];const [items,setItems]=useState<LibraryCopy[]>([]);const [more,setMore]=useState(false);
 const [search,setSearch]=useState('');const [query,setQuery]=useState('');const [reload,setReload]=useState(0);const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(true);const [notice,setNotice]=useState('');const [editing,setEditing]=useState<LibraryCopy|null>(null);const [form,setForm]=useState(false);
 useEffect(()=>{let active=true;libraryRequest<CopyPage>(`/copies?search=${encodeURIComponent(query)}&limit=25`).then(page=>{if(active){setItems(page.items);setMore(page.has_more);setNotice('');}}).catch(()=>{if(active)setNotice(t.error);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[query,reload,refreshKey,t.error]);
 async function moreRows(){setBusy(true);try{const page=await libraryRequest<CopyPage>(`/copies?search=${encodeURIComponent(query)}&offset=${items.length}&limit=25`);setItems([...items,...page.items]);setMore(page.has_more);}catch{setNotice(t.error);}finally{setBusy(false);}}
 async function save(event:FormEvent<HTMLFormElement>){event.preventDefault();if(busy)return;const values=Object.fromEntries(new FormData(event.currentTarget));setBusy(true);try{
  await libraryRequest<LibraryCopy>(`/copies${editing?`/${editing.id}`:''}`,editing?'PUT':'POST',{...values,catalog_card_id:values.catalog_card_id||null,...(editing?{version:editing.version}:{})});setEditing(null);setForm(false);setLoading(true);setReload(r=>r+1);setNotice(t.saved);
 }catch{setNotice(t.error);}finally{setBusy(false);}}
 const update=(copy:LibraryCopy)=>setItems(list=>list.map(item=>item.id===copy.id?copy:item));
 return <section className="submissions card-library" aria-label={t.title}><h2>{onChoose?t.choose:t.title}</h2><p>{t.hint}</p>
  <form onSubmit={e=>{e.preventDefault();setLoading(true);setQuery(search);setReload(r=>r+1);}}><label>{t.search}<input value={search} maxLength={200} onChange={e=>setSearch(e.target.value)}/></label><button className="button button-outline" disabled={busy||loading}>{s.reload}</button></form>
  {!onChoose&&<button className="button button-dark" disabled={busy||disabled} onClick={()=>{setForm(true);setEditing(null);}}>{t.new}</button>}
  {form&&!onChoose&&<form key={editing?.id??'new'} onSubmit={save}><fieldset disabled={busy||disabled}><legend>{editing?t.edit:t.new}</legend><CatalogFields entry={editing?copyAsEntry(editing):null} lang={lang} onDirty={()=>undefined}/><label>{s.cardNotes}<textarea name="notes" maxLength={2000} defaultValue={editing?.notes??''}/></label><button className="button button-dark">{t.new}</button><button type="button" onClick={()=>setForm(false)}>{t.cancel}</button></fieldset></form>}
  {loading&&<p role="status">{s.loading}</p>}{notice&&<p role="status">{notice}</p>}{!loading&&!items.length&&<p>{t.empty}</p>}
  <div className="submission-list">{items.map(copy=><article className="info-card" key={copy.id}><h3>{copy.card_name}</h3><p>{copy.expansion} · {copy.card_number} · {copy.language}</p><p>{t.copy}: {copy.reference}</p><p>{copy.available?t.available:t.unavailable}</p>
   {copy.active_submission_id&&<Link className="text-link" href={`/account/submissions/${copy.active_submission_id}`}>{t.order}</Link>}
   {onChoose?<button className="button button-outline" disabled={disabled||busy||!copy.available} onClick={()=>onChoose(copy)}>{t.select}</button>:<><button className="button button-outline" disabled={busy||!copy.available} onClick={()=>{setEditing(copy);setForm(true);}}>{t.edit}</button><LibraryPhotos copy={copy} lang={lang} onSaved={update}/></>}
  </article>)}</div>{more&&<button className="button button-outline" disabled={busy||loading} onClick={()=>void moreRows()}>{s.more}</button>}
 </section>;
}
