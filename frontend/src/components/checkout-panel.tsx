'use client';

import { useEffect, useState, type FormEvent } from 'react';

import type { Language } from '@/lib/i18n';

import { checkoutMessages, parseEuro, type Address, type Order } from '@/lib/checkout';

import { submissionRequest, type Submission } from '@/lib/submissions';

import { money, pricingMessages } from '@/lib/pricing';



const addressRequest = <T,>(path='',method='GET',payload?:object)=>submissionRequest<T>(path,method,payload,fetch,'/api/addresses');

const fields=['recipient','line1','line2','postal_code','city','country','phone','instructions'] as const;

export function AddressBook({lang}:{lang:Language}) {

 const t=checkoutMessages[lang];const [addresses,setAddresses]=useState<Address[]>([]);const [editing,setEditing]=useState<Address|null|undefined>();const [error,setError]=useState('');const [busy,setBusy]=useState(false);

 async function load(){try{setAddresses(await addressRequest<Address[]>());setError('');}catch{setError(t.error);}}

 useEffect(()=>{let active=true;addressRequest<Address[]>().then(a=>{if(active)setAddresses(a);}).catch(()=>{if(active)setError(t.error);});return()=>{active=false;};},[t.error]);

 async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const data=new FormData(e.currentTarget);const payload=Object.fromEntries(fields.map(k=>[k,String(data.get(k)??'')]));setBusy(true);try{await addressRequest(editing?`/${editing.id}`:'',editing?'PUT':'POST',editing?{...payload,version:editing.version}:payload);setEditing(undefined);await load();}catch{setError(t.error);}finally{setBusy(false);}}

 async function remove(a:Address){setBusy(true);try{await addressRequest(`/${a.id}`,'DELETE',{version:a.version});await load();}catch(e){setError(e instanceof Error&&e.message==='address_in_use'?t.address_in_use:t.error);}finally{setBusy(false);}}

 return <section className="pricing-panel"><h2>{t.addresses}</h2>{error&&<p role="alert">{error}</p>}<button className="button button-outline" disabled={busy} onClick={()=>setEditing(null)}>{t.newAddress}</button><button className="button button-outline" disabled={busy} onClick={()=>void load()}>{t.reload}</button>

 {addresses.map(a=><article className="quote-line" key={a.id}><p>{a.recipient}<br/>{a.line1} {a.line2}<br/>{a.postal_code} {a.city} · {a.country}</p><button className="button button-outline" disabled={busy} onClick={()=>setEditing(a)}>{t.edit}</button><button className="button button-outline" disabled={busy} onClick={()=>void remove(a)}>{t.remove}</button></article>)}

 {editing!==undefined&&<form key={editing?.id??'new'} onSubmit={e=>void submit(e)}><fieldset disabled={busy}>{fields.map(field=><label key={field}>{t[field]}<input name={field} required={['recipient','line1','city','country'].includes(field)} maxLength={field==='country'?2:field==='phone'||field==='postal_code'?32:field==='city'?100:field==='instructions'?1000:200} pattern={field==='country'?'[A-Z]{2}':undefined} defaultValue={editing?.[field]??(field==='country'?'FR':'')} autoComplete={field==='phone'?'tel':undefined}/></label>)}<button className="button button-dark">{t.save}</button><button type="button" className="button button-outline" onClick={()=>setEditing(undefined)}>{t.cancel}</button></fieldset></form>}</section>;

}



