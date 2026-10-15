import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFile } from 'node:fs/promises';
import { componentModule } from './tsx-render.mjs';
import { customerOperationsCopy, customerOperationsError, customerOperationsRequest,
  customerProfileHref, intakeDetailHref, normalizeCardReference, validCardReference } from '../src/lib/customer-operations.ts';

const { CustomerDirectoryTable, CustomerAccount, CustomerHistory, CardTraceResult, OperationsFeedback, CustomerDirectory, PhysicalCardLookup } =
  await import(await componentModule('../src/components/customer-operations.tsx'));
const customer = { id: '9eead62a-5b9d-4329-aa73-602739791cc4', first_name: 'Claire', last_name: 'Collector',
  email: 'claire@example.invalid', status: 'active', created_at: '2026-10-14T10:00:00Z', email_verified: true,
  password_hash: 'DO-NOT-RENDER-PASSWORD', saved_addresses: [], addresses_truncated: false };
const address = { id: 'address-fixture', recipient: 'Shipment recipient', line1: '1 Example Street', line2: '', city: 'Paris',
  postal_code: '75001', country: 'FR', phone: '+33123456789', instructions: 'Shipment instructions' };
const submission = { id: 'submission-fixture', reference: 'SP-FIXTURE', status: 'submitted', created_at: customer.created_at,
  confirmed_at: customer.created_at, declared_quantity: 36, intake_status: 'reconciled', return_address: address, return_address_source: 'accepted_snapshot' };
const trace = { card: { id:'card-fixture', reference:'PC-'+'A'.repeat(32), status:'matched' }, parcel:{id:'parcel-fixture',reference:'PI-FIXTURE'},
  submission, customer, declared_entry:{id:'entry-fixture',card_name:'Collector card',game:'pokemon',expansion:'Example set',card_number:'1/102',language:'FR'} };
const render = (component, props) => renderToStaticMarkup(createElement(component, props));

