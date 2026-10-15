import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { checkoutMessages, parseEuro } from '../src/lib/checkout.ts';
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
