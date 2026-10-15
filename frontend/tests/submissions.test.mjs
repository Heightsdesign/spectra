import test from 'node:test';
import assert from 'node:assert/strict';
import { submissionRequest, submissionMessages, games } from '../src/lib/submissions.ts';
for (const lang of ['FR','EN']) {
 test(`${lang} submission workflow messages`,()=>{
  for(const key of Object.keys(submissionMessages.EN)) assert.ok(submissionMessages[lang][key]);
  assert.notEqual(submissionMessages[lang].draft,submissionMessages[lang].submitted);
  assert.ok(submissionMessages[lang].warning.length>50);
 });
}
test('four supported games',()=>assert.equal(Object.keys(games).length,4));
test('writes request CSRF and send version',async()=>{
 const calls=[];
 const request=async(url,options)=>{calls.push([url,options]);return Response.json(url.includes('/csrf')?{csrf_token:'secret'}:{id:'draft'});};
 assert.deepEqual(await submissionRequest('/draft/confirm','POST',{version:3},request),{id:'draft'});
 assert.equal(calls[0][0],'/api/auth/csrf');
 assert.equal(calls[1][1].headers['X-CSRF-Token'],'secret');
 assert.equal(calls[1][1].headers['X-Spectra-Client'],'1');
 assert.equal(calls[1][1].body,'{"version":3}');
 assert.equal(calls[1][1].cache,'no-store');
});
test('reads do not fetch CSRF',async()=>{
 let count=0; await submissionRequest('', 'GET',undefined,async()=>{count++;return Response.json([]);});assert.equal(count,1);
});
test('stale edits surface conflicts',async()=>{
 await assert.rejects(submissionRequest('/draft','PATCH',{version:1},async url=>url.includes('/csrf')?Response.json({csrf_token:'x'}):Response.json({detail:'submission_conflict'},{status:409})),/submission_conflict/);
});
test('expired session blocks write',async()=>{
 let count=0;await assert.rejects(submissionRequest('','POST',{},async()=>{count++;return Response.json({},{status:401});}),/authentication_required/);assert.equal(count,1);
});
