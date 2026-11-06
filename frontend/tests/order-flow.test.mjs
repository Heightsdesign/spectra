import test from 'node:test';
import assert from 'node:assert/strict';
import { acceptedQuote, canAcceptQuote, canVisitStep, isTracking, nextAction, orderMessages, orderSteps, resumeStep } from '../src/lib/order-flow.ts';
import { payableAmount } from '../src/lib/checkout.ts';

const now = Date.parse('2026-11-05T12:00:00Z');
function fixture() {
  const order = { terms_accepted:false, stripe_test_only:true, readiness:{ready:true,states:[]}, grading:{development_only:true,stripe_test_only:true,tax_mode:'exempt'}, shipping:{status:'configured',charge_minor:500,service:{}},final_payable_minor:2500 };
  return { item:{status:'draft',entries:[{processing_tier:'standard',upgrade_ids:['classic']}],card_count:2},order,
    quote:{id:'q',status:'valid',expires_at:'2026-11-05T13:00:00Z',snapshot:{development_only:true,stripe_test_only:true,commercial_terms_version:'TEST',checkout:order}},
    commercial:{payment_status:'quote_not_accepted',accepted_quote_id:null,verified_payment_at:null,dispatch_deadline:null,charging_enabled:false,shipment_declarations:[],parcel_receipts:[]} };
}
test('resume uses saved server state for every stage, including interrupted accepted orders',()=>{
  const data=fixture();assert.equal(resumeStep(data),'quote');
  data.item.entries=[];assert.equal(resumeStep(data),'cards');
  data.item.entries=[{processing_tier:'',upgrade_ids:['classic']}];assert.equal(resumeStep(data),'service');
  data.item.entries[0].processing_tier='standard';data.order.readiness.ready=false;assert.equal(resumeStep(data),'return');
  data.item.status='submitted';assert.equal(resumeStep(data),'return');
  data.order.readiness.ready=true;assert.equal(resumeStep(data),'quote');
  data.commercial.accepted_quote_id='q';assert.equal(resumeStep(data),'payment');
});
test('URL navigation never unlocks a payment or permits an empty order to skip cards',()=>{
  const data=fixture();assert.equal(canVisitStep('payment',data),false);
  data.item.entries=[];for(const step of orderSteps.slice(1))assert.equal(canVisitStep(step,data),false);
  assert.equal(canVisitStep('cards',data),true);
});
test('confirmation and acceptance remain separate and require a current complete quote',()=>{
  const data=fixture();assert.equal(canAcceptQuote(data,now),false);
  data.item.status='submitted';assert.equal(canAcceptQuote(data,now),true);
  data.quote.snapshot.checkout.readiness.ready=false;assert.equal(canAcceptQuote(data,now),false);
});
for(const status of ['expired','invalidated','catalog_changed','superseded','unavailable','accepted'])test(`cannot accept a ${status} quote`,()=>{
  const data=fixture();data.item.status='submitted';data.quote.status=status;assert.equal(canAcceptQuote(data,now),false);
});
test('expiry and explicit terms remain mandatory even when navigation requests quote acceptance',()=>{
  const data=fixture();data.item.status='submitted';assert.equal(canAcceptQuote(data,now+3600001),false);
  delete data.quote.snapshot.commercial_terms_version;assert.equal(canAcceptQuote(data,now),false);
});
test('ordinary development estimates remain non-payable and non-acceptable',()=>{
  const data=fixture();data.item.status='submitted';data.quote.snapshot.stripe_test_only=false;data.order.grading.stripe_test_only=false;
  assert.equal(canAcceptQuote(data,now),false);assert.equal(payableAmount(data.order),null);
});
test('FICTIF TEST is explicitly marked in quote and checkout; exact amount is server supplied',()=>{
  const data=fixture();data.item.status='submitted';assert.equal(canAcceptQuote(data,now),true);assert.equal(payableAmount(data.order),2500);
  data.order.stripe_test_only=false;assert.equal(canAcceptQuote(data,now),false);assert.equal(payableAmount(data.order),null);
});
test('historical accepted grading-only quotes stay read-only with no invented payable total',()=>{
  const data=fixture();data.item.status='submitted';data.quote.status='accepted';delete data.quote.snapshot.checkout;
  data.order={readiness:{ready:false,states:['legacy_grading_terms']},grading:null,shipping:{status:'pending',charge_minor:null,service:null},final_payable_minor:null,terms_accepted:true};
  assert.equal(resumeStep(data),'payment');assert.equal(canAcceptQuote(data,now),false);assert.equal(payableAmount(data.order),null);
});
test('accepted snapshot is selected ahead of newer estimates and recovered by exact accepted identity',()=>{
  const valid={id:'new',status:'valid'},accepted={id:'old',status:'accepted'};
  assert.equal(acceptedQuote([valid,accepted]),accepted);assert.equal(acceptedQuote([valid,accepted],'old'),accepted);assert.equal(acceptedQuote([valid],'old'),null);
});
test('pending, error, cancellation and a browser return do not imply verified payment',()=>{
  const data=fixture();for(const status of ['creating','pending','action_required','failed','cancelled','expired','restricted']){data.commercial.payment_status=status;assert.equal(isTracking(data),false);}
  data.commercial.payment_status='verified';assert.equal(isTracking(data),true);
  data.commercial.payment_status='restricted';data.commercial.verified_payment_at='2026-11-05T12:00:00Z';assert.equal(isTracking(data),true);assert.equal(nextAction(data.commercial),'restricted');
});
test('shipment declaration, physical receipt and financial restrictions stay distinct',()=>{
  const state=fixture().commercial;state.payment_status='verified';assert.equal(nextAction(state),'dispatch');
  state.shipment_declarations=[{}];assert.equal(nextAction(state),'declared');
  state.parcel_receipts=[{}];assert.equal(nextAction(state),'received');state.payment_status='restricted';assert.equal(nextAction(state),'restricted');
});
test('both language dictionaries are complete and distinguish the two commitments',()=>{
  assert.deepEqual(Object.keys(orderMessages.FR).sort(),Object.keys(orderMessages.EN).sort());
  for(const lang of ['FR','EN']){for(const value of Object.values(orderMessages[lang]))assert.ok(value.trim());assert.notEqual(orderMessages[lang].confirm,orderMessages[lang].accept);}
  assert.match(orderMessages.FR.test,/FICTIF — STRIPE TEST/);assert.doesNotMatch(JSON.stringify(orderMessages),/SPECTRA|fiscalit\?/);
});
