'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { submissionMessages, submissionRequest, type Submission } from '@/lib/submissions';
import { orderMessages } from '@/lib/order-flow';
import type { Language } from '@/lib/i18n';
import { Container } from './ui';
import { OrderWorkspace } from './order-workspace';

export function Submissions({ lang, identifier }: { lang: Language; identifier?: string }) {
  return identifier ? <OrderWorkspace key={identifier} lang={lang} identifier={identifier} /> : <OrderList lang={lang} />;
}
function OrderList({ lang }: { lang: Language }) {
  const t = submissionMessages[lang]; const flow = orderMessages[lang]; const router = useRouter();
  const [items, setItems] = useState<Submission[]>([]); const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [more, setMore] = useState(false); const [reload, setReload] = useState(0);
  useEffect(() => { let active = true; submissionRequest<Submission[]>('?limit=50').then(result => { if (active) { setItems(result); setMore(result.length === 50); setError(''); } }).catch(() => { if (active) setError(flow.error); }).finally(() => { if (active) setLoaded(true); }); return () => { active = false; }; }, [reload, flow.error]);
  async function create() { if (busy) return; setBusy(true); setError(''); try { const item = await submissionRequest<Submission>('', 'POST', {}); router.push(`/account/submissions/${item.id}?step=cards`); } catch { setError(flow.actionError); setBusy(false); } }
  async function next() { setBusy(true); try { const result = await submissionRequest<Submission[]>(`?offset=${items.length}&limit=50`); setItems(rows => [...rows, ...result]); setMore(result.length === 50); } catch { setError(flow.error); } finally { setBusy(false); } }
  return <section className="order-list" aria-busy={busy || !loaded}><div className="order-list-heading"><h2>{t.title}</h2><button className="button button-dark" disabled={busy} onClick={() => void create()}>+ {t.new}</button></div>
    {error && <p role="alert">{error} <button className="text-link" disabled={busy} onClick={() => setReload(n => n + 1)}>{flow.retry}</button></p>}
    {!loaded && <p role="status">{t.loading}</p>}{loaded && !items.length && !error && <p className="order-empty">{t.empty}</p>}
    <ul>{items.map(item => <li key={item.id}><div><span className="order-badge">{item.status === 'draft' ? t.draft : flow.confirmed}</span><h3>{item.reference}</h3><p>{item.card_count} {flow.count.toLowerCase()} · {new Date(item.created_at).toLocaleDateString(lang === 'FR' ? 'fr-FR' : 'en-GB')}</p></div><Link className="text-link" href={`/account/submissions/${item.id}`}>{item.status === 'draft' ? flow.resume : flow.open} →</Link></li>)}</ul>
    {more && <button className="button button-outline" disabled={busy} onClick={() => void next()}>{t.more}</button>}
  </section>;
}
export function SubmissionPage({ lang, identifier }: { lang: Language; identifier: string }) {
  const [selected, setSelected] = useState(lang);
  return <section className="section order-page"><Container><div className="order-language"><label>{selected === 'FR' ? 'Langue' : 'Language'}<select value={selected} onChange={event => setSelected(event.target.value === 'EN' ? 'EN' : 'FR')}><option value="FR">Français</option><option value="EN">English</option></select></label></div><Submissions lang={selected} identifier={identifier} /></Container></section>;
}
