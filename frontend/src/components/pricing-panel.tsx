"use client";
import { checkoutMessages } from '@/lib/checkout';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { submissionRequest, type Entry, type Submission } from '@/lib/submissions';
import { compatible, money, ordered, pricingMessages, type Catalog, type Quote } from '@/lib/pricing';
import type { Language } from '@/lib/i18n';

function Choices({catalog,entry,lang}:{catalog:Catalog;entry?:Entry;lang:Language}) {
 const t=pricingMessages[lang];
 const id=useId();
 const [tier,setTier]=useState(entry?.processing_tier??'standard');
 const [upgrades,setUpgrades]=useState(entry?.upgrade_ids??['classic']);
 const label=upgrades.find(key=>catalog.upgrades[key]?.group==='label')??'';
 function selectLabel(value:string){setUpgrades([...upgrades.filter(key=>catalog.upgrades[key]?.group!=='label'),value]);}
 return <>
  <p className="field-hint">{t.quantityConfiguration}</p>
  <label htmlFor={`${id}-speed`}>{t.speed}</label>
  <select id={`${id}-speed`} name="processing_tier" value={tier} onChange={e=>setTier(e.target.value)} required>
   {!catalog.tiers[tier]&&<option value={tier} disabled>{tier} — {t.unavailableOption}</option>}
   {ordered(catalog.tiers).map(([key,option])=><option key={key} value={key} disabled={!option.available}>{option.name[lang]} (+{money(option.price_adjustment_minor,lang)}){!option.available?` — ${t.unavailableOption}`:''}</option>)}
  </select>
  {catalog.tiers[tier]&&<p className="field-hint">{catalog.tiers[tier].description[lang]}{catalog.tiers[tier].estimated_turnaround&&<> · {t.turnaround}: {catalog.tiers[tier].estimated_turnaround[lang]}</>}</p>}
  <label htmlFor={`${id}-label`}>{t.label}</label>
  <select id={`${id}-label`} name="upgrade_ids" value={label} onChange={e=>selectLabel(e.target.value)} required>
   {!label&&<option value="" disabled>{t.label}</option>}
   {ordered(catalog.upgrades).filter(([,u])=>u.group==='label').map(([key,u])=><option key={key} value={key} disabled={!u.available||!!(u.allowed_tiers&&!u.allowed_tiers.includes(tier))}>{u.name[lang]} — {u.price_minor===0?t.included:money(u.price_minor,lang)}{!u.available?` — ${t.unavailableOption}`:''}</option>)}
  </select>
  {label&&<p className="field-hint">{catalog.upgrades[label].description[lang]}</p>}
  {ordered(catalog.upgrades).filter(([,u])=>u.group!=='label').map(([key,u])=><label className="pricing-checkbox" key={key}><input type="checkbox" name="upgrade_ids" value={key} checked={upgrades.includes(key)} disabled={!upgrades.includes(key)&&(!u.available||!!(u.allowed_tiers&&!u.allowed_tiers.includes(tier)))} onChange={e=>setUpgrades(e.target.checked?[...upgrades,key]:upgrades.filter(i=>i!==key))}/><span>{u.name[lang]} — {money(u.price_minor,lang)}<small>{u.description[lang]}</small></span></label>)}
  {upgrades.filter(key=>!catalog.upgrades[key]).map(key=><label className="pricing-checkbox" key={key}><input type="checkbox" name="upgrade_ids" value={key} checked onChange={()=>setUpgrades(upgrades.filter(i=>i!==key))}/><span>{key} — {t.unavailableOption}</span></label>)}
  {!compatible(catalog,tier,upgrades)&&<p role="alert">{t.options_incompatible}</p>}
 </>;
}

export function EntryServiceFields({entry,lang}:{entry?:Entry;lang:Language}) {
 const [catalog,setCatalog]=useState<Catalog|null>(null);
 useEffect(()=>{let active=true;submissionRequest<Catalog>('/catalog').then(value=>{if(active)setCatalog(value);}).catch(()=>{});return()=>{active=false;};},[]);
 return catalog?<Choices catalog={catalog} entry={entry} lang={lang}/>:null;
}

