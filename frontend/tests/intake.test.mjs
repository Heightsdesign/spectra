import test from 'node:test';
import assert from 'node:assert/strict';
import { intakeCopy, intakeStates, intakeErrors, intakeEvents, intakeRequest } from '../src/lib/intake.ts';

test('intake French and English cover the same workflow and states',()=>{
  assert.deepEqual(Object.keys(intakeCopy.FR).sort(),Object.keys(intakeCopy.EN).sort());
  assert.deepEqual(Object.keys(intakeStates.FR).sort(),Object.keys(intakeStates.EN).sort());
  for (const dictionary of [intakeErrors,intakeEvents]) assert.deepEqual(Object.keys(dictionary.FR).sort(),Object.keys(dictionary.EN).sort());
  for(const lang of ['FR','EN']) for(const text of Object.values(intakeCopy[lang])) assert.ok(text.length);
});
test('staff mutations use internal namespace and session CSRF, preserve idempotency key',async()=>{
  const calls=[];
  const payload={request_key:'stable-retry-key',parcel_id:'parcel'};
  const request=async(url,options)=>{ calls.push({url,options}); return new Response(JSON.stringify(url.endsWith('/csrf')?{csrf_token:'session-bound'}:{id:'physical-card'})); };
  assert.deepEqual(await intakeRequest('/submissions/id/cards',payload,request),{id:'physical-card'});
  assert.equal(calls[0].url,'/api/auth/csrf');
  assert.equal(calls[1].url,'/internal/intake/submissions/id/cards');
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'session-bound');
  assert.equal(calls[1].options.headers['X-Spectra-Client'],'1');
  assert.deepEqual(JSON.parse(calls[1].options.body),payload);
  assert.equal(calls[1].options.cache,'no-store');
});
test('failed CSRF prevents staff mutation and authorization errors propagate',async()=>{
  let count=0;
  await assert.rejects(intakeRequest('/submissions/id/cards',{},async()=>{count++;return new Response('{}',{status:401});}),/authentication_required/);
  assert.equal(count,1);
  for(const [status,detail] of [[401,'authentication_required'],[403,'staff_required'],[409,'quantity_unreconciled']]) {
    await assert.rejects(intakeRequest('/submissions',undefined,async()=>new Response(JSON.stringify({detail}),{status})),new RegExp(detail));
  }
});
