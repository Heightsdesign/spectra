import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { componentModule } from './tsx-render.mjs';
import { displayCommercialText } from '../src/lib/commercial-display.ts';

const { QuoteBreakdown }=await import(await componentModule('../src/components/pricing-panel.tsx'));
const local=text=>({FR:text,EN:text});
function quote(){return {id:'historical-accepted',status:'accepted',created_at:'2026-11-05T12:00:00Z',expires_at:'2026-11-05T13:00:00Z',accepted_at:'2026-11-05T12:01:00Z',pricing_configuration_version:'historical-v1',snapshot:{development_only:true,stripe_test_only:true,currency:'EUR',commercial_terms_version:'FICTIF-TEST-v1',quantity:2,lines:[],subtotal_minor:2000,discount_minor:0,net_minor:2000,tax_minor:0,total_minor:2000,tax_mode:'exempt',tax_rate_bps:0,tax_description:local('Fiscalit? synth?tique TEST 0 %, sans valeur fiscale.'),discount:null,checkout:{stripe_test_only:true,grading:{development_only:true,stripe_test_only:true,tax_mode:'exempt'},readiness:{ready:true,states:['ready_for_checkout']},shipping:{status:'configured',charge_minor:500,service:{name:local('FICTIF ? STRIPE TEST : retour France'),coverage:local('Simulation uniquement : aucune couverture r?elle.'),exclusions:local('Aucun transport ni remboursement r?el. Ne pas envoyer de cartes.')}},final_payable_minor:2500,return_address:null}}};}
test('accepted quote rendering preserves snapshot identity, monetary values and terms',()=>{
  const value=quote(),before=JSON.stringify(value);const html=renderToStaticMarkup(createElement(QuoteBreakdown,{quote:value,lang:'FR'}));
  assert.equal(JSON.stringify(value),before);assert.match(html,/25,00/);assert.match(html,/historical-v1/);assert.match(html,/FICTIF — STRIPE TEST/);assert.match(html,/aucune couverture réelle/);assert.doesNotMatch(html,/fiscalit\?|couverture r\?elle/);
});
test('historical grading-only quote never presents its subtotal as a final payable amount',()=>{
  const value=quote();delete value.snapshot.checkout;const html=renderToStaticMarkup(createElement(QuoteBreakdown,{quote:value,lang:'FR'}));
  assert.match(html,/Sous-total grading/);assert.doesNotMatch(html,/Montant total payable/);assert.match(html,/20,00/);
});
test('display repairs are narrowly limited to known synthetic labels',()=>{
  assert.equal(displayCommercialText('Une carte ? Une note ?'),'Une carte ? Une note ?');
  assert.equal(displayCommercialText('FICTIF ? STRIPE TEST : retour France'),'FICTIF — STRIPE TEST : retour France');
});