function QuoteBreakdown({quote,lang}:{quote:Quote;lang:Language}) {
 const t=pricingMessages[lang]; const s=quote.snapshot; const ct=checkoutMessages[lang]; const checkout=s.checkout;
 const price=(n:number)=>money(n,lang,s.currency);
 const date=(value:string)=>new Date(value).toLocaleString(lang==='FR'?'fr-FR':'en-GB');
 return <article className="quote-review">
  <h3>{t.review}</h3><p role="status">{t[quote.status]}</p>
  {s.development_only&&<p className="pricing-example">{t.example}</p>}
  <p>{t.created}: {date(quote.created_at)} · {t.expires}: {date(quote.expires_at)}</p>
  <p className="pricing-version">{t.version}: {quote.pricing_configuration_version}</p>
  {s.volume_bracket&&<p>{lang==='FR'?'Palier appliqué à toutes les cartes':'Volume rate applied to all cards'}: {s.volume_bracket.min_quantity}+ · {price(s.volume_bracket.unit_price_minor)}</p>}
  {s.lines.map(line=><section className="quote-line" key={line.entry_id}><h4>{line.card_name} × {line.quantity}</h4><p>{line.tier_name[lang]}{line.estimated_turnaround&&<> · {t.turnaround}: {line.estimated_turnaround[lang]}</>}</p>
   <dl className="pricing-totals"><div><dt>{t.base}</dt><dd>{price(line.base_unit_minor)}</dd></div><div><dt>{t.speedCharge}</dt><dd>{price(line.speed_unit_minor)}</dd></div>{line.upgrades.map(u=><div key={u.id}><dt>{u.name[lang]} · {t.upgradeCharge}</dt><dd>{price(u.unit_minor)}</dd></div>)}<div><dt>{t.unit} × {line.quantity}</dt><dd>{price(line.subtotal_minor)}</dd></div><div><dt>{t.discount}</dt><dd>−{price(line.discount_minor)}</dd></div><div><dt>{t.net}</dt><dd>{price(line.net_minor)}</dd></div><div><dt>{t.tax}</dt><dd>{price(line.tax_minor)}</dd></div><div><dt>{t.total}</dt><dd>{price(line.total_minor)}</dd></div></dl>
  </section>)}
  {s.discount&&<p>{t.discountRule}: {s.discount.min_quantity} {t.cards}, {s.discount.rate_bps/100}% · {s.discount_scope==='base'?t.scopeBase:t.scopeAll}</p>}
  <p>{t[s.tax_mode]} · {s.tax_rate_bps/100}% · {s.tax_description[lang]}</p>
  <dl className="pricing-totals"><div><dt>{t.quantity}</dt><dd>{s.quantity}</dd></div><div><dt>{t.subtotal}</dt><dd>{price(s.subtotal_minor)}</dd></div><div><dt>{t.discount}</dt><dd>−{price(s.discount_minor)}</dd></div><div><dt>{t.net}</dt><dd>{price(s.net_minor)}</dd></div><div><dt>{t.tax}</dt><dd>{price(s.tax_minor)}</dd></div><div className="quote-total"><dt>{t.total}</dt><dd>{price(s.total_minor)}</dd></div></dl>
  {checkout&&<section className="quote-line"><h4>{ct.summary}</h4>
   {checkout.return_address&&<p>{checkout.return_address.recipient}<br/>{checkout.return_address.line1} {checkout.return_address.line2}<br/>{checkout.return_address.postal_code} {checkout.return_address.city} · {checkout.return_address.country}<br/>{checkout.return_address.phone}<br/>{checkout.return_address.instructions}</p>}
   <ul>{checkout.readiness.states.map(state=><li key={state}>{ct[state as keyof typeof ct]??state}</li>)}</ul>
   {checkout.shipping.service&&<><p>{checkout.shipping.service.name[lang]} · {money(checkout.shipping.charge_minor!,lang)}</p><p>{checkout.shipping.service.coverage[lang]}</p><p>{checkout.shipping.service.exclusions[lang]}</p></>}
   <p><strong>{ct.payable}: {checkout.final_payable_minor===null?ct.pending:money(checkout.final_payable_minor,lang)}</strong></p>
  </section>}
  {quote.accepted_at&&<p>{t.acceptedAt}: {date(quote.accepted_at)}</p>}
 </article>;
}

