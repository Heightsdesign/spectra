"use client";
import Link from 'next/link';
import { useRef, useState } from 'react';
import { useAdminLanguage } from './admin-language';
import { canonicalScan } from '@/lib/physical-labels';
import { inspectionRequest, inspectionError, InspectionError, type InspectionResult, type InspectionAction, type InspectionCommand } from '@/lib/inspection';

export function InspectionWorkstation({ initialLanguage }: { initialLanguage: 'FR' | 'EN' }) {
  const [language, setLanguage] = useAdminLanguage(initialLanguage);
  const fr = language === 'FR';
  const [scan, setScan] = useState('');
  const [data, setData] = useState<InspectionResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('');
  const pendingCommand = useRef<{ reference: string; payload: InspectionCommand } | null>(null);
  const inFlight = useRef(false);
  const scanInput = useRef<HTMLInputElement>(null);
  const labels: Record<string, string> = fr ? {
    start: 'Commencer l’inspection', pause: 'Confirmer la mise en attente', resume: 'Reprendre l’inspection',
    in_progress: 'En cours', paused: 'En pause', inspection_workstation: 'Poste d’inspection',
    inspection_hold_storage: 'Stockage en attente', secure_intake_storage: 'Stockage sécurisé de réception',
  } : {
    start: 'Start inspection', pause: 'Confirm pause and handover', resume: 'Resume inspection',
    in_progress: 'In progress', paused: 'Paused', inspection_workstation: 'Inspection workstation',
    inspection_hold_storage: 'Inspection hold storage', secure_intake_storage: 'Secure intake storage',
  };

  async function run(task: () => Promise<InspectionResult>, lookup = false) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await task();
      setData(result);
      if (lookup) {
        pendingCommand.current = null;
        setReason('');
      }
    } catch (e) {
      setError(e);
    } finally {
      inFlight.current = false;
      setBusy(false);
      scanInput.current?.focus();
      scanInput.current?.select();
    }
  }

  function perform(action: InspectionAction) {
    if (!data || busy) return;
    const source = data.inspection?.location ?? 'secure_intake_storage';
    const destination = action === 'pause' ? 'inspection_hold_storage' : 'inspection_workstation';
    const confirmation = `${data.card.reference}\n${labels[action]}\n${labels[source]} → ${labels[destination]}\n${fr ? 'Confirmer ce transfert physique ?' : 'Confirm this physical handover?'}`;
    if (!window.confirm(confirmation)) return;
    const payload: InspectionCommand = { action, reason: reason.trim(), version: data.inspection?.version ?? 0, request_key: crypto.randomUUID() };
    const pending = pendingCommand.current;
    if (pending?.reference === data.card.reference && pending.payload.action === action && pending.payload.reason === payload.reason && pending.payload.version === payload.version) {
      payload.request_key = pending.payload.request_key;
    }
    pendingCommand.current = { reference: data.card.reference, payload };
    void run(async () => {
      const result = await inspectionRequest('/' + data.card.reference + '/command', payload);
      pendingCommand.current = null;
      return result;
    });
  }

  async function acquire(file: File, side: 'front' | 'back', current: InspectionResult) {
    const bytes = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const sha256 = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
    const encoded = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    return inspectionRequest('/' + current.card.reference + '/images', {
      inspection_id: current.inspection!.id, version: current.inspection!.version,
      side, filename: file.name, data: encoded, sha256, reason: reason.trim(),
    });
  }

  const eligibility = data?.eligibility[data.inspection?.status === 'paused' ? 'resume' : data.inspection ? 'image' : 'start'];
  const action: InspectionAction = !data?.inspection ? 'start' : data.inspection.status === 'paused' ? 'resume' : 'pause';
  return <section className="container-shell intake-workspace inspection-workstation" aria-labelledby="inspection-title">
    <header className="intake-heading">
      <div><p className="eyebrow">SPECTRA / {fr ? 'Opérations internes' : 'Internal operations'}</p><h1 id="inspection-title">Inspection</h1></div>
      <label className="intake-language">{fr ? 'Langue' : 'Language'}<select value={language} onChange={e => setLanguage(e.target.value as 'FR' | 'EN')}><option value="FR">Français</option><option value="EN">English</option></select></label>
    </header>
    <p className="intake-help">{fr ? 'Un scan identifie la carte. Confirmez séparément toute prise en charge physique.' : 'Scanning identifies a card. Confirm physical custody separately.'}</p>
    <form className="inspection-search" onSubmit={e => {
      e.preventDefault();
      if (busy) return;
      setData(null);
      void run(() => inspectionRequest('/lookup?reference=' + encodeURIComponent(canonicalScan(scan))), true);
    }}>
      <label htmlFor="inspection-scan">{fr ? 'QR / référence PC complète' : 'QR / complete PC reference'}</label>
      <input ref={scanInput} id="inspection-scan" value={scan} onChange={e => setScan(e.target.value)} autoComplete="off" required autoFocus disabled={busy} />
      <button className="button button-dark" disabled={busy}>{fr ? 'Identifier' : 'Identify'}</button>
    </form>
    <div role="alert">{error ? inspectionError(error, language) : null}</div>
    <div role="status" aria-live="polite">{busy && (fr ? 'Chargement…' : 'Loading…')}</div>
    {data && <>
      <article className="intake-record inspection-identity">
        <p className="eyebrow">{fr ? 'Carte physique identifiée' : 'Identified physical card'}</p>
        <h2>{data.card.reference}</h2>
        <p>{data.entry ? `${data.entry.card_name} · ${data.entry.expansion} · ${data.entry.card_number} · ${data.entry.language}` : (fr ? 'Non identifiée' : 'Unidentified')}</p>
        <p><Link href={'/admin/submissions/' + data.submission.id}>{data.submission.reference}</Link> · <Link href={'/admin/customers/' + data.submission.customer_id}>{fr ? 'Profil client associé' : 'Associated customer profile'}</Link></p>
      </article>
      <div className="intake-record-grid">
        <article className="intake-record" aria-labelledby="inspection-eligibility">
          <h2 id="inspection-eligibility">{fr ? 'Éligibilité' : 'Eligibility'}</h2>
          <p className="intake-badge" data-testid="eligibility-status">{eligibility?.eligible ? (fr ? 'Autorisée' : 'Eligible') : (fr ? 'Bloquée' : 'Blocked')}</p>
          <ul>{eligibility?.reasons.map(r => <li key={r.code} data-reason={r.code}>{fr ? r.fr : r.en}</li>)}</ul>
          <p data-testid="inspection-status">{data.inspection ? labels[data.inspection.status] : (fr ? 'Non commencée' : 'Not started')}</p>
          <p>{data.inspection ? labels[data.inspection.location] : (fr ? 'Garde d’inspection non encore confirmée.' : 'Inspection custody has not yet been confirmed.')}</p>
          <label htmlFor="inspection-reason">{fr ? 'Motif opérationnel (obligatoire)' : 'Operational reason (required)'}</label>
          <input id="inspection-reason" maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} disabled={busy} />
          <button className="button button-dark" data-action={action} disabled={busy || !reason.trim() || !data.eligibility[action].eligible} onClick={() => perform(action)}>{labels[action]}</button>
        </article>
        <article className="intake-record" aria-labelledby="inspection-images">
          <h2 id="inspection-images">{fr ? 'Images originales' : 'Original images'}</h2>
          <p className="intake-help">{fr ? 'Étalonnage du scanner non validé. Chaque remplacement conserve les versions précédentes.' : 'Scanner calibration has not been validated. Replacement preserves all previous versions.'}</p>
          {(['front', 'back'] as const).map(side => <div key={side}>
            <label htmlFor={'inspection-' + side}>{side === 'front' ? (fr ? 'Recto' : 'Front') : (fr ? 'Verso' : 'Back')} · <span data-image-status={side}>{data.images.some(i => i.side === side) ? (fr ? 'Présente' : 'Present') : (fr ? 'Absente' : 'Missing')}</span></label>
            <input id={'inspection-' + side} type="file" accept="image/png,image/jpeg,image/tiff" disabled={busy || !reason.trim() || !data.eligibility.image.eligible} onChange={e => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (!file || !data.inspection) return;
              if (file.size > 25 * 1024 * 1024) { setError(new InspectionError('image_too_large')); return; }
              if (!window.confirm(`${data.card.reference}\n${side === 'front' ? (fr ? 'Recto' : 'Front') : (fr ? 'Verso' : 'Back')}\n${fr ? 'Associer une nouvelle version à cette carte ?' : 'Attach a new version to this card?'}`)) return;
              void run(() => acquire(file, side, data));
            }} />
          </div>)}
          <ul className="inspection-image-history">{data.images.map(image => <li key={image.id}>
            <a href={'/internal/inspection/' + data.card.reference + '/images/' + image.id} target="_blank" rel="noreferrer">{image.side === 'front' ? (fr ? 'Recto' : 'Front') : (fr ? 'Verso' : 'Back')} · v{image.version}</a>
            <details><summary>SHA-256</summary><code>{image.sha256}</code></details>
          </li>)}</ul>
        </article>
      </div>
      <article className="intake-record inspection-history" aria-labelledby="inspection-custody">
        <h2 id="inspection-custody">{fr ? 'Historique de garde' : 'Custody history'}</h2>
        {!data.custody.length && <p>{fr ? 'Aucun transfert d’inspection confirmé.' : 'No inspection handover confirmed.'}</p>}
        <ol>{data.custody.map(event => <li key={event.id}>
          <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString(fr ? 'fr-FR' : 'en-GB', { timeZone: 'UTC' })} UTC</time>
          <p>{labels[event.source]} → {labels[event.destination]} · {event.reason}</p>
          <small>{fr ? 'Opérateur' : 'Operator'}: {event.actor_id}</small>
        </li>)}</ol>
      </article>
    </>}
  </section>;
}
