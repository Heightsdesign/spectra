'use client';
import type { Language } from '@/lib/i18n';
import { payableAmount } from '@/lib/checkout';
import { money } from '@/lib/pricing';
import { canStartCheckout, needsPaymentReview, paymentStatusLabel } from '@/lib/commercial';
import { orderMessages, type OrderData } from '@/lib/order-flow';
import { QuoteBreakdown } from './pricing-panel';

export function OrderPayment({ data, lang, busy, onPay, onRefresh }: { data: OrderData; lang: Language; busy: boolean; onPay: () => void; onRefresh: () => void }) {
  const t = orderMessages[lang]; const { commercial, quote } = data; const amount = quote?.snapshot.checkout ? payableAmount(quote.snapshot.checkout) : null;
  const pending = ['creating', 'pending', 'action_required'].includes(commercial.payment_status);
  return <div className="order-payment"><p className="order-badge" role="status">{paymentStatusLabel(commercial, lang)}</p><p className="order-payment-amount">{amount === null ? t.undetermined : money(amount, lang)}</p>{!needsPaymentReview(commercial) && <p>{pending ? t.pendingHint : t.payHint}</p>}
    {canStartCheckout(commercial) && amount !== null ? <button className="button button-dark" disabled={busy} onClick={onPay}>{pending ? (lang === 'FR' ? 'Reprendre Stripe Checkout' : 'Resume Stripe Checkout') : t.pay}</button> : !needsPaymentReview(commercial) && <p>{pending ? t.pending : t.payUnavailable}</p>}
    <button className="text-link" disabled={busy} onClick={onRefresh}>{t.refresh}</button>{quote && <details><summary>{t.quoteDetails}</summary><QuoteBreakdown quote={quote} lang={lang} /></details>}
  </div>;
}

