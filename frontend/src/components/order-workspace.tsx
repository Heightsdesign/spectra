'use client';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import type { Language } from '@/lib/i18n';
import { submissionRequest, submissionMessages, type Submission, type Entry } from '@/lib/submissions';
import { checkoutMessages, customerDeliveryInput, payableAmount, type Address, type Order } from '@/lib/checkout';
import { commonConfiguration, compatible, hasMixedConfiguration, money, pricingMessages, type Catalog, type Quote } from '@/lib/pricing';
import { commercialMessages, canStartCheckout, canDeclareShipment, checkoutInput, type CommercialState } from '@/lib/commercial';
import { acceptedQuote, canAcceptQuote, canVisitStep, isTracking, nextAction, orderMessages, orderSteps, resumeStep, type OrderData, type OrderStep } from '@/lib/order-flow';
import { Choices, QuoteBreakdown } from './pricing-panel';
import { ReturnDetailsForm } from './checkout-panel';
import { CatalogFields } from './catalog-fields';
import { CardLibrary } from './card-library';
import { SubmissionPhotos } from './submission-photos';
import { OrderPayment } from './order-payment';
import { PaidOrderPanel } from './paid-order-panel';
import { OrderDialog } from './order-dialog';

type Action = (path: string, method: string, body: object, next?: OrderStep) => Promise<boolean>;
type ReadEpoch = { identifier: string; active: boolean; full: number; commercial: number };
class OrderReadError extends Error {}
const addressRequest = <T,>(path = '', method = 'GET', payload?: object) => submissionRequest<T>(path, method, payload, fetch, '/api/addresses');
const formatDate = (value: string, lang: Language) => new Date(value).toLocaleDateString(lang === 'FR' ? 'fr-FR' : 'en-GB', { day: 'numeric', month: 'long', year: 'numeric' });

