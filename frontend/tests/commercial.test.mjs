import assert from 'node:assert/strict';
import test from 'node:test';
import { checkoutInput, canDeclareShipment, commercialMessages, supplementaryConsent } from '../src/lib/commercial.ts';
import { payableAmount } from '../src/lib/checkout.ts';
import { compatible } from '../src/lib/pricing.ts';
import { submissionRequest } from '../src/lib/submissions.ts';

const state={charging_enabled:false,payment_status:'awaiting_payment',verified_payment_at:null,dispatch_deadline:null,indicators:['awaiting_verified_payment'],shipment_declarations:[],parcel_receipts:[]};
test('Stripe status labels are readable and complete in French and English',()=>{
 assert.equal(commercialMessages.FR.cancelled,'Tentative annulée');
 assert.equal(commercialMessages.EN.cancelled,'Attempt cancelled');
 for(const lang of ['FR','EN']) for(const key of ['creating','pending','action_required','failed','cancelled','expired','verified','restricted','refunded','partially_refunded','commercial_hold','dispute_review','financial_review']) {
  const label=commercialMessages[lang][key];assert.ok(label?.trim());assert.doesNotMatch(label,/[?\uFFFD]|Ã|â€|Â/);
 }
});
test('acceptance cannot enable customer dispatch or establish a deadline',()=>{
 assert.equal(canDeclareShipment(state),false);
 assert.equal(canDeclareShipment({...state,payment_status:'quote_not_accepted'}),false);
 assert.equal(canDeclareShipment({...state,payment_status:'verified'}),false);
 assert.equal(canDeclareShipment({...state,payment_status:'verified',verified_payment_at:'2026-11-03T10:00:00Z',dispatch_deadline:'2026-12-03T10:00:00Z'}),true);
});
test('late payment-backed dispatch is not represented as cancellation or forfeiture',()=>{
 const late={...state,payment_status:'verified',verified_payment_at:'2026-11-03T10:00:00Z',dispatch_deadline:'2026-12-03T10:00:00Z',indicators:['dispatch_deadline_passed']};
 assert.equal(canDeclareShipment(late),true);
 for(const lang of ['FR','EN']){assert.ok(commercialMessages[lang].expectation);assert.ok(commercialMessages[lang].unverified);assert.ok(commercialMessages[lang].paymentUnavailable);}
 assert.deepEqual(Object.keys(commercialMessages.FR).sort(),Object.keys(commercialMessages.EN).sort());
});
test('supplement acceptance submits consent only to its exact existing-order quote',async()=>{
 assert.throws(()=>supplementaryConsent(false),/explicit_terms_required/);
 let sent;
 await submissionRequest('/order-id/supplementary-quotes/quote-id/accept','POST',supplementaryConsent(true),async(url,options)=>{
  if(url.endsWith('/csrf'))return Response.json({csrf_token:'test-only'});
  sent={url,options};return Response.json({status:'accepted',payment_status:'awaiting_payment'});
 });
 assert.equal(sent.url,'/api/submissions/order-id/supplementary-quotes/quote-id/accept');
 assert.deepEqual(JSON.parse(sent.options.body),{accept_terms:true});
 assert.equal(sent.options.headers['X-CSRF-Token'],'test-only');
});
test('missing shipping or terms readiness cannot display a payable amount',()=>{
 const order={grading:{development_only:false,tax_mode:'pending',per_service_tax:true},shipping:{status:'configured',charge_minor:1234,service:{name:{EN:'TEST'}}},readiness:{ready:true,states:['ready_for_checkout']},final_payable_minor:5834};
 assert.equal(payableAmount(order),5834);
 assert.equal(payableAmount({...order,readiness:{ready:false,states:['commercial_terms_pending']}}),null);
 assert.equal(payableAmount({...order,shipping:{...order.shipping,charge_minor:null}}),null);
 assert.equal(payableAmount({...order,final_payable_minor:1.1}),null);
});
test('UI accepts configured service IDs without assuming legacy names and rejects disabled IDs',()=>{
 const catalog={tiers:{'approved-test-service':{available:true}},groups:{label:{min_selected:1,max_selected:1}},upgrades:{classic:{available:true,group:'label',allowed_tiers:null,incompatible_with:[]}}};
 assert.equal(compatible(catalog,'approved-test-service',['classic']),true);
 assert.equal(compatible(catalog,'standard',['classic']),false);
 assert.equal(compatible({...catalog,tiers:{'approved-test-service':{available:false}}},'approved-test-service',['classic']),false);
});

test('Checkout sends only the accepted quote identity and retains CSRF protection',async()=>{
 let sent;
 await submissionRequest('/order-id/stripe-checkout','POST',checkoutInput('accepted-quote'),async(url,options)=>{
  if(url.endsWith('/csrf'))return Response.json({csrf_token:'test-only'});
  sent={url,options};return Response.json({url:'https://checkout.stripe.com/c/pay/TEST',status:'pending'});
 });
 assert.deepEqual(JSON.parse(sent.options.body),{quote_id:'accepted-quote'});
 assert.equal(sent.options.headers['X-CSRF-Token'],'test-only');
});
test('pending, failed, action-required and restricted payment cannot enable shipment',()=>{
 for(const payment_status of ['creating','pending','failed','expired','cancelled','action_required','restricted']){
  assert.equal(canDeclareShipment({...state,payment_status,verified_payment_at:'2026-11-03T10:00:00Z',dispatch_deadline:'2026-12-03T10:00:00Z'}),false);
  for(const lang of ['FR','EN'])assert.ok(commercialMessages[lang][payment_status]);
 }
});
