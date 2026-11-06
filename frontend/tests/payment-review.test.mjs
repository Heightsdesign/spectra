import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { componentModule } from './tsx-render.mjs';
import { canStartCheckout, needsPaymentReview, paymentStatusLabel, canDeclareShipment } from '../src/lib/commercial.ts';

const { OrderPayment } = await import(await componentModule('../src/components/order-payment.tsx'));
const review = { payment_status: 'action_required', payment_review_required: true, charging_enabled: false,
  verified_payment_at: null, dispatch_deadline: null, indicators: [], shipment_declarations: [], parcel_receipts: [] };
const quote = { id: 'accepted-test-quote', status: 'accepted', created_at: '2026-11-06T10:00:00Z',
  expires_at: '2026-11-06T11:00:00Z', snapshot: { lines: [], subtotal_minor: 2000, discount_minor: 0,
    net_minor: 2000, tax_minor: 0, total_minor: 2000, tax_description: { FR: 'TEST', EN: 'TEST' },
    checkout: { readiness: { ready: true, states: [] }, shipping: { charge_minor: 500, service: null },
      final_payable_minor: 2500 } } };

for (const lang of ['FR', 'EN']) {
  test(`completed Checkout renders SELBY review and refresh without payment/resume controls (${lang})`, () => {
    const html = renderToStaticMarkup(createElement(OrderPayment, { data: { commercial: review, quote }, lang,
      busy: false, onPay() { assert.fail('render must not initiate payment'); }, onRefresh() {} }));
    assert.match(html, /SELBY/);
    assert.match(html, lang === 'FR' ? /vérification par SELBY nécessaire/ : /SELBY verification required/);
    assert.match(html, lang === 'FR' ? /Actualiser/ : /Refresh/);
    assert.doesNotMatch(html, /reprendre|resume|onPay|client_secret/i);
    assert.equal((html.match(/<button/g) ?? []).length, 1);
    assert.doesNotMatch(paymentStatusLabel(review, lang), /[?\uFFFD]/);
  });
}

test('review prevents resuming even with stale charging_enabled and never enables dispatch', () => {
  assert.equal(needsPaymentReview(review), true);
  assert.equal(canStartCheckout({ ...review, charging_enabled: true }), false);
  assert.equal(canDeclareShipment(review), false);
});

test('open challenge still permits Checkout and later success replaces review presentation', () => {
  const open = { ...review, payment_review_required: false, charging_enabled: true };
  assert.equal(canStartCheckout(open), true);
  assert.match(paymentStatusLabel(open, 'EN'), /resume Checkout/);
  for (const payment_status of ['verified', 'restricted']) {
    const final = { ...review, payment_status };
    assert.equal(needsPaymentReview(final), false);
    assert.doesNotMatch(paymentStatusLabel(final, 'EN'), /SELBY verification required/);
  }
});
