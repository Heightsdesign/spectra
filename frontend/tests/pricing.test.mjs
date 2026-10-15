import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { compatible, money, ordered, pricingMessages } from '../src/lib/pricing.ts';
import { submissionRequest } from '../src/lib/submissions.ts';

const catalog=JSON.parse(await readFile(new URL('../../backend/pricing/development-example.json',import.meta.url),'utf8'));
for(const lang of ['FR','EN']) {
 test(`${lang} pricing messages cover quote lifecycle and payment exclusion`,()=>{
  assert.deepEqual(Object.keys(pricingMessages[lang]).sort(),Object.keys(pricingMessages.EN).sort());
  for(const value of Object.values(pricingMessages[lang]))assert.ok(value.length>0);
  assert.ok(pricingMessages[lang].payment);
  for(const status of ['valid','expired','invalidated','catalog_changed','accepted','superseded','unavailable'])assert.ok(pricingMessages[lang][status]);
 });
 test(`${lang} catalog has localized names and descriptions, no published turnaround`,()=>{
  for(const option of [...Object.values(catalog.tiers),...Object.values(catalog.upgrades)]) {assert.ok(option.name[lang]);assert.ok(option.description[lang]);}
  for(const tier of Object.values(catalog.tiers))assert.equal(tier.estimated_turnaround,null);
 });
}
test('EUR display follows French and English locales',()=>{
 assert.equal(money(12345,'EN'),'€123.45');
 assert.match(money(12345,'FR'),/123,45\s*€/);
 assert.equal(money(0,'EN'),'€0.00');
});
test('every tier accepts either initial label, never both',()=>{
 for(const tier of ['standard','express','priority'])for(const label of ['classic','detailed'])assert.equal(compatible(catalog,tier,[label]),true);
 assert.equal(compatible(catalog,'standard',['classic','detailed']),false);
 assert.equal(compatible(catalog,'standard',[]),false);
 assert.equal(compatible(catalog,'standard',['classic','classic']),false);
});
test('unavailable and unknown options are rejected by UI validation',()=>{
 const changed=structuredClone(catalog);changed.tiers.express.available=false;changed.upgrades.detailed.available=false;
 assert.equal(compatible(changed,'express',['classic']),false);
 assert.equal(compatible(changed,'standard',['detailed']),false);
 assert.equal(compatible(changed,'fake',['classic']),false);
 assert.equal(compatible(changed,'standard',['fake']),false);
});
test('future groups, incompatible options and tier restrictions need no new UI schema',()=>{
 const changed=structuredClone(catalog);
 changed.groups.extra={min_selected:0,max_selected:1};
 changed.upgrades.extra={...changed.upgrades.detailed,group:'extra',incompatible_with:['detailed'],allowed_tiers:['express']};
 assert.equal(compatible(changed,'express',['classic','extra']),true);
 assert.equal(compatible(changed,'standard',['classic','extra']),false);
 assert.equal(compatible(changed,'express',['detailed','extra']),false);
});
test('display order has a deterministic identifier tiebreaker',()=>{
 assert.deepEqual(ordered({z:{display_order:1},a:{display_order:1},first:{display_order:0}}).map(([id])=>id),['first','a','z']);
});
test('configuration requests carry identifiers and revision, never calculated prices',async()=>{
 let sent;
 await submissionRequest('/s/configuration','PATCH',{version:3,processing_tier:'express',upgrade_ids:['detailed']},async(url,options)=>{
  if(url.endsWith('/csrf'))return Response.json({csrf_token:'csrf'});
  sent=options;return Response.json({version:4});
 });
 assert.deepEqual(JSON.parse(sent.body),{version:3,processing_tier:'express',upgrade_ids:['detailed']});
 assert.equal(sent.headers['X-CSRF-Token'],'csrf');
});
test('acceptance explicitly records consent without payment parameters',async()=>{
 let sent;
 await submissionRequest('/s/quotes/q/accept','POST',{version:4,accept_terms:true},async(url,options)=>{
  if(url.endsWith('/csrf'))return Response.json({csrf_token:'csrf'});
  sent=options;return Response.json({status:'accepted'});
 });
 assert.deepEqual(JSON.parse(sent.body),{version:4,accept_terms:true});
});
test('expired quote errors remain server-authoritative',async()=>{
 await assert.rejects(submissionRequest('/s/quotes/q/accept','POST',{version:4,accept_terms:true},async url=>url.endsWith('/csrf')?Response.json({csrf_token:'csrf'}):Response.json({detail:'quote_stale'},{status:409})),/quote_stale/);
});
