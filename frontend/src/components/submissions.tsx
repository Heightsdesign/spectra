"use client";
import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { submissionMessages, submissionRequest, games, type Submission, type Entry } from '@/lib/submissions';
import type { Language } from '@/lib/i18n';
import { Container } from './ui';
import { CheckoutPanel } from './checkout-panel';
import { EntryServiceFields, PricingPanel } from './pricing-panel';
import { pricingMessages } from '@/lib/pricing';
export function Submissions({ lang, identifier }: {lang:Language; identifier?:string}) {
 const t=submissionMessages[lang];
 const [deliveryRefresh,setDeliveryRefresh]=useState(0);
 const [deliveryDirty,setDeliveryDirty]=useState(false);
 const router=useRouter();
 const [items,setItems]=useState<Submission[]>([]);
 const [item,setItem]=useState<Submission|null>(null);
 const [busy,setBusy]=useState(false);
 const [loaded,setLoaded]=useState(false);
 const [notice,setNotice]=useState('');
 const [editing,setEditing]=useState<Entry|null>(null);
 const [review,setReview]=useState(false);
 const [more,setMore]=useState(false);
 const [dirty,setDirty]=useState(false);
 const [notesDirty,setNotesDirty]=useState(false);
 const [pricingDirty,setPricingDirty]=useState(false);
 const [reload,setReload]=useState(0);
 function error(e:unknown) { const key=e instanceof Error ? e.message:'unavailable'; const pricing=pricingMessages[lang]; setNotice(key in t ? t[key as keyof typeof t]:key in pricing?pricing[key as keyof typeof pricing]:t.unavailable); }
 useEffect(()=>{
  let active=true;
  submissionRequest(identifier ? `/${identifier}`:'?limit=50').then(result=>{if(active){if(identifier)setItem(result as Submission);else {setItems(result as Submission[]);setMore((result as Submission[]).length===50);} setLoaded(true);}}).catch(e=>{if(active){error(e);setLoaded(true);}});
  return ()=>{active=false;};
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[identifier,reload]);
 async function run(path:string,method:string,payload:object) {
  if(busy)return;
  setBusy(true);setNotice('');
  try { const result=await submissionRequest(path,method,payload) as Submission; if(!identifier){router.push(`/account/submissions/${result.id}`);return;} setItem(result);setEditing(null);setDirty(false);setNotesDirty(false);setNotice(t.saved); }
  catch(e){error(e);} finally{setBusy(false);}
 }
 async function nextPage() {
  setBusy(true);setNotice('');
  try { const result=await submissionRequest(`?offset=${items.length}&limit=50`) as Submission[];setItems([...items,...result]);setMore(result.length===50); }catch(e){error(e);}finally{setBusy(false);}
 }
 function saveEntry(event:FormEvent<HTMLFormElement>) {
  event.preventDefault();if(!item)return;
  const data=new FormData(event.currentTarget);
  const values=Object.fromEntries(data);
  void run(`/${item.id}/entries${editing ? `/${editing.id}`:''}`,editing?'PUT':'POST',{...values,...(data.has('upgrade_ids')?{upgrade_ids:data.getAll('upgrade_ids')}:{}),quantity:Number(values.quantity),version:item.version});
 }
 const status=(s:Submission)=>s.status==='draft'?t.draft:t.submitted;
 return <div lang={lang.toLowerCase()} className="submissions">
  <h2>{identifier ? item?.reference ?? t.title:t.title}</h2>
  {notice && <p role="status" className="auth-feedback">{notice}</p>}
  <button type="button" className="text-link" disabled={busy} onClick={()=>{setNotice('');setEditing(null);setDirty(false);setNotesDirty(false);setPricingDirty(false);setReview(false);setReload(reload+1);}}>{t.reload}</button>
  {!loaded && <p>{t.loading}</p>}
  {!identifier && <><button className="button button-dark" disabled={busy} onClick={()=>void run('','POST',{})}>{t.new}</button>{loaded && !items.length && <p>{t.empty}</p>}<div className="submission-list">{items.map(s=><article className="info-card" key={s.id}><h3><Link className="text-link" href={`/account/submissions/${s.id}`}>{s.reference}</Link></h3><p>{status(s)} · {t.cards}: {s.card_count}</p><p>{t.created}: {new Date(s.created_at).toLocaleDateString(lang==='FR'?'fr-FR':'en-GB')}</p></article>)}</div>{more && <button disabled={busy} className="button button-outline" onClick={()=>void nextPage()}>{t.more}</button>}</>}
  {item && <><p>{status(item)} · {t.cards}: {item.card_count} · {t.created}: {new Date(item.created_at).toLocaleDateString(lang==='FR'?'fr-FR':'en-GB')}</p>
   <div className="submission-list">{item.entries.map(entry=><article className="info-card" key={entry.id}><h3>{entry.card_name} × {entry.quantity}</h3><dl>{(['game','expansion','card_number','language','notes'] as const).map(key=><div key={key}><dt>{t[key]}</dt><dd>{key==='game' ? games[entry.game as keyof typeof games] ?? entry.game:entry[key] || '—'}</dd></div>)}</dl>{item.status==='draft' && !review && <div className="submission-actions"><button disabled={busy||dirty||notesDirty||pricingDirty} className="button button-outline" onClick={()=>{setEditing(entry);setDirty(true);}}>{t.edit}</button><button disabled={busy||dirty||notesDirty||pricingDirty} className="button button-outline" onClick={()=>void run(`/${item.id}/entries/${entry.id}`,'DELETE',{version:item.version})}>{t.remove}</button></div>}</article>)}</div>
   {item.status==='draft' && !review && <>
    <form key={`${editing?.id ?? 'new'}-${item.version}`} onSubmit={saveEntry} onChange={()=>setDirty(true)}><fieldset disabled={busy||notesDirty||pricingDirty}><legend>{editing?t.edit:t.add}</legend>
     <label>{t.game}<select name="game" defaultValue={editing?.game ?? 'pokemon'}>{Object.entries(games).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
     <div className="form-pair">{(['card_name','expansion','card_number','language'] as const).map(key=><label key={key}>{t[key]}<input name={key} required maxLength={key==='card_name'||key==='expansion'?200:64} defaultValue={editing?.[key] ?? ''}/></label>)}</div>
     <label>{t.quantity}<input name="quantity" type="number" required min={1} max={100} defaultValue={editing?.quantity ?? 1}/></label>
     <label>{t.notes}<textarea name="notes" maxLength={2000} defaultValue={editing?.notes ?? ''}/></label>
     <EntryServiceFields key={`${editing?.id ?? 'new'}-${item.version}`} entry={editing??undefined} lang={lang}/>
     <button className="button button-dark" disabled={busy}>{t.add}</button>{dirty && <button type="button" className="button button-outline" onClick={()=>{setEditing(null);setDirty(false);setReload(reload+1);}}>{t.cancel}</button>}
    </fieldset></form>
    <form key={`notes-${item.version}`} onChange={()=>setNotesDirty(true)} onSubmit={e=>{e.preventDefault();void run(`/${item.id}`,'PATCH',{version:item.version,notes:new FormData(e.currentTarget).get('notes')});}}><fieldset disabled={busy||dirty||pricingDirty}><label>{t.notes}<textarea name="notes" maxLength={2000} defaultValue={item.notes}/></label><button className="button button-outline">{t.save}</button></fieldset></form>
    <button className="button button-dark" disabled={busy||dirty||notesDirty||pricingDirty||!item.entries.length} onClick={()=>{setReview(true);setNotice('');}}>{t.review}</button>
   </>}
   {(review||item.status==='submitted') && <p>{t.notes}: {item.notes || '—'}</p>}
   <CheckoutPanel refreshKey={deliveryRefresh} item={item} lang={lang} disabled={busy||dirty||notesDirty||pricingDirty} onDirty={setDeliveryDirty} onChange={()=>setDeliveryRefresh(r=>r+1)}/>
   <PricingPanel key={`${item.id}-${reload}-${deliveryRefresh}`} item={item} lang={lang} readOnly={review} onAccepted={()=>setDeliveryRefresh(r=>r+1)} disabled={busy||dirty||notesDirty||deliveryDirty} onDirty={setPricingDirty} onChange={value=>{setItem(value);setPricingDirty(false);}}/>
   {review && item.status==='draft' && <div className="auth-panel"><p>{t.warning}</p><button className="button button-dark" disabled={busy} onClick={()=>void run(`/${item.id}/confirm`,'POST',{version:item.version})}>{t.confirm}</button><button className="button button-outline" disabled={busy} onClick={()=>setReview(false)}>{t.cancel}</button></div>}
  </>}
 </div>;
}
export function SubmissionPage({lang,identifier}:{lang:Language;identifier:string}) {const [selected,setSelected]=useState(lang);return <section className="section"><Container><label>{selected==='FR'?'Langue de l’interface':'Interface language'}<select value={selected} onChange={e=>setSelected(e.target.value==='EN'?'EN':'FR')}><option value="FR">Français</option><option value="EN">English</option></select></label><Submissions lang={selected} identifier={identifier}/><Link href="/account" className="text-link">{submissionMessages[selected].back}</Link></Container></section>;}