export function PricingPanel({item,lang,disabled,readOnly=false,onChange,onDirty,onAccepted}:{onAccepted?:()=>void;item:Submission;lang:Language;disabled:boolean;readOnly?:boolean;onChange:(item:Submission)=>void;onDirty:(dirty:boolean)=>void}) {
 const t=pricingMessages[lang];
 const [catalog,setCatalog]=useState<Catalog|null>(null);
 const [quote,setQuote]=useState<Quote|null>(null);
 const [loadedKey,setLoadedKey]=useState('');
 const [busy,setBusy]=useState(false);
 const [notice,setNotice]=useState('');
 const [refresh,setRefresh]=useState(0);
 const [dirtyForm,setDirtyForm]=useState<string|null>(null);
 const [consent,setConsent]=useState(false);
 const [expiredId,setExpiredId]=useState<string|null>(null);
 const requestKey=`${item.version}:${refresh}`;
 const loaded=loadedKey===requestKey;
 function error(e:unknown){const key=e instanceof Error?e.message:'serviceError';setNotice(key in t?key:'serviceError');}
 useEffect(()=>{
  let active=true;
  Promise.allSettled([submissionRequest<Catalog>('/catalog'),submissionRequest<Quote[]>(`/${item.id}/quotes`)]).then(([catalogResult,quotesResult])=>{
   if(!active)return;
   if(catalogResult.status==='fulfilled')setCatalog(catalogResult.value);else{setCatalog(null);error(catalogResult.reason);}
   if(quotesResult.status==='fulfilled'){const values=quotesResult.value;setQuote(values.find(q=>q.status==='accepted')??values.find(q=>q.status==='valid')??values[0]??null);}else{setQuote(null);error(quotesResult.reason);}
   setLoadedKey(`${item.version}:${refresh}`);
  });
  return()=>{active=false;};
 // Error keys are translated at render time.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[item.id,item.version,refresh]);
 useEffect(()=>{if(!quote)return;const timer=window.setTimeout(()=>setExpiredId(quote.id),Math.max(0,Date.parse(quote.expires_at)-Date.now()));return()=>window.clearTimeout(timer);},[quote]);
 // The server rechecks expiry and revision on acceptance. This clock is UI only.
 const expired=!!quote && quote.status==='valid' && quote.id===expiredId;
 async function configure(event:FormEvent<HTMLFormElement>,entryId?:string) {
  event.preventDefault();if(!catalog||busy||disabled)return;
  const values=new FormData(event.currentTarget);
  const tier=String(values.get('processing_tier'));const ids=values.getAll('upgrade_ids').map(String);
  if(!compatible(catalog,tier,ids)){setNotice('options_incompatible');return;}
  setBusy(true);setNotice('');
  try{const result=await submissionRequest<Submission>(`/${item.id}${entryId?`/entries/${entryId}`:''}/configuration`,'PATCH',{version:item.version,processing_tier:tier,upgrade_ids:ids});setQuote(null);setDirtyForm(null);onDirty(false);setConsent(false);onChange(result);setNotice('configurationSaved');}
  catch(e){error(e);}finally{setBusy(false);}
 }
 async function generate(){if(busy||disabled||dirtyForm)return;setBusy(true);setNotice('');try{setQuote(await submissionRequest<Quote>(`/${item.id}/quotes`,'POST',{version:item.version}));setConsent(false);}catch(e){error(e);}finally{setBusy(false);}}
 async function accept(event:FormEvent<HTMLFormElement>){event.preventDefault();if(!quote||!consent||busy||disabled||dirtyForm)return;setBusy(true);setNotice('');try{setQuote(await submissionRequest<Quote>(`/${item.id}/quotes/${quote.id}/accept`,'POST',{version:item.version,accept_terms:true}));onAccepted?.();}catch(e){error(e);}finally{setBusy(false);}}
 function markDirty(id:string){setDirtyForm(id);onDirty(true);setConsent(false);}
 return <section className="pricing-panel" aria-busy={busy}>
  <p className="eyebrow">SPECTRA</p><h2>{t.title}</h2><p>{t.payment}</p><p className="field-hint">{t.independent}</p>
  {notice&&<p role="status" className="auth-feedback">{t[notice as keyof typeof t]}</p>}
  <button className="button button-outline" disabled={busy||disabled} onClick={()=>{setNotice('');setDirtyForm(null);onDirty(false);setConsent(false);setRefresh(n=>n+1);}}>{t.refresh}</button>
  {!loaded&&<p>{t.loading}</p>}
  {loaded&&catalog&&<>
   {catalog.development_only&&<p className="pricing-example">{t.example}</p>}
   <p>{t.base}: {money(catalog.base_price_minor,lang)}</p>
   {(readOnly||item.status==='submitted')&&<div className="submission-list">{item.entries.map(entry=><article key={entry.id}><h3>{entry.card_name} × {entry.quantity}</h3><p>{catalog.tiers[entry.processing_tier]?.name[lang]??entry.processing_tier} · {entry.upgrade_ids.map(id=>catalog.upgrades[id]?.name[lang]??id).join(', ')}</p></article>)}</div>}
   {item.status==='draft'&&!readOnly&&item.entries.length>0&&<>
    <form key={`all-${item.version}-${refresh}`} onChange={()=>markDirty('all')} onSubmit={e=>void configure(e)}><fieldset disabled={busy||disabled||!!(dirtyForm&&dirtyForm!=='all')}><legend>{t.applyAll}</legend><Choices catalog={catalog} lang={lang}/><button className="button button-dark">{t.applyAll}</button></fieldset></form>
    <div className="pricing-configurations">{item.entries.map(entry=><form key={`${entry.id}-${item.version}-${refresh}`} onChange={()=>markDirty(entry.id)} onSubmit={e=>void configure(e,entry.id)}><fieldset disabled={busy||disabled||!!(dirtyForm&&dirtyForm!==entry.id)}><legend>{entry.card_name} × {entry.quantity}</legend><Choices catalog={catalog} lang={lang} entry={entry}/><button className="button button-outline">{t.save}</button></fieldset></form>)}</div>
   </>}
   <button className="button button-dark" disabled={busy||disabled||!!dirtyForm||!item.entries.length||quote?.status==='accepted'} onClick={()=>void generate()}>{t.generate}</button>
  </>}
  {(disabled||dirtyForm)&&<p>{t.unsaved}</p>}
  {loaded&&quote&&<><QuoteBreakdown quote={expired?{...quote,status:'expired'}:quote} lang={lang}/>
   {quote.status==='valid'&&!quote.snapshot.development_only&&item.status==='draft'&&<p>{t.confirmFirst}</p>}
   {quote.status==='valid'&&!expired&&!quote.snapshot.development_only&&quote.snapshot.checkout?.readiness.ready&&item.status==='submitted'&&<form onSubmit={e=>void accept(e)}><fieldset disabled={busy||disabled||!!dirtyForm}><label className="pricing-checkbox"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>{t.consent}</span></label><button className="button button-dark" disabled={!consent}>{t.accept}</button></fieldset></form>}
  </>}
  {loaded&&!quote&&<p>{t.noQuote}</p>}
 </section>;
}
