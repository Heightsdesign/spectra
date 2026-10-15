"use client";
import Link from 'next/link';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { intakeCopy, intakeStates, intakeErrors, intakeEvents, intakeRequest, type IntakeSummary, type IntakeDetail, type IntakeStatus } from '@/lib/intake';
import { customerProfileHref } from '@/lib/customer-operations';
import { useAdminLanguage } from './admin-language';
import { CardLabelActions, PhysicalLabelsPanel } from './physical-labels';

export function IntakeWorkspace({ initialLanguage, role, initialSubmissionId }: { initialLanguage: 'FR' | 'EN'; role: string; initialSubmissionId?: string }) {
  const [lang, setLang] = useAdminLanguage(initialLanguage);
  const [items, setItems] = useState<IntakeSummary[]>([]);
  const [item, setItem] = useState<IntakeDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const keys = useRef(new Map<string, { signature: string; key: string }>());
  const t = intakeCopy[lang];
  const labels = intakeStates[lang];
  const label = (value: string) => labels[value as keyof typeof labels] ?? value;
  const errorMessage = (error: unknown) => {
    const code = error instanceof Error ? error.message : '';
    return intakeErrors[lang][code as keyof typeof intakeErrors.EN] ?? t.error;
  };
  const sid = item?.id;
  const detailHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (sid) detailHeading.current?.focus(); }, [sid]);
  const path = `/submissions/${sid}`;
  const locked = busy || item?.status === 'reconciled';
  const reconciling = item?.status === 'reconciliation_pending';

  async function load(id?: string) {
    try {
      if (id) setItem(await intakeRequest(`/submissions/${id}`));
      else setItems(await intakeRequest(`/submissions?search=${encodeURIComponent(search)}&status=${filter}`));
    } catch (error) { setNotice(errorMessage(error)); }
  }
  useEffect(() => {
    let active = true;
    intakeRequest(initialSubmissionId ? `/submissions/${encodeURIComponent(initialSubmissionId)}` : '/submissions').then(data => { if (active) { if (initialSubmissionId) setItem(data); else setItems(data); } }).catch(() => { if (active) setNotice(intakeCopy[initialLanguage].error); });
    return () => { active = false; };
  }, [initialLanguage, initialSubmissionId]);

  async function mutate(endpoint: string, payload: Record<string, unknown>, creation = false) {
    if (!window.confirm(payload.action === 'complete' ? t.finalizeConfirm : t.confirm)) return;
    setBusy(true); setNotice('');
    if (creation) {
      const signature = JSON.stringify(payload);
      const previous = keys.current.get(endpoint);
      const key = previous?.signature === signature ? previous.key : crypto.randomUUID();
      keys.current.set(endpoint, { signature, key });
      payload = { ...payload, request_key: key };
    }
    try {
      await intakeRequest(endpoint, payload);
      keys.current.delete(endpoint);
      setItem(await intakeRequest(path));
      setNotice(t.saved);
    } catch (error) { setNotice(errorMessage(error)); }
    finally { setBusy(false); }
  }
  function form(title: string, endpoint: string, fields: ReactNode, transform: (v: Record<string, string>) => Record<string, unknown> = v => v, creation = false) {
    const finalizing = title === t.complete;
    return <form className={finalizing ? 'intake-form intake-finalize' : 'intake-form'} onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const values = Object.fromEntries(new FormData(e.currentTarget)) as Record<string,string>; void mutate(endpoint, transform(values), creation); }}><fieldset disabled={locked}><legend>{title}</legend>{finalizing && <p className="intake-warning">{t.finalizeHelp}</p>}{title === t.override && <p>{t.overrideHelp}</p>}<div className="intake-fields">{fields}</div><button type="submit" className={finalizing ? 'button intake-danger' : 'button button-outline'}>{busy ? t.busy : title}</button></fieldset></form>;
  }
  const input = (name: string, title: string, required = false, maxLength = 2000) => <label className="intake-field">{title}<input name={name} required={required} maxLength={maxLength} /></label>;
  const entries = <><option value="">{t.unknown}</option>{item?.entries.map(e => <option key={e.id} value={e.id}>{e.card_name} · {e.expansion} · {e.card_number} · {e.language} × {e.quantity}</option>)}</>;
  const receipt = (status: IntakeStatus) => ({ awaiting_receipt:t.waiting, partially_received:t.partial, reconciliation_pending:t.pending, reconciled:t.done, on_hold:t.held })[status];
  return <section className="container-shell intake-workspace" lang={lang.toLowerCase()} aria-labelledby="intake-title"><header className="intake-heading"><div><p className="eyebrow">SPECTRA / {t.operations}</p><h1 id="intake-title">{t.title}</h1></div><label className="intake-language">{t.language} <select value={lang} onChange={e => setLang(e.target.value as 'FR' | 'EN')}><option value="FR">Français</option><option value="EN">English</option></select></label></header><p className={notice ? 'intake-feedback' : 'intake-feedback is-empty'} role="status" aria-live="polite">{notice}</p>
    {!item ? <>
      <form className="intake-search" onSubmit={e => { e.preventDefault(); void load(); }}>
        <label>{t.search}<input maxLength={40} value={search} onChange={e => setSearch(e.target.value)} /></label>
        <label>{t.filter}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">{t.all}</option>{(['awaiting_receipt','partially_received','reconciliation_pending','reconciled','on_hold'] as const).map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label>
        <button type="submit" className="button button-dark">{t.find}</button>
      </form>
      <div className="intake-scroll" role="region" aria-label={t.back} tabIndex={0}><table>
        <caption>{t.back}</caption>
        <thead><tr>{[t.search,t.customer,t.declared,t.received,t.status,t.date,t.receipt,t.open].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{items.map(row => <tr key={row.id}><th scope="row">{row.reference}</th><td className="intake-reference">{row.customer_reference}</td><td>{row.declared_quantity}</td><td>{row.received_quantity}</td><td><span className="intake-badge">{label(row.status)}</span></td><td>{new Date(row.submitted_at).toLocaleString(lang.toLowerCase())}</td><td>{receipt(row.status)}</td><td><button type="button" className="button button-outline" aria-label={`${t.open} ${row.reference}`} onClick={() => void load(row.id)}>{t.open}</button></td></tr>)}</tbody>
      </table>{!items.length && <p className="intake-empty">{t.empty}</p>}</div>
      <button type="button" className="button button-outline" onClick={() => { if (items.length) { const last = items[items.length-1]; void intakeRequest(`/submissions?search=${encodeURIComponent(search)}&status=${filter}&offset=${items.length}`).then(data => setItems([...items, ...data.filter((r: IntakeSummary) => r.id !== last.id)])).catch(() => setNotice(t.error)); } }}>+ {t.more}</button>
    </> : <>
      <div className="intake-toolbar"><button type="button" className="button button-outline" disabled={busy} onClick={() => { setItem(null); void load(); }}>{t.back}</button><button type="button" className="button button-outline" disabled={busy} onClick={() => void load(item.id)}>{t.refresh}</button></div>
      <section className="intake-overview" aria-labelledby="overview-title">
        <div className="intake-heading"><div><p className="eyebrow">{t.overview}</p><h2 id="overview-title" ref={detailHeading} tabIndex={-1}>{item.reference}</h2></div><span className="intake-badge">{label(item.status)}</span></div>
        <dl className="intake-metrics"><div><dt>{t.customer}</dt><dd className="intake-reference">{item.customer_reference}</dd><dd><Link className="operations-link" href={customerProfileHref(item.customer_reference)}>{t.customerProfile}</Link></dd></div><div><dt>{t.declared}</dt><dd>{item.declared_quantity}</dd></div><div><dt>{t.received}</dt><dd>{item.received_quantity}</dd></div><div><dt>{t.accepted}</dt><dd>{item.commercially_accepted ? t.yes : t.no}</dd></div></dl>
        <p>{receipt(item.status)}</p>{item.status === 'reconciled' && <p className="intake-warning">{t.final}</p>}
      </section>
      <nav className="intake-section-nav" aria-label={t.overview}>{[['authorization',t.authorization],['parcels',t.parcels],['inventory',t.cards],['declarations',t.declared],['discrepancies',t.issues],['audit',t.audit]].map(([id,title]) => <a key={id} href={`#intake-${id}`}>{title}</a>)}</nav>
      <section className="intake-section" id="intake-authorization" aria-labelledby="authorization-title">
        <h2 id="authorization-title">{t.authorization}</h2><aside className="intake-warning">{t.warning}</aside><p className="intake-badge">{item.operational_override ? t.authorized : t.notAuthorized}</p>
        <div className="intake-grid">{(['override','begin','hold','resume','complete'] as const).filter(action => action === 'override' ? role === 'admin' && !item.operational_override : action === 'begin' ? item.status === 'partially_received' : action === 'resume' ? item.status === 'on_hold' : action === 'complete' ? reconciling : item.status !== 'on_hold').map(action => <div key={action}>{form(t[action],path+'/transition',input('reason',t.reason,true,1000),v=>({...v, action}))}</div>)}</div>
      </section>
      <section className="intake-section" id="intake-parcels" aria-labelledby="parcels-title">
        <h2 id="parcels-title">{t.parcels} <span className="intake-count">{item.parcels.length}</span></h2>
        {form(t.register,path+'/parcels',<>{input('carrier',t.carrier,false,100)}{input('tracking',t.tracking,false,200)}{input('notes',t.notes)}</>,v=>v,true)}
        <div className="intake-record-grid">{item.parcels.map(p=><article className="intake-record" key={p.id}><h3>{p.reference}</h3><span className="intake-badge">{label(p.status)}</span><p>{new Date(p.received_at).toLocaleString(lang.toLowerCase())}</p><p>{p.carrier} · {p.tracking}</p><p>{p.notes}</p></article>)}</div>{!item.parcels.length && <p className="intake-empty">{t.empty}</p>}
      </section>
      <section className="intake-section" id="intake-inventory" aria-labelledby="inventory-title">
        <h2 id="inventory-title">{t.cards} <span className="intake-count">{item.cards.length}</span></h2><p className="intake-help">{t.inventoryHelp}</p>
        {reconciling && form(t.create,path+'/cards',<><label>{t.parcel}<select name="parcel_id" required>{item.parcels.map(p=><option key={p.id} value={p.id}>{p.reference}</option>)}</select></label>{input('notes',t.notes)}</>,v=>v,true)}
        <PhysicalLabelsPanel key={item.id} submissionId={item.id} references={item.cards.map(c=>c.reference)} language={lang}><div className="intake-record-grid">{item.cards.map(c=><article className="intake-record" key={c.id}><h3>{c.reference}</h3><span className="intake-badge">{label(c.status)}</span><p>{t.parcel}: {item.parcels.find(p=>p.id===c.parcel_id)?.reference}</p><p>{t.entry}: {item.entries.find(e=>e.id===c.entry_id)?.card_name ?? t.unknown}</p><Link className="operations-link" href={customerProfileHref(item.customer_reference)}>{t.customerProfile}</Link><CardLabelActions reference={c.reference} /><details><summary>{t.matchDetails}</summary><p>{c.notes}</p>{reconciling && form(t.match,`${path}/cards/${c.id}/match`,<><label>{t.entry}<select name="entry_id" defaultValue={c.entry_id??''}>{entries}</select></label>{input('reason',t.reason,true,1000)}</>,v=>({...v,entry_id:v.entry_id||null}))}</details></article>)}</div></PhysicalLabelsPanel>{!item.cards.length && <p className="intake-empty">{t.empty}</p>}
      </section>
      <section className="intake-section" id="intake-declarations" aria-labelledby="declarations-title">
        <h2 id="declarations-title">{t.declared}</h2><div className="intake-scroll" role="region" aria-label={t.declared} tabIndex={0}><table><caption>{t.progress}</caption><thead><tr><th scope="col">{t.entry}</th><th scope="col">{t.progress}</th></tr></thead><tbody>{item.entries.map(e=><tr key={e.id}><th scope="row">{e.card_name}<small>{e.expansion} · {e.card_number} · {e.language}</small></th><td>{item.cards.filter(c=>c.entry_id===e.id).length} / {e.quantity}</td></tr>)}</tbody></table></div>
      </section>
      <section className="intake-section" id="intake-discrepancies" aria-labelledby="discrepancies-title">
        <h2 id="discrepancies-title">{t.issues} <span className="intake-count">{item.discrepancies.length}</span></h2>
        {reconciling && form(t.record,path+'/discrepancies',<><label>{t.kind}<select name="kind">{['missing','unexpected','mismatch','damaged','unresolved'].map(k=><option key={k} value={k}>{label(k)}</option>)}</select></label><label>{t.entry}<select name="entry_id">{entries}</select></label><label>{t.cards}<select name="card_id"><option value="">—</option>{item.cards.map(c=><option key={c.id} value={c.id}>{c.reference}</option>)}</select></label><label>{t.quantity}<input name="quantity" type="number" min="1" max="10000" defaultValue="1" required /></label>{input('notes',t.notes,true)}</>,v=>({...v,card_id:v.card_id||null,entry_id:v.entry_id||null,quantity:Number(v.quantity)}))}
        <div className="intake-record-grid">{item.discrepancies.map(d=><article className="intake-record" key={d.id}><h3>{label(d.kind)} × {d.quantity}</h3><span className="intake-badge">{label(d.status)}</span><p>{item.cards.find(c=>c.id===d.card_id)?.reference} {item.entries.find(e=>e.id===d.entry_id)?.card_name}</p><p>{d.notes}</p><p>{d.resolution}</p>{reconciling && d.status==='open' && form(t.resolve,`${path}/discrepancies/${d.id}/resolve`,<><label>{t.status}<select name="status"><option value="resolved">{t.resolve}</option><option value="acknowledged">{t.acknowledge}</option></select></label>{input('reason',t.reason,true)}</>)}</article>)}</div>{!item.discrepancies.length && <p className="intake-empty">{t.empty}</p>}
      </section>
      <section className="intake-section" id="intake-audit" aria-labelledby="audit-title">
        <h2 id="audit-title">{t.audit} <span className="intake-count">{item.events.length}</span></h2>
        <div className="intake-audit-list">{item.events.map(e=><details key={e.id}><summary><time dateTime={e.created_at}>{new Date(e.created_at).toLocaleString(lang.toLowerCase())}</time><span>{intakeEvents[lang][e.action as keyof typeof intakeEvents.EN] ?? e.action}</span></summary><p>{e.actor_id} · {e.entity_id}</p><p>{e.reason}</p><pre aria-label={t.auditDetails}>{JSON.stringify(e.data,null,2)}</pre></details>)}</div>{!item.events.length && <p className="intake-empty">{t.empty}</p>}
      </section>
    </>}
  </section>;
}