test('customer operations FR/EN dictionaries cover all workflows', () => {
  assert.deepEqual(Object.keys(customerOperationsCopy.FR).sort(), Object.keys(customerOperationsCopy.EN).sort());
  for (const language of ['FR','EN']) for (const text of Object.values(customerOperationsCopy[language])) assert.ok(text.length > 0);
});
test('directory rows navigate by reference and expose only necessary list fields', async () => {
  const html = render(CustomerDirectoryTable, { items:[customer], language:'FR' });
  assert.ok(html.includes(`href="${customerProfileHref(customer.id)}"`));
  assert.match(html, /Claire Collector/);
  assert.match(html, /claire@example\.invalid/);
  assert.match(html, /scope="row"/);
  assert.match(html, /role="region"[^>]+tabindex="0"/);
  assert.doesNotMatch(html, /DO-NOT-RENDER-PASSWORD/);
  for (const path of ['customers/page.tsx','customers/[customerId]/page.tsx','cards/page.tsx','submissions/[submissionId]/page.tsx'])
    await readFile(new URL('../src/app/admin/'+path, import.meta.url));
});
test('account detail separates shipment recipient phone from account contact and escapes text', () => {
  for (const language of ['FR','EN']) {
    const html = render(CustomerAccount, { customer:{...customer,first_name:'<script>private</script>',saved_addresses:[address]},language });
    const t = customerOperationsCopy[language];
    assert.ok(html.includes(t.email));
    assert.ok(html.includes(t.noAccountPhone));
    assert.ok(html.includes(t.phone));
    assert.match(html, /Shipment recipient/);
    assert.match(html, /\+33123456789/);
    assert.match(html, /&lt;script&gt;private&lt;\/script&gt;/);
    assert.doesNotMatch(html, /<script>private|DO-NOT-RENDER-PASSWORD/);
  }
});
test('history distinguishes accepted snapshots, current selections, legacy and draft submissions', () => {
  for (const language of ['FR','EN']) {
    const t = customerOperationsCopy[language];
    const html = render(CustomerHistory, {language,items:[submission,{...submission,id:'draft',status:'draft',return_address_source:'current_selection'},
      {...submission,id:'legacy',return_address:null,return_address_source:'not_recorded'}]});
    for (const label of [t.acceptedSnapshot,t.currentSelection,t.notRecorded,t.submissionStatus]) assert.ok(html.includes(label));
    assert.ok(html.includes(`href="${intakeDetailHref(submission.id)}"`));
    assert.ok(!html.includes(intakeDetailHref('draft')));
    assert.match(html, /36/);
  }
});
test('physical card trace includes customer, parcel, submission and declared card with direct links', () => {
  const html = render(CardTraceResult,{trace,language:'EN'});
  for (const text of [trace.card.reference,trace.parcel.reference,submission.reference,customer.email,'Collector card']) assert.ok(html.includes(text));
  for (const href of [customerProfileHref(customer.id),intakeDetailHref(submission.id)]) assert.ok(html.includes(`href="${href}"`));
  assert.match(html,/does not establish legal ownership/);
  assert.doesNotMatch(html,/DO-NOT-RENDER-PASSWORD/);
  assert.ok(render(CardTraceResult,{trace:{...trace,declared_entry:null},language:'FR'}).includes(customerOperationsCopy.FR.unidentified));
});
test('lookup validates exact PC references and normalizes case without accepting partial searches', () => {
  const reference = 'PC-'+'a'.repeat(32);
  assert.equal(normalizeCardReference(' '+reference+' '),reference.toUpperCase());
  assert.ok(validCardReference(reference));
  for (const bad of ['PC-','PC-123','SP-'+'A'.repeat(32),'PC-'+'Z'.repeat(32),'PC-'+'A'.repeat(33),'%']) assert.equal(validCardReference(bad),false);
});
test('read-only requests use the internal namespace, abort signals and no-store', async () => {
  const controller = new AbortController();
  let call;
  const result = await customerOperationsRequest('/customers?search=claire',async (url,options) => {
    call={url,options}; return Response.json({items:[customer]});
  },controller.signal);
  assert.equal(call.url,'/internal/customer-operations/customers?search=claire');
  assert.equal(call.options.cache,'no-store');
  assert.equal(call.options.signal,controller.signal);
  assert.equal(call.options.body,undefined);
  assert.equal(call.options.method,undefined);
  assert.deepEqual(result.items,[customer]);
});
test('staff denials and unknown card errors remain explicit and localized', async () => {
  for (const code of ['authentication_required','staff_required','card_not_found','trace_inconsistent','invalid_card_reference','customer_not_found']) {
    await assert.rejects(customerOperationsRequest('/cards/PC-fixture',async () => Response.json({detail:code},{status:403})),new RegExp(code));
    assert.notEqual(customerOperationsError(new Error(code),'FR'),customerOperationsCopy.FR.error);
  }
  assert.equal(customerOperationsError(new Error('database_secret'),'EN'),customerOperationsCopy.EN.error);
});
test('empty, loading and error UI have accessible live feedback in both languages', () => {
  for (const language of ['FR','EN']) {
    const t = customerOperationsCopy[language];
    assert.ok(render(OperationsFeedback,{language,empty:true}).includes(t.empty));
    assert.ok(render(OperationsFeedback,{language,loading:true}).includes(t.loading));
    const error = render(OperationsFeedback,{language,error:new Error('card_not_found'),retry:()=>{}});
    assert.ok(error.includes(t.cardNotFound) && error.includes(t.retry));
    assert.match(error,/role="status" aria-live="polite"/);
    assert.ok(render(CustomerDirectory,{initialLanguage:language}).includes(t.loading));
    assert.ok(render(PhysicalCardLookup,{initialLanguage:language}).includes(t.lookupEmpty));
  }
});
test('navigation URL builders never put email or name into destinations', () => {
  assert.equal(customerProfileHref('x/y'),'/admin/customers/x%2Fy');
  assert.equal(intakeDetailHref('x?y'),'/admin/submissions/x%3Fy');
  assert.ok(!customerProfileHref(customer.id).includes(customer.email));
});
