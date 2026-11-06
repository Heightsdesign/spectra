import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { checkoutMessages, parseEuro, customerDeliveryInput, returnServices, payableAmount } from '../src/lib/checkout.ts';
import { submissionRequest } from '../src/lib/submissions.ts';

for(const lang of ['FR','EN'])test(`${lang} checkout explains unresolved charges and inbound responsibility`,()=>{
 const t=checkoutMessages[lang];
 assert.deepEqual(Object.keys(t).sort(),Object.keys(checkoutMessages.EN).sort());
 for(const value of Object.values(t))assert.ok(value.length>0);
 for(const state of ['missing_return_address','unsupported_shipping_destination','shipping_price_pending','tax_configuration_pending','ready_for_checkout'])assert.ok(t[state]);
 assert.match(t.policy,lang==='FR'?/payez/:/pay/);
 assert.match(t.policy,lang==='FR'?/physique/:/physical/);
 assert.match(t.detailed,lang==='FR'?/face avant/:/front/);
});
test('declared EUR values parse exactly and reject ambiguous or malicious input',()=>{
 for(const [value,expected] of [['19.90',1990],['19,9',1990],['0',0],['999999.99',99999999],['.99',null],['-1',null],['1e3',null],['12.345',null],['NaN',null],['Infinity',null],['',null]])assert.equal(parseEuro(value),expected);
});
test('address requests use existing session-bound CSRF without submission-prefix confusion',async()=>{
 const calls=[];
 const request=async(url,options)=>{calls.push([url,options]);return Response.json(url==='/api/auth/csrf'?{csrf_token:'session-token'}:{id:'address'});};
 assert.deepEqual(await submissionRequest('/one','PUT',{version:1},request,'/api/addresses'),{id:'address'});
 assert.equal(calls[0][0],'/api/auth/csrf');
 assert.equal(calls[1][0],'/api/addresses/one');
 assert.equal(calls[1][1].headers['X-CSRF-Token'],'session-token');
 assert.equal(calls[1][1].cache,'no-store');
});
test('official catalog is non-publishable until tax validation, with no fabricated return rates',async()=>{
 const catalog=JSON.parse(await readFile(new URL('../../backend/pricing/spectra-v1.json',import.meta.url),'utf8'));
 const shipping=JSON.parse(await readFile(new URL('../../backend/pricing/shipping-unconfigured.json',import.meta.url),'utf8'));
 assert.equal(catalog.tax_mode,'pending');assert.equal(catalog.tax_validation_reference,null);
 assert.deepEqual(catalog.volume_prices.map(p=>[p.min_quantity,p.unit_price_minor]),[[1,1990],[5,1790],[10,1690]]);
 assert.deepEqual(catalog.discounts,[]);
 assert.deepEqual(shipping.services,{});assert.equal(shipping.receiving_address,null);
});

test('customer preparation saves address/value without parcel or hidden service defaults',()=>{
 const data=new FormData();data.set('address','address-1');data.set('declared','1250,50');data.set('weight_g','999');data.set('length_mm','250');
 assert.deepEqual(customerDeliveryInput(data,4),{version:4,address_id:'address-1',declared_value_minor:125050});
 data.set('service','verified-service');assert.equal(customerDeliveryInput(data,4).service_id,'verified-service');
 data.set('service','');assert.equal(customerDeliveryInput(data,4).service_id,null);
 data.set('declared','');assert.equal(customerDeliveryInput(data,4).declared_value_minor,null);
 data.set('declared','1e3');assert.throws(()=>customerDeliveryInput(data,4),/invalid_input/);
});

test('shipping selection is limited to configured destination services',()=>{
 const order={available_services:[{id:'fr',countries:['FR']},{id:'gb',countries:['GB']}]};
 const addresses=[{id:'paris',country:'FR'},{id:'tokyo',country:'JP'}];
 assert.deepEqual(returnServices(order,addresses,'paris').map(s=>s.id),['fr']);
 assert.deepEqual(returnServices(order,addresses,'tokyo'),[]);
});

test('development, missing shipping and unresolved tax never display a payable amount',()=>{
 const ready={grading:{development_only:false,tax_mode:'inclusive'},readiness:{ready:true,states:['ready_for_checkout']},shipping:{status:'configured',charge_minor:100,service:{name:{FR:'TEST',EN:'TEST'}}},final_payable_minor:2100};
 assert.equal(payableAmount(ready),2100);
 assert.equal(payableAmount({...ready,grading:{development_only:true}}),null);
 assert.equal(payableAmount({...ready,grading:{tax_mode:'pending'}}),null);
 assert.equal(payableAmount({...ready,readiness:{ready:false,states:[]}}),null);
 assert.equal(payableAmount({...ready,readiness:{ready:true,states:['development_rates']}}),null);
 assert.equal(payableAmount({...ready,shipping:{status:'pending',charge_minor:null,service:null}}),null);
 assert.equal(payableAmount({...ready,final_payable_minor:null}),null);
});


test('fictitious TEST payable requires both server snapshot markers; ordinary development remains blocked',()=>{
 const order={readiness:{ready:true,states:['ready_for_checkout']},grading:{development_only:true,stripe_test_only:true,tax_mode:'exempt'},shipping:{status:'configured',charge_minor:500,service:{}},stripe_test_only:true,final_payable_minor:2500};
 assert.equal(payableAmount(order),2500);
 assert.equal(payableAmount({...order,stripe_test_only:false}),null);
 assert.equal(payableAmount({...order,grading:{...order.grading,stripe_test_only:false}}),null);
 assert.equal(payableAmount({...order,readiness:{ready:false,states:['development_rates']}}),null);
});