export function OrderWorkspace({ identifier, lang }: { identifier: string; lang: Language }) {
  const t = orderMessages[lang];
  const [data, setData] = useState<OrderData | null>(null);
  const [step, setStep] = useState<OrderStep>('cards');
  const [error, setError] = useState('');
  const [readErrors, setReadErrors] = useState({ full: '', commercial: '' });
  const feedback = error || (readErrors.full === identifier || readErrors.commercial === identifier ? t.error : '');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [formDirty, setDirty] = useState(false);
  const [pendingPhotos, setPendingPhotos] = useState<Set<string>>(() => new Set());
  const dirty = formDirty || pendingPhotos.size > 0;
  const onPhotoPending = useCallback((key: string, pending: boolean) => { setPendingPhotos(previous => {
    if (previous.has(key) === pending) return previous;
    const next = new Set(previous); if (pending) next.add(key); else next.delete(key); return next;
  }); }, []);
  const [reset, setReset] = useState(0);
  const [cardReset, setCardReset] = useState(0);
  const [leave, setLeave] = useState<{ run: () => void } | null>(null);
  const [modal, setModal] = useState<'add' | 'library' | 'address' | 'shipment' | Entry | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const lock = useRef(false);
  const reads = useRef<ReadEpoch>({ identifier, active: false, full: 0, commercial: 0 });
  const latest = useRef({ dirty, busy, step, data });
  const urlRef = useRef('');
  useEffect(() => { latest.current = { dirty, busy, step, data }; }, [dirty, busy, step, data]);
  useEffect(() => {
    const epoch = { identifier, active: true, full: 0, commercial: 0 };
    reads.current = epoch;
    return () => { epoch.active = false; };
  }, [identifier]);

  const readCommercial = useCallback(async (epoch: ReadEpoch, version: number) => {
    try {
      const commercial = await submissionRequest<CommercialState>(`/${identifier}/commercial-state`);
      if (epoch.active && epoch.commercial === version) {
        setReadErrors(previous => ({ ...previous, commercial: '' }));
        setData(previous => previous?.item.id === identifier ? { ...previous, commercial } : previous);
      }
      return commercial;
    } catch {
      if (epoch.active && epoch.commercial === version) setReadErrors(previous => ({ ...previous, commercial: identifier }));
      throw new OrderReadError();
    }
  }, [identifier]);

  const load = useCallback(async (): Promise<OrderData> => {
    const epoch = reads.current;
    if (!epoch.active || epoch.identifier !== identifier) throw new OrderReadError();
    const fullVersion = ++epoch.full;
    const commercialVersion = ++epoch.commercial;
    const details = Promise.all([
      submissionRequest<Submission>(`/${identifier}`), submissionRequest<Order>(`/${identifier}/order-summary`),
      submissionRequest<Quote[]>(`/${identifier}/quotes`),
    ]).catch(() => {
      if (epoch.active && epoch.full === fullVersion) setReadErrors(previous => ({ ...previous, full: identifier }));
      throw new OrderReadError();
    });
    const [[item, order, quotes], commercial] = await Promise.all([details, readCommercial(epoch, commercialVersion)]);
    let quote = acceptedQuote(quotes, commercial.accepted_quote_id);
    if (!quote && commercial.accepted_quote_id) {
      try { quote = await submissionRequest<Quote>(`/${identifier}/quotes/${commercial.accepted_quote_id}`); }
      catch {
        if (epoch.active && epoch.full === fullVersion) setReadErrors(previous => ({ ...previous, full: identifier }));
        throw new OrderReadError();
      }
    }
    const result = { item, order, quote, commercial };
    if (!epoch.active || epoch.full !== fullVersion) throw new OrderReadError();
    setReadErrors(previous => ({ ...previous, full: '' }));
    // A newer commercial-only read must survive an older full response.
    setData(previous => ({ ...result, commercial: previous?.item.id === identifier ? previous.commercial : commercial }));
    return result;
  }, [identifier, readCommercial]);

  useEffect(() => {
    let active = true;
    load().then(result => {
      if (!active) return;
      const requested = new URL(location.href).searchParams.get('step');
      const candidate = orderSteps.find(value => value === requested);
      setStep(candidate && canVisitStep(candidate, result) ? candidate : resumeStep(result));
      urlRef.current = location.href;
    }).catch(() => {});
    return () => { active = false; };
  }, [load]);

  const status = data?.commercial.payment_status;
  const refreshCommercial = useCallback(async () => {
    const epoch = reads.current;
    if (epoch.active && epoch.identifier === identifier) await readCommercial(epoch, ++epoch.commercial);
  }, [identifier, readCommercial]);
  useEffect(() => {
    const focus = () => { if (latest.current.data?.item.id === identifier) void refreshCommercial().catch(() => {}); };
    window.addEventListener('focus', focus);
    return () => window.removeEventListener('focus', focus);
  }, [identifier, refreshCommercial]);
  useEffect(() => {
    if (!status || !['creating', 'pending', 'action_required'].includes(status)) return;
    const timer = window.setInterval(() => {
      if (!latest.current.dirty && !latest.current.busy && !lock.current) load().catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [status, load]);

  function safe(run: () => void) {
    if (latest.current.busy || lock.current) return;
    if (latest.current.dirty) setLeave({ run }); else run();
  }
  function move(value: OrderStep) {
    if (!data || !canVisitStep(value, data) || value === step) return;
    safe(() => {
      setStep(value); setNotice('');
      const url = new URL(location.href); url.searchParams.set('step', value);
      history.pushState(null, '', url); urlRef.current = url.href;
      requestAnimationFrame(() => { heading.current?.focus(); heading.current?.scrollIntoView({ block: 'start', behavior: 'instant' }); });
    });
  }
  useEffect(() => {
    function unload(event: BeforeUnloadEvent) { if (latest.current.dirty || latest.current.busy || lock.current) { event.preventDefault(); event.returnValue = ''; } }
    function click(event: MouseEvent) {
      if (!latest.current.dirty && !latest.current.busy && !lock.current) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
      if (!link || link.target === '_blank' || link.hasAttribute('download') || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (link.href === location.href || link.getAttribute('href')?.startsWith('#')) return;
      event.preventDefault(); event.stopPropagation();
      if (!lock.current) setLeave({ run: () => location.assign(link.href) });
    }
    function pop() {
      const target = new URL(location.href); const current = latest.current;
      if (current.dirty || lock.current) {
        history.pushState(null, '', urlRef.current);
        if (!lock.current) setLeave({ run: () => location.assign(target.href) });
        return;
      }
      const value = orderSteps.find(s => s === target.searchParams.get('step'));
      if (current.data) setStep(value && canVisitStep(value, current.data) ? value : resumeStep(current.data));
      urlRef.current = target.href;
    }
    window.addEventListener('beforeunload', unload); document.addEventListener('click', click, true); window.addEventListener('popstate', pop);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', click, true); window.removeEventListener('popstate', pop); };
  }, []);

  const act: Action = async (path, method, body, next) => {
    if (lock.current || busy) return false;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await submissionRequest(path, method, body);
      const updated = await load(); setDirty(false); setModal(null); setNotice(t.saved);
      if (path.endsWith('/delivery') && !updated.order.readiness.ready) next = 'return';
      if (next) { setStep(next); const url = new URL(location.href); url.searchParams.set('step', next); history.replaceState(null, '', url); urlRef.current = url.href; }
      requestAnimationFrame(() => heading.current?.focus());
      return true;
    } catch (cause) {
      if (cause instanceof OrderReadError) return false;
      const key = cause instanceof Error ? cause.message : '';
      if (key === 'payment_financial_restriction') await refreshCommercial().catch(() => {});
      const messages = { ...submissionMessages[lang], ...pricingMessages[lang] };
      setError(key in messages ? messages[key as keyof typeof messages] : t.actionError);
      return false;
    } finally { lock.current = false; setBusy(false); }
  };
  async function refresh() {
    const hadData = Boolean(latest.current.data);
    safe(() => { void load().then(result => { if (!hadData && reads.current.active && reads.current.identifier === identifier) setStep(resumeStep(result)); }).catch(() => {}); });
  }
  async function pay() {
    if (!data?.commercial.accepted_quote_id || !canStartCheckout(data.commercial) || lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const result = await submissionRequest<{ url: string | null; status: string }>(`/${identifier}/stripe-checkout`, 'POST', checkoutInput(data.commercial.accepted_quote_id));
      if (result.url) {
        const target = new URL(result.url);
        if (target.protocol !== 'https:' || target.hostname !== 'checkout.stripe.com') throw Error('invalid_checkout');
        location.assign(target.href);
      } else await load();
    } catch (cause) {
      if (cause instanceof OrderReadError) return;
      if (cause instanceof Error && ['payment_financial_restriction', 'payment_already_verified_or_restricted'].includes(cause.message)) await refreshCommercial().catch(() => {});
      setError(t.actionError);
    } finally { lock.current = false; setBusy(false); }
  }
  if (!data || data.item.id !== identifier) return <section className="order-workspace" aria-busy={!feedback}><p className="eyebrow">SELBY</p><h1>{t.title}</h1>{feedback ? <><p role="alert">{feedback}</p><button className="button button-dark" onClick={() => void refresh()}>{t.retry}</button></> : <p role="status">{t.loading}</p>}</section>;
  const tracking = isTracking(data);
  const fictitious = Boolean(data.order.stripe_test_only || data.quote?.snapshot.stripe_test_only);
  const index = orderSteps.indexOf(step);
  const open = (value: typeof modal) => safe(() => { setModal(value); setError(''); });
  return <div className="order-workspace" lang={lang.toLowerCase()} aria-busy={busy}>
    <header className="order-header"><Link className="text-link" href="/account">← {t.account}</Link><p className="eyebrow">SELBY / {tracking ? t.tracking : t.title}</p><h1>{data.item.reference}</h1><p className="order-save-status" role="status">{dirty ? t.unsaved : t.allSaved}</p></header>
    {fictitious && <aside className="order-test-banner"><strong>{t.test}</strong><span>{t.testHint}</span></aside>}
    {feedback && <div className="order-feedback" role="alert"><p>{feedback}</p><button className="text-link" disabled={busy} onClick={() => void refresh()}>{t.refresh}</button></div>}
    {notice && <p className="order-feedback" role="status">{notice}</p>}
    {tracking ? <Tracking data={data} lang={lang} busy={busy} fictitious={fictitious} onShipment={() => open('shipment')} onRefresh={() => void refresh()} /> : <>
      <nav className="order-stepper" aria-label={t.title}><ol>{orderSteps.map((value, i) => <li key={value}><button aria-label={t[value]} aria-current={value === step ? 'step' : undefined} disabled={busy || !canVisitStep(value, data)} onClick={() => move(value)}><span>{i + 1}</span><span>{t[value]}</span></button></li>)}</ol></nav>
      <div className="order-layout"><section className="order-stage" aria-labelledby="order-step-heading">
        <p className="order-mobile-progress">{t.step} {index + 1} {t.of} 5</p><h2 ref={heading} id="order-step-heading" tabIndex={-1}>{t[step]}</h2>
        <div hidden={step !== 'cards'}><Cards key={cardReset} onPending={onPhotoPending} onRemove={entry => safe(() => void act(`/${identifier}/entries/${entry.id}`, 'DELETE', { version: data.item.version }))} data={data} lang={lang} busy={busy} onOpen={open} onBusy={setBusy} onSaved={item => { setData(previous => previous ? { ...previous, item } : previous); void load().catch(() => {}); }} />
          <div className="order-actions">{data.item.entries.length > 0 && <button className="button button-dark" disabled={busy} onClick={() => move('service')}>{t.next}</button>}</div></div>
        <div hidden={step !== 'service'}><ServiceStep key={`service-${reset}`} data={data} lang={lang} busy={busy} act={act} onDirty={setDirty} onNext={() => move('return')} /></div>
        <div hidden={step !== 'return'}><ReturnStep key={`return-${reset}`} data={data} lang={lang} busy={busy} act={act} onDirty={setDirty} onAddress={() => open('address')} onNext={() => move('quote')} /></div>
        <div hidden={step !== 'quote'}><QuoteStep key={`${data.quote?.id}-${data.quote?.status}`} data={data} lang={lang} busy={busy} act={act} onNext={() => move('payment')} /></div>
        <div hidden={step !== 'payment'}><OrderPayment data={data} lang={lang} busy={busy} onPay={() => void pay()} onRefresh={() => void refresh()} /></div>
        {index > 0 && <button type="button" className="text-link order-previous" disabled={busy} onClick={() => move(orderSteps[index - 1])}>← {t.back}</button>}
      </section><CompactSummary data={data} lang={lang} dirty={dirty} /></div>
    </>}
    {modal && <OrderDialog title={typeof modal === 'object' ? t.editCard : modal === 'add' ? t.add : modal === 'library' ? t.library : modal === 'address' ? t.newAddress : t.declare} closeLabel={t.close} busy={busy} onClose={() => safe(() => setModal(null))}>
      {(modal === 'add' || typeof modal === 'object') && <CardEditor key={typeof modal === 'object' ? modal.id : 'new'} item={data.item} entry={typeof modal === 'object' ? modal : null} lang={lang} busy={busy} act={act} onDirty={setDirty} />}
      {modal === 'library' && <CardLibrary lang={lang} refreshKey={data.item.version} disabled={busy} onChoose={copy => void act(`/${identifier}/library-copies`, 'POST', { copy_id: copy.id, version: data.item.version })} />}
      {modal === 'address' && <AddressEditor lang={lang} onDirty={setDirty} onSave={async payload => {
        if (lock.current) return; lock.current = true; setBusy(true); setError('');
        try { await addressRequest('', 'POST', payload); await load(); setDirty(false); setModal(null); setReset(n => n + 1); setNotice(t.saved); }
        catch (cause) { if (!(cause instanceof OrderReadError)) setError(t.actionError); } finally { lock.current = false; setBusy(false); }
      }} busy={busy} />}
      {modal === 'shipment' && <ShipmentEditor data={data} lang={lang} busy={busy} act={act} onDirty={setDirty} />}
      {feedback && <p role="alert" className="order-feedback">{feedback}</p>}
    </OrderDialog>}
    {leave && <OrderDialog title={t.leaveTitle} closeLabel={t.close} onClose={() => setLeave(null)}><p>{t.leaveHint}</p><div className="order-actions"><button className="button button-dark" onClick={() => setLeave(null)}>{t.stay}</button><button className="button button-outline" onClick={() => { const action = leave.run; setLeave(null); setDirty(false); latest.current = { ...latest.current, dirty: false }; if (pendingPhotos.size) setCardReset(n => n + 1); setPendingPhotos(new Set()); setReset(n => n + 1); action(); }}>{t.discard}</button></div></OrderDialog>}
  </div>;
}

function CompactSummary({ data, lang, dirty }: { data: OrderData; lang: Language; dirty: boolean }) {
  const [expanded, setExpanded] = useState(true);
  useEffect(() => {
    const media = matchMedia('(min-width: 761px)');
    const update = () => setExpanded(media.matches);
    const timer = window.setTimeout(update, 0); media.addEventListener('change', update);
    return () => { clearTimeout(timer); media.removeEventListener('change', update); };
  }, []);
  const t = orderMessages[lang]; const amount = dirty ? null : payableAmount(data.order);
  const lines = data.order.grading?.lines ?? [];
  const services = [...new Set(lines.map(line => line.tier_name[lang]))];
  return <aside className="order-summary"><details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>{t.summary}</summary><div><dl><div><dt>{t.count}</dt><dd>{data.item.card_count}</dd></div><div><dt>{t.service}</dt><dd>{services.length > 1 ? t.mixed : services[0] ?? '—'}</dd></div><div className="order-summary-total"><dt>{t.total}</dt><dd>{amount === null ? t.undetermined : money(amount, lang)}</dd></div></dl>{amount === null && <p>{t.estimate}</p>}</div></details></aside>;
}

function Cards({ data, lang, busy, onOpen, onRemove, onPending, onBusy, onSaved }: { data: OrderData; lang: Language; busy: boolean; onOpen: (value: 'add' | 'library' | Entry) => void; onRemove: (entry: Entry) => void; onPending: (key: string, pending: boolean) => void; onBusy: (value: boolean) => void; onSaved: (item: Submission) => void }) {
  const { item } = data; const t = orderMessages[lang]; const locked = item.status !== 'draft';
  return <><p className="order-intro">{locked ? t.locked : t.emptyHint}</p>
    {!locked && <div className="order-add-actions"><button className={item.entries.length ? 'button button-outline' : 'button button-dark'} disabled={busy} onClick={() => onOpen('add')}>+ {t.add}</button>{item.library_enabled && <button className="text-link" disabled={busy} onClick={() => onOpen('library')}>{t.library}</button>}</div>}
    {!item.entries.length && <div className="order-empty"><span aria-hidden="true">＋</span><h3>{t.empty}</h3></div>}
    <ul className="order-card-list">{item.entries.map(entry => <li key={entry.id}><div className="order-card-heading"><div><h3>{entry.card_name}</h3><p>{entry.expansion} · {entry.card_number} · {entry.language}</p></div><span className="order-quantity">× {entry.quantity}</span></div>
      <details><summary>{t.details}</summary><p>{entry.notes}</p>{entry.owned_copy_id && <p>CC-{entry.owned_copy_id.replaceAll('-', '').toUpperCase()}</p>}<SubmissionPhotos item={item} entry={entry} lang={lang} disabled={busy} readOnly={locked} onBusy={onBusy} onSaved={onSaved} onPending={onPending} /></details>
      {!locked && <div className="order-card-tools">{!entry.owned_copy_id && <button className="text-link" disabled={busy} onClick={() => onOpen(entry)}>{t.edit}</button>}<button className="text-link" disabled={busy} onClick={() => onRemove(entry)}>{t.remove}</button></div>}
    </li>)}</ul>
  </>;
}

function CardEditor({ item, entry, lang, busy, act, onDirty }: { item: Submission; entry: Entry | null; lang: Language; busy: boolean; act: Action; onDirty: (value: boolean) => void }) {
  const t = submissionMessages[lang];
  return <form onChange={() => onDirty(true)} onSubmit={event => {
    event.preventDefault(); if (item.status !== 'draft') return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    void act(entry ? `/${item.id}/entries/${entry.id}` : `/${item.id}/${item.library_enabled ? 'library-register' : 'entries'}`, entry ? 'PUT' : 'POST', { ...values, catalog_card_id: values.catalog_card_id || null, quantity: Number(values.quantity), version: item.version });
  }}><fieldset disabled={busy || item.status !== 'draft'}><CatalogFields entry={entry} lang={lang} onDirty={() => onDirty(true)} /><label>{t.quantity}<input name="quantity" type="number" min={1} max={100} required defaultValue={entry?.quantity ?? 1} /></label><label>{t.cardNotes}<textarea name="notes" maxLength={2000} defaultValue={entry?.notes ?? ''} /></label><button className="button button-dark">{orderMessages[lang].saveCard}</button></fieldset></form>;
}

function ServiceStep({ data, lang, busy, act, onDirty, onNext }: { data: OrderData; lang: Language; busy: boolean; act: Action; onDirty: (value: boolean) => void; onNext: () => void }) {
  const t = orderMessages[lang]; const { item } = data;
  const [catalog, setCatalog] = useState<Catalog | null>(null); const [error, setError] = useState(false); const [retry, setRetry] = useState(0);
  const [perCard, setPerCard] = useState(false); const [replace, setReplace] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  useEffect(() => { let active = true; submissionRequest<Catalog>('/catalog').then(value => { if (active) { setCatalog(value); setError(false); } }).catch(() => { if (active) setError(true); }); return () => { active = false; }; }, [retry]);
  const mixed = hasMixedConfiguration(item.entries);
  async function save(event: FormEvent<HTMLFormElement>, entry?: Entry) {
    event.preventDefault(); if (!catalog || item.status !== 'draft') return;
    const form = new FormData(event.currentTarget); const tier = String(form.get('processing_tier')); const ids = form.getAll('upgrade_ids').map(String);
    if (!compatible(catalog, tier, ids)) return;
    const result = await act(`/${item.id}${entry ? `/entries/${entry.id}` : ''}/configuration`, 'PATCH', { version: item.version, processing_tier: tier, upgrade_ids: ids, ...(!entry ? { notes: String(form.get('order_notes') ?? '') } : {}) }, entry ? undefined : 'return');
    if (result) { setEditing(null); setReplace(false); }
  }
  if (item.status !== 'draft') return <><p className="order-intro">{t.locked}</p><ServiceList data={data} lang={lang} /><button className="button button-dark" disabled={busy} onClick={onNext}>{t.next}</button></>;
  return <><p className="order-intro">{t.serviceHint}</p>{error ? <p role="alert">{pricingMessages[lang].pricing_unavailable} <button className="text-link" onClick={() => setRetry(n => n + 1)}>{t.retry}</button></p> : !catalog ? <p role="status">{t.loading}</p> : <>
    {mixed && <p>{t.mixedHint}</p>}
    <form key={`all-${item.version}`} onChange={() => { onDirty(true); setEditing('all'); }} onSubmit={event => void save(event)}><fieldset disabled={busy || Boolean(editing && editing !== 'all')}>
      {mixed && <label className="order-check"><input type="checkbox" checked={replace} onChange={event => setReplace(event.target.checked)} />{t.replace}</label>}
      <fieldset disabled={mixed && !replace}><Choices catalog={catalog} entry={commonConfiguration(item.entries)} lang={lang} /><label>{t.notes}<textarea name="order_notes" maxLength={2000} defaultValue={item.notes} /></label>{(!mixed || replace) && <button className="button button-dark" disabled={!item.entries.length}>{t.saveService}</button>}</fieldset>
    </fieldset></form>
    <details open={perCard} onToggle={event => setPerCard(event.currentTarget.open)}><summary>{t.perCard}</summary>{item.entries.map(entry => <form className="order-per-card" key={`${entry.id}-${item.version}`} onChange={() => { onDirty(true); setEditing(entry.id); }} onSubmit={event => void save(event, entry)}><fieldset disabled={busy || Boolean(editing && editing !== entry.id)}><legend>{entry.card_name} × {entry.quantity}</legend><Choices catalog={catalog} entry={entry} lang={lang} perEntry /><button className="button button-outline">{pricingMessages[lang].save}</button></fieldset></form>)}</details>
    {mixed && !editing && <button className="button button-dark" disabled={busy} onClick={onNext}>{t.next}</button>}
  </>}</>;
}

function ReturnStep({ data, lang, busy, act, onDirty, onAddress, onNext }: { data: OrderData; lang: Language; busy: boolean; act: Action; onDirty: (value: boolean) => void; onAddress: () => void; onNext: () => void }) {
  const t = orderMessages[lang]; const [addresses, setAddresses] = useState<Address[]>([]); const [error, setError] = useState(false); const [revision, setRevision] = useState(0);
  useEffect(() => { let active = true; addressRequest<Address[]>().then(value => { if (active) { setAddresses(value); setError(false); } }).catch(() => { if (active) setError(true); }); return () => { active = false; }; }, [revision]);
  const accepted = data.order.terms_accepted || data.quote?.status === 'accepted';
  if (accepted) return <><p className="order-intro">{t.returnLocked}</p><ReturnAddress order={data.order} /><button className="button button-dark" disabled={busy} onClick={onNext}>{t.next}</button></>;
  return <><p className="order-intro">{t.returnHint}</p>{error && <p role="alert">{checkoutMessages[lang].error} <button className="text-link" onClick={() => setRevision(n => n + 1)}>{t.retry}</button></p>}
    <button className="text-link" disabled={busy} onClick={onAddress}>+ {t.newAddress}</button>
    <ReturnDetailsForm key={`${data.order.delivery.version}-${data.item.version}`} order={data.order} addresses={addresses} lang={lang} disabled={busy || error} onDirty={() => onDirty(true)} onSubmit={event => {
      event.preventDefault(); let payload; try { payload = customerDeliveryInput(new FormData(event.currentTarget), data.order.delivery.version); } catch { setError(true); return; }
      void act(`/${data.item.id}/delivery`, 'PUT', payload, 'quote');
    }} embedded />
    <Readiness order={data.order} lang={lang} />
    {data.order.shipping.service && <details><summary>{checkoutMessages[lang].service}</summary><p>{data.order.shipping.service.name[lang]}</p><p>{data.order.shipping.service.coverage[lang]}</p><p>{data.order.shipping.service.exclusions[lang]}</p></details>}
  </>;
}

function AddressEditor({ lang, busy, onDirty, onSave }: { lang: Language; busy: boolean; onDirty: (value: boolean) => void; onSave: (payload: object) => Promise<void> }) {
  const t = checkoutMessages[lang]; const fields = ['recipient', 'line1', 'line2', 'postal_code', 'city', 'country', 'phone', 'instructions'] as const;
  return <form onChange={() => onDirty(true)} onSubmit={event => { event.preventDefault(); void onSave(Object.fromEntries(new FormData(event.currentTarget))); }}><fieldset disabled={busy}>{fields.map(field => <label key={field}>{t[field]}<input name={field} required={['recipient', 'line1', 'city', 'country'].includes(field)} maxLength={field === 'country' ? 2 : field === 'phone' || field === 'postal_code' ? 32 : field === 'instructions' ? 1000 : field === 'city' ? 100 : 200} pattern={field === 'country' ? '[A-Z]{2}' : undefined} defaultValue={field === 'country' ? 'FR' : ''} /></label>)}<button className="button button-dark">{orderMessages[lang].saveAddress}</button></fieldset></form>;
}

function QuoteStep({ data, lang, busy, act, onNext }: { data: OrderData; lang: Language; busy: boolean; act: Action; onNext: () => void }) {
  const t = orderMessages[lang]; const [consent, setConsent] = useState(false); const [clock, setClock] = useState(() => Date.now()); const q = data.quote;
  useEffect(() => { if (!q || q.status !== 'valid') return; const timer = window.setTimeout(() => setClock(Date.now()), Math.min(2147483647, Math.max(0, Date.parse(q.expires_at) - Date.now() + 10))); return () => clearTimeout(timer); }, [q]);
  const valid = Boolean(q?.status === 'valid' && Date.parse(q.expires_at) > clock);
  if (q?.status === 'accepted') return <><p className="order-badge">{t.accepted}</p><QuoteSummary quote={q} lang={lang} /><button className="button button-dark" disabled={busy} onClick={onNext}>{t.next}</button></>;
  return <><p className="order-intro">{t.quoteHint}</p><ServiceList data={data} lang={lang} />
    {q ? (valid ? <QuoteSummary quote={q} lang={lang} /> : <details><summary>{t.quoteDetails}</summary><QuoteBreakdown quote={q} lang={lang} /></details>) : <p>{t.noQuote}</p>}
    <Readiness order={data.order} lang={lang} />
    {!valid && <div className="order-feedback"><p>{q ? t.expired : t.noQuote}</p><button className="button button-dark" disabled={busy || !data.item.entries.length || !data.order.readiness.ready} onClick={() => void act(`/${data.item.id}/quotes`, 'POST', { version: data.item.version })}>{q ? t.recalculate : t.generate}</button></div>}
    {valid && <>
      <section className={`order-commit ${data.item.status === 'draft' ? 'order-commit-confirm' : 'order-commit-done'}`}><p className="eyebrow">{data.item.status === 'draft' ? '01' : '✓'}</p><h3>{data.item.status === 'draft' ? t.confirmTitle : t.confirmed}</h3><p>{t.confirmHint}</p>{data.item.status === 'draft' && <button className="button button-dark" disabled={busy || !data.order.readiness.ready} onClick={() => void act(`/${data.item.id}/confirm`, 'POST', { version: data.item.version })}>{t.confirm}</button>}</section>
      <section className="order-commit order-commit-accept" data-locked={data.item.status === 'draft'}><p className="eyebrow">02</p><h3>{t.acceptTitle}</h3><p>{t.acceptHint}</p>{data.item.status === 'submitted' && <form onSubmit={event => { event.preventDefault(); if (consent && canAcceptQuote(data)) void act(`/${data.item.id}/quotes/${q!.id}/accept`, 'POST', { version: data.item.version, accept_terms: true }, 'payment'); }}><fieldset disabled={busy || !canAcceptQuote(data, clock)}><label className="order-check"><input type="checkbox" required checked={consent} onChange={event => setConsent(event.target.checked)} /><span>{t.consent} <strong>{q?.snapshot.commercial_terms_version}</strong></span></label><button className="button button-dark" disabled={!consent}>{t.accept}</button></fieldset></form>}</section>
    </>}
  </>;
}

function QuoteSummary({ quote, lang }: { quote: Quote; lang: Language }) {
  const t = orderMessages[lang]; const checkout = quote.snapshot.checkout;
  return <><dl className="order-price-list"><div><dt>{t.grading}</dt><dd>{money(quote.snapshot.total_minor, lang)}</dd></div><div><dt>{t.shipping}</dt><dd>{checkout?.shipping.charge_minor != null ? money(checkout.shipping.charge_minor, lang) : t.undetermined}</dd></div><div><dt>{t.tax}</dt><dd>{checkout?.tax_total_minor != null ? money(checkout.tax_total_minor, lang) : t.undetermined}</dd></div></dl>
    {!checkout && <p role="status">{t.legacy}</p>}<details className="order-quote-details"><summary>{t.quoteDetails}</summary><QuoteBreakdown quote={quote} lang={lang} /></details></>;
}

function Readiness({ order, lang }: { order: Order; lang: Language }) {
  if (order.readiness.ready) return null;
  const t = orderMessages[lang]; const labels = checkoutMessages[lang];
  return <div className="order-blockers" role="status"><p>{t.returnBlocked}</p><ul>{order.readiness.states.map(state => <li key={state}>{labels[state as keyof typeof labels] ?? t.unavailable}</li>)}</ul></div>;
}


function Tracking({ data, lang, busy, fictitious, onShipment, onRefresh }: { data: OrderData; lang: Language; busy: boolean; fictitious: boolean; onShipment: () => void; onRefresh: () => void }) {
  const t = orderMessages[lang]; const state = data.commercial; const action = nextAction(state); const amount = data.quote?.snapshot.checkout?.final_payable_minor;
  const restricted = state.payment_status === 'restricted';
  const hint = action === 'received' ? t.receivedHint : action === 'declared' ? t.declaredHint : action === 'restricted' ? t.restrictedHint : t.dispatchHint;
  return <div className="order-tracking"><section className="order-tracking-hero" aria-live="polite"><p className="eyebrow">{t.nextAction}</p><h2>{fictitious && action === 'dispatch' ? t.paid : t[action === 'payment' ? 'payment' : action]}</h2><p>{fictitious && action === 'dispatch' ? t.testNext : hint}</p>
    {!restricted && canDeclareShipment(state) && !state.shipment_declarations.length && !state.parcel_receipts.length && <button className={fictitious ? 'button button-outline' : 'button button-dark'} disabled={busy} onClick={onShipment}>{t.declare}{fictitious ? ' · TEST' : ''}</button>}
    {state.financial_restrictions?.map(reason => <p key={reason}>{commercialMessages[lang][reason as keyof typeof commercialMessages[Language]] ?? t.restrictedHint}</p>)}
  </section>{state.indicators.filter(value => ['manual_review_required', 'dispatch_deadline_passed', 'dispatch_deadline_approaching'].includes(value)).map(value => <p key={value} className="order-feedback" role="status">{commercialMessages[lang][value as keyof typeof commercialMessages[Language]]}</p>)}<dl className="order-tracking-facts"><div><dt>{t.count}</dt><dd>{data.item.card_count}</dd></div><div><dt>{t.service}</dt><dd>{[...new Set(data.quote?.snapshot.lines.map(line => line.tier_name[lang]) ?? [])].join(' / ') || t.unavailable}</dd></div><div><dt>{t.paidAmount}</dt><dd>{typeof amount === 'number' ? money(amount, lang) : t.unavailable}</dd></div><div><dt>{t.deadline}</dt><dd>{state.dispatch_deadline ? formatDate(state.dispatch_deadline, lang) : t.unavailable}</dd></div></dl>
    <section className="order-timeline"><h3>{t.progress}</h3><ol><li data-complete="true"><strong>{t.paid}</strong><span>{state.verified_payment_at ? formatDate(state.verified_payment_at, lang) : t.unavailable}</span></li><li data-complete={state.shipment_declarations.length > 0}><strong>{t.declared}</strong><span>{state.shipment_declarations.length ? formatDate(state.shipment_declarations[0].recorded_at, lang) : '—'}</span></li><li data-complete={state.parcel_receipts.length > 0}><strong>{t.received}</strong><span>{state.parcel_receipts.length ? formatDate(state.parcel_receipts[0].received_at, lang) : '—'}</span></li><li><strong>{t.processing}</strong><span>{t.unavailable}</span></li></ol><p>{t.noProduction}</p></section>
    <details><summary>{t.cardsDetails}</summary><ServiceList data={data} lang={lang} /></details>
    {data.quote && <details><summary>{t.quoteDetails}</summary><QuoteBreakdown quote={data.quote} lang={lang} /></details>}
    <details><summary>{t.shipment}</summary><ReturnAddress order={data.order} /><p>{t.duePolicy}</p>{data.order.inbound_receiving_address && <p>{data.order.inbound_receiving_address}</p>}<p>{t.shipmentHint}</p>{state.shipment_declarations.map(row => <p key={row.id}>{row.carrier} · {row.tracking} · {formatDate(row.recorded_at, lang)}</p>)}{state.parcel_receipts.map(row => <p key={row.id}>{row.reference} · {formatDate(row.received_at, lang)}</p>)}</details>
    <PaidOrderPanel item={data.item} lang={lang} refreshKey={0} supplementsOnly />
    <button className="text-link" disabled={busy} onClick={onRefresh}>{t.refresh}</button>
  </div>;
}

function ServiceList({ data, lang }: { data: OrderData; lang: Language }) {
  const snapshot = data.quote?.status === 'accepted' ? data.quote.snapshot.lines : data.order.grading?.lines;
  return <ul className="order-service-list">{data.item.entries.map(entry => { const line = snapshot?.find(row => row.entry_id === entry.id); return <li key={entry.id}><strong>{entry.card_name} <span>× {entry.quantity}</span></strong><span>{line?.tier_name[lang] ?? entry.processing_tier} · {line?.upgrades.map(u => u.name[lang]).join(', ') ?? entry.upgrade_ids.join(', ')}</span></li>; })}</ul>;
}
function ReturnAddress({ order }: { order: Order }) {
  const a = order.return_address;
  return a ? <address>{a.recipient}<br />{a.line1} {a.line2}<br />{a.postal_code} {a.city} · {a.country}</address> : null;
}
function ShipmentEditor({ data, lang, busy, act, onDirty }: { data: OrderData; lang: Language; busy: boolean; act: Action; onDirty: (value: boolean) => void }) {
  const t = commercialMessages[lang]; const key = useRef(crypto.randomUUID());
  return <form onChange={() => onDirty(true)} onSubmit={event => { event.preventDefault(); if (!canDeclareShipment(data.commercial)) return; const values = new FormData(event.currentTarget); const date = String(values.get('date') ?? ''); void act(`/${data.item.id}/shipment-declarations`, 'POST', { request_key: key.current, carrier: String(values.get('carrier') ?? ''), tracking: String(values.get('tracking') ?? ''), declared_dispatch_at: date ? new Date(date).toISOString() : null }); }}><p>{orderMessages[lang].shipmentHint}</p><fieldset disabled={busy || !canDeclareShipment(data.commercial)}><label>{t.carrier}<input name="carrier" maxLength={100} /></label><label>{t.tracking}<input name="tracking" maxLength={200} /></label><label>{t.declaredDate}<input name="date" type="datetime-local" /></label><button className="button button-dark">{t.save}</button></fieldset></form>;
}
