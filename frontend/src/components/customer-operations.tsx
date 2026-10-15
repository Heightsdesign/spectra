"use client";
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { customerOperationsCopy, customerOperationsError, customerOperationsRequest, customerProfileHref, intakeDetailHref,
  type Language, type CustomerSummary, type CustomerDetail,
  type CustomerSubmission, type ShipmentAddress, type ResultPage, type CardTrace } from '@/lib/customer-operations';
import { intakeStates } from '@/lib/intake';
import { useAdminLanguage } from './admin-language';
import { canonicalScan } from '@/lib/physical-labels';

function useRead<T>(path: string, revision: number) {
  const [result, setResult] = useState<{ path: string; revision: number; data: T | null; error: unknown } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    customerOperationsRequest<T>(path, fetch, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ path, revision, data, error: null });
    }).catch(error => { if (!controller.signal.aborted) setResult({ path, revision, data: null, error }); });
    return () => controller.abort();
  }, [path, revision]);
  const current = result?.path === path && result.revision === revision;
  return { loading: !current, data: current ? result.data : null, error: current ? result.error : null };
}

function LanguageSelect({ language, setLanguage }: { language: Language; setLanguage: (value: Language) => void }) {
  return <label className="intake-language">{customerOperationsCopy[language].language}<select value={language} onChange={e => setLanguage(e.target.value as Language)}><option value="FR">Français</option><option value="EN">English</option></select></label>;
}
function PageHeading({ title, language, setLanguage }: { title: string; language: Language; setLanguage: (value: Language) => void }) {
  return <header className="intake-heading"><div><p className="eyebrow">SPECTRA / {language === 'FR' ? 'Opérations internes' : 'Internal operations'}</p><h1>{title}</h1></div><LanguageSelect language={language} setLanguage={setLanguage} /></header>;
}
export function OperationsFeedback({ loading, error, empty, language, retry }: { loading?: boolean; error?: unknown; empty?: boolean; language: Language; retry?: () => void }) {
  const t = customerOperationsCopy[language];
  return <div role="status" aria-live="polite" className="operations-feedback">{loading ? <p>{t.loading}</p> : error ? <><p>{customerOperationsError(error, language)}</p>{retry && <button type="button" className="button button-outline" onClick={retry}>{t.retry}</button>}</> : empty ? <p className="intake-empty">{t.empty}</p> : null}</div>;
}
function Pagination({ offset, hasMore, loading, language, onPage }: { offset: number; hasMore: boolean; loading: boolean; language: Language; onPage: (offset: number) => void }) {
  const t = customerOperationsCopy[language];
  return <div className="intake-toolbar operations-pagination"><button type="button" className="button button-outline" disabled={loading || offset === 0} onClick={() => onPage(Math.max(0, offset - 25))}>{t.previous}</button><button type="button" className="button button-outline" disabled={loading || !hasMore} onClick={() => onPage(offset + 25)}>{t.next}</button></div>;
}
export function CustomerDirectoryTable({ items, language }: { items: CustomerSummary[]; language: Language }) {
  const t = customerOperationsCopy[language];
  return <div className="intake-scroll" role="region" aria-label={t.clients} tabIndex={0}><table><caption>{t.clients}</caption><thead><tr>{[t.name,t.email,t.status,t.date,t.open].map(title => <th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{items.map(c => <tr key={c.id}><th scope="row"><Link className="operations-link" href={customerProfileHref(c.id)}>{c.first_name} {c.last_name}</Link></th><td>{c.email}</td><td><span className="intake-badge">{c.status === 'active' ? t.active : t.disabled}</span></td><td>{new Date(c.created_at).toLocaleDateString(language.toLowerCase())}</td><td><Link className="button button-outline" href={customerProfileHref(c.id)} aria-label={`${t.open} ${c.first_name} ${c.last_name}`}>{t.open}</Link></td></tr>)}</tbody></table></div>;
}
export function CustomerDirectory({ initialLanguage }: { initialLanguage: Language }) {
  const [language, setLanguage] = useAdminLanguage(initialLanguage);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const { data, loading, error } = useRead<ResultPage<CustomerSummary>>(`/customers?search=${encodeURIComponent(query)}&limit=25&offset=${offset}`, revision);
  const t = customerOperationsCopy[language];
  return <section className="container-shell intake-workspace customer-operations" lang={language.toLowerCase()}>
    <PageHeading title={t.title} language={language} setLanguage={setLanguage} />
    <form className="intake-search operations-search" onSubmit={e => { e.preventDefault(); setQuery(search.trim()); setOffset(0); setRevision(value => value + 1); }}><label>{t.search}<input value={search} onChange={e => setSearch(e.target.value)} maxLength={254} aria-describedby="customer-search-hint" /></label><button type="submit" className="button button-dark">{t.find}</button><p id="customer-search-hint" className="intake-help">{t.searchHint}</p></form>
    <OperationsFeedback loading={loading} error={error} empty={!!data && !data.items.length} language={language} retry={() => setRevision(value => value + 1)} />
    {data && !!data.items.length && <CustomerDirectoryTable items={data.items} language={language} />}
    <Pagination offset={offset} hasMore={data?.has_more ?? false} loading={loading} language={language} onPage={setOffset} />
  </section>;
}
export function ShipmentAddressCard({ address, language }: { address: ShipmentAddress; language: Language }) {
  const t = customerOperationsCopy[language];
  return <div className="operations-address"><p><strong>{t.recipient}</strong><br />{address.recipient}</p><p>{address.line1}{address.line2 && <><br />{address.line2}</>}<br />{address.postal_code} {address.city}<br />{address.country}</p>{address.phone && <p><strong>{t.phone}</strong><br />{address.phone}</p>}{address.instructions && <p><strong>{t.instructions}</strong><br />{address.instructions}</p>}</div>;
}
export function CustomerAccount({ customer, language }: { customer: CustomerDetail; language: Language }) {
  const t = customerOperationsCopy[language];
  return <><section className="intake-overview" aria-labelledby="customer-account-title"><h2 id="customer-account-title">{t.account}</h2><dl className="operations-account">
    {([[t.reference, customer.id], [t.firstName, customer.first_name], [t.lastName, customer.last_name], [t.email, customer.email], [t.status, customer.status === 'active' ? t.active : t.disabled], [t.verified, customer.email_verified ? t.yes : t.no], [t.date, new Date(customer.created_at).toLocaleString(language.toLowerCase())]] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
  </dl><p className="intake-help">{t.noAccountPhone}</p></section>
    <section className="intake-section" aria-labelledby="customer-addresses-title"><h2 id="customer-addresses-title">{t.addresses}</h2><div className="intake-record-grid">{customer.saved_addresses.map(address => <article className="intake-record" key={address.id}><ShipmentAddressCard address={address} language={language} /></article>)}</div>{!customer.saved_addresses.length && <p className="intake-empty">{t.empty}</p>}{customer.addresses_truncated && <p>{t.addressesTruncated}</p>}</section>
  </>;
}
export function CustomerHistory({ items, language }: { items: CustomerSubmission[]; language: Language }) {
  const t = customerOperationsCopy[language];
  const labels = intakeStates[language] as Record<string, string>;
  return <div className="intake-scroll" role="region" aria-label={t.history} tabIndex={0}><table><caption>{t.history}</caption><thead><tr>{[t.submission,t.created,t.submitted,t.submissionStatus,t.intakeStatus,t.declared,t.returnAddress,t.intakeLink].map(title => <th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{items.map(s => <tr key={s.id}><th scope="row">{s.status === 'submitted' ? <Link className="operations-link" href={intakeDetailHref(s.id)}>{s.reference}</Link> : s.reference}</th><td>{new Date(s.created_at).toLocaleDateString(language.toLowerCase())}</td><td>{s.confirmed_at ? new Date(s.confirmed_at).toLocaleDateString(language.toLowerCase()) : '—'}</td><td>{s.status === 'draft' ? t.draft : s.status === 'submitted' ? t.submitted : s.status}</td><td>{s.intake_status ? labels[s.intake_status] ?? s.intake_status : '—'}</td><td>{s.declared_quantity}</td><td className="operations-shipment"><details><summary>{t.returnAddress}</summary><p className="intake-help">{s.return_address_source === 'accepted_snapshot' ? t.acceptedSnapshot : s.return_address_source === 'current_selection' ? t.currentSelection : s.return_address_source === 'not_recorded' ? t.notRecorded : t.noAddress}</p>{s.return_address && <ShipmentAddressCard address={s.return_address} language={language} />}</details></td><td>{s.status === 'submitted' && <Link className="button button-outline" href={intakeDetailHref(s.id)} aria-label={`${t.intakeLink} ${s.reference}`}>{t.intakeLink}</Link>}</td></tr>)}</tbody></table></div>;
}
export function CustomerDetailWorkspace({ customerId, initialLanguage }: { customerId: string; initialLanguage: Language }) {
  const [language, setLanguage] = useAdminLanguage(initialLanguage);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const customer = useRead<CustomerDetail>(`/customers/${encodeURIComponent(customerId)}`, revision);
  const history = useRead<ResultPage<CustomerSubmission>>(`/customers/${encodeURIComponent(customerId)}/submissions?limit=25&offset=${offset}`, revision);
  const t = customerOperationsCopy[language];
  return <section className="container-shell intake-workspace customer-operations" lang={language.toLowerCase()}>
    <PageHeading title={t.account} language={language} setLanguage={setLanguage} />
    <div className="intake-toolbar"><Link className="button button-outline" href="/admin/customers">{t.clients}</Link></div>
    <OperationsFeedback loading={customer.loading} error={customer.error} language={language} retry={() => setRevision(value => value + 1)} />
    {customer.data && <><CustomerAccount customer={customer.data} language={language} /><aside className="intake-warning">{t.association}</aside><section className="intake-section" aria-labelledby="history-title"><h2 id="history-title">{t.history}</h2><OperationsFeedback loading={history.loading} error={history.error} empty={!!history.data && !history.data.items.length} language={language} retry={() => setRevision(value => value + 1)} />{history.data && !!history.data.items.length && <CustomerHistory items={history.data.items} language={language} />}<Pagination offset={offset} hasMore={history.data?.has_more ?? false} loading={history.loading} language={language} onPage={setOffset} /></section></>}
  </section>;
}
export function CardTraceResult({ trace, language }: { trace: CardTrace; language: Language }) {
  const t = customerOperationsCopy[language];
  return <section className="intake-overview" aria-labelledby="card-trace-title"><h2 id="card-trace-title">{trace.card.reference}</h2><dl className="operations-account">{[[t.card,trace.card.reference],[t.parcel,trace.parcel.reference],[t.submission,trace.submission.reference],[t.account,`${trace.customer.first_name} ${trace.customer.last_name}`],[t.email,trace.customer.email],[t.entry,trace.declared_entry ? `${trace.declared_entry.card_name} · ${trace.declared_entry.expansion} · ${trace.declared_entry.card_number} · ${trace.declared_entry.language}` : t.unidentified]].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className="intake-help">{t.association}</p><div className="intake-toolbar"><Link className="button button-outline" href={customerProfileHref(trace.customer.id)}>{t.customerLink}</Link><Link className="button button-outline" href={intakeDetailHref(trace.submission.id)}>{t.intakeLink}</Link></div></section>;
}
export function PhysicalCardLookup({ initialLanguage }: { initialLanguage: Language }) {
  const [language, setLanguage] = useAdminLanguage(initialLanguage);
  const [reference, setReference] = useState('');
  const [result, setResult] = useState<CardTrace | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const t = customerOperationsCopy[language];
  async function lookup() {
    setResult(null); setError(null);
    let canonical:string;
    try {canonical=canonicalScan(reference);} catch {setError(new Error('invalid_card_reference'));return;}
    setLoading(true);
    try { setResult(await customerOperationsRequest<CardTrace>(`/cards/${encodeURIComponent(canonical)}`)); }
    catch (error) { setError(error); }
    finally { setLoading(false); }
  }
  return <section className="container-shell intake-workspace customer-operations" lang={language.toLowerCase()}><PageHeading title={t.trace} language={language} setLanguage={setLanguage} /><form className="intake-search operations-search" onSubmit={e => { e.preventDefault(); void lookup(); }}><label>{t.cardReference}<input required disabled={loading} maxLength={128} value={reference} onChange={e => setReference(e.target.value)} aria-describedby="card-reference-hint" /></label><button type="submit" className="button button-dark" disabled={loading}>{t.find}</button><p id="card-reference-hint" className="intake-help">{t.cardHint}</p></form><OperationsFeedback loading={loading} error={error} language={language} />{result ? <CardTraceResult trace={result} language={language} /> : !error && !loading && <p className="intake-empty">{t.lookupEmpty}</p>}</section>;
}
