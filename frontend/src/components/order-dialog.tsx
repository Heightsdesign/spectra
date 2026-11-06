'use client';
import { useEffect, useId, useRef, type ReactNode } from 'react';

/** Native modal isolation, keyboard containment and focus return. No nested forms. */
export function OrderDialog({ title, closeLabel, onClose, busy = false, children }: {
  title: string; closeLabel: string; onClose: () => void; busy?: boolean; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const nestedOpener = Boolean(opener?.closest('dialog'));
    dialog?.showModal();
    return () => { dialog?.close(); requestAnimationFrame(() => {
      if (opener?.isConnected) opener.focus();
      else if (!nestedOpener) document.querySelector<HTMLElement>('#order-step-heading')?.focus();
    }); };
  }, []);
  return <dialog ref={ref} className="order-dialog" aria-labelledby={titleId} aria-modal="true"
    onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const items = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')].filter(element => element.getClientRects().length > 0);
      const first = items[0], last = items.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    onClick={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <header><h2 id={titleId} tabIndex={-1}>{title}</h2><button type="button" className="order-icon-button" aria-label={closeLabel} disabled={busy} onClick={onClose}>×</button></header>
    <div className="order-dialog-content" aria-busy={busy}>{children}</div>
  </dialog>;
}