export function CheckoutPanel({item,lang,disabled,onChange,onDirty,refreshKey}:{refreshKey:number;item:Submission;lang:Language;disabled:boolean;onChange:()=>void;onDirty:(dirty:boolean)=>void}) {

 const t=checkoutMessages[lang];const pt=pricingMessages[lang];const [order,setOrder]=useState<Order|null>(null);const [addresses,setAddresses]=useState<Address[]>([]);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [refresh,setRefresh]=useState(0);

 useEffect(()=>{let active=true;Promise.all([submissionRequest<Order>(`/${item.id}/order-summary`),addressRequest<Address[]>()]).then(([o,a])=>{if(active){setOrder(o);setAddresses(a);setError('');}}).catch(()=>{if(active)setError(t.error);});return()=>{active=false;};},[item.id,item.version,refresh,refreshKey,t.error]);

 async function save(e:FormEvent<HTMLFormElement>){e.preventDefault();if(!order)return;const data=new FormData(e.currentTarget);const raw=String(data.get('declared')??'');const declared=raw?parseEuro(raw):null;if(raw&&declared===null){setError(t.error);return;}setBusy(true);try{const parcel=Object.fromEntries(['weight_g','length_mm','width_mm','height_mm'].map(k=>[k,data.get(k)?Number(data.get(k)):null]));setOrder(await submissionRequest<Order>(`/${item.id}/delivery`,'PUT',{version:order.delivery.version,address_id:data.get('address')||null,declared_value_minor:declared,service_id:data.get('service')||null,parcel}));setError('');onDirty(false);onChange();}catch{setError(t.error);}finally{setBusy(false);}}

 return <section className="pricing-panel"><h2>{t.summary}</h2>{error&&<p role="alert">{error}</p>}<p>{t.detailed}</p>{order&&<><p>{order.submission_reference} · {t.quantity}: {order.quantity}</p>{order.grading&&<><ul>{order.grading.lines.map(line=><li key={line.entry_id}>{line.card_name} / {line.quantity} / {line.tier_name[lang]} / {line.upgrades.map(u=>u.name[lang]).join(', ')}: {money(line.total_minor,lang)}</li>)}</ul><dl className="pricing-totals">{([[t.baseCharges,order.grading.base_minor],[t.speedCharges,order.grading.speed_minor],[t.upgradeCharges,order.grading.upgrades_minor],[pt.discount,order.grading.discount_minor],[pt.net,order.grading.net_minor],[pt.tax,order.grading.tax_minor],[pt.total,order.grading.total_minor]] as [string,number][]).map(([label,amount])=><div key={label}><dt>{label}</dt><dd>{money(amount,lang)}</dd></div>)}</dl><p>{order.grading.tax_description[lang]}</p></>}<h3>{t.delivery}</h3><form key={`${order.delivery.version}:${refresh}`} onSubmit={e=>void save(e)} onChange={()=>onDirty(true)}><fieldset disabled={busy||disabled||order.terms_accepted}><label>{t.choose}<select name="address" defaultValue={order.delivery.address_id??''}><option value="">—</option>{addresses.map(a=><option value={a.id} key={a.id}>{a.recipient} · {a.line1} · {a.city} · {a.country}</option>)}</select></label><a className="text-link" href="/account/settings">{t.addresses} ↗</a><label>{t.declared}<input name="declared" inputMode="decimal" pattern="[0-9]+([.,][0-9]{1,2})?" defaultValue={order.delivery.declared_value_minor===null?'':(order.delivery.declared_value_minor/100).toFixed(2)}/></label><label>{t.service}<select name="service" defaultValue={order.delivery.service_id??''}><option value="">{t.noService}</option>{order.available_services.map(s=><option value={s.id} key={s.id}>{s.name[lang]}</option>)}</select></label>{(['weight_g','length_mm','width_mm','height_mm'] as const).map(k=><label key={k}>{t[k]}<input name={k} type="number" min="1" max={k==='weight_g'?100000:5000} defaultValue={order.delivery.parcel[k]??''}/></label>)}<button className="button button-dark">{t.save}</button></fieldset></form>

 {order.return_address&&<p>{order.return_address.recipient}<br/>{order.return_address.line1} {order.return_address.line2}<br/>{order.return_address.postal_code} {order.return_address.city} · {order.return_address.country}<br/>{order.return_address.phone}<br/>{order.return_address.instructions}</p>}

 <ul aria-live="polite">{order.readiness.states.map(s=><li key={s}>{t[s as keyof typeof t]??s}</li>)}</ul>{order.shipping.charge_minor!==null&&<><p>{t.shipping}: {money(order.shipping.charge_minor,lang)}</p><p>{order.shipping.service?.coverage[lang]}</p><p>{order.shipping.service?.exclusions[lang]}</p></>}<p><strong>{t.payable}: {order.final_payable_minor===null?t.pending:money(order.final_payable_minor,lang)}</strong></p><button className="button button-dark" disabled>{t.checkout}</button><h3>{t.inbound}</h3><p>{t.policy}</p><p>{order.inbound_receiving_address??t.receivingPending}</p></>}<button className="button button-outline" disabled={busy} onClick={()=>{setRefresh(r=>r+1);onDirty(false);onChange();}}>{t.reload}</button></section>;

}

