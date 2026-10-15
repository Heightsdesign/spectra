import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { componentModule } from './tsx-render.mjs';
import { canonicalScan,labelReferences,labelCopy,labelPdf,labelError,QR_PREFIX } from '../src/lib/physical-labels.ts';

const { PhysicalLabelsPanel,CardLabelActions }=await import(await componentModule('../src/components/physical-labels.tsx'));
const reference='PC-'+'A'.repeat(32);
test('versioned QR and keyboard scanner suffix preserve the complete identity',()=>{
  for(const value of [reference.toLowerCase()+'\r\n',QR_PREFIX+reference+'\n','\t'+QR_PREFIX.toLowerCase()+reference.toLowerCase()]) assert.equal(canonicalScan(value),reference);
  for(const bad of ['PC-123','SP:PC:2:'+reference,'https://example.invalid/'+reference,reference.slice(0,8)+'\n'+reference.slice(8),'PC-'+'Z'.repeat(32)]) assert.throws(()=>canonicalScan(bad));
});
test('batch ordering deduplicates complete identifiers and bounds the selection',()=>{
  const other='PC-'+'B'.repeat(32);
  assert.deepEqual(labelReferences([other,reference,reference]),[reference,other]);
  assert.throws(()=>labelReferences([]),/empty_selection/);
  assert.throws(()=>labelReferences(Array(251).fill(reference)),/batch_limit/);
  assert.equal(labelReferences(Array.from({length:250},(_,i)=>'PC-'+i.toString(16).padStart(32,'0'))).length,250);
});
test('FR/EN cover printing, reprinting, previews, calibration and physical limitations',()=>{
  assert.deepEqual(Object.keys(labelCopy.FR).sort(),Object.keys(labelCopy.EN).sort());
  for(const language of ['FR','EN']) for(const text of Object.values(labelCopy[language])) assert.ok(text.length);
});
test('frozen-card print actions are independent of locked reconciliation fieldsets',()=>{
  for(const language of ['FR','EN']) {
    const html=renderToStaticMarkup(createElement(PhysicalLabelsPanel,{submissionId:'submission',references:[reference],language},createElement(CardLabelActions,{reference})));
    assert.ok(html.includes(labelCopy[language].print));assert.ok(html.includes(labelCopy[language].reprint));
    assert.ok(html.includes(labelCopy[language].all));assert.ok(html.includes(labelCopy[language].calibration));
    assert.match(html,/type="checkbox"/);assert.match(html,/role="status" aria-live="polite"/);
    assert.doesNotMatch(html,/<fieldset|window\.print/);
  }
});
test('batch PDF requests retain Origin/CSRF convention and send only references/profile',async()=>{
  const calls=[];
  const request=async(url,options)=>{calls.push({url,options});return url.endsWith('/csrf')?Response.json({csrf_token:'session-bound'}):new Response('%PDF-fixture',{headers:{'Content-Type':'application/pdf'}});};
  const blob=await labelPdf('/submissions/id/pdf',{references:[reference],profile:'50x30'},request);
  assert.equal(await blob.text(),'%PDF-fixture');assert.equal(calls.length,2);
  assert.equal(calls[1].url,'/internal/labels/submissions/id/pdf');
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'session-bound');assert.equal(calls[1].options.headers['X-Spectra-Client'],'1');
  assert.equal(calls[1].options.method,'POST');assert.equal(calls[1].options.cache,'no-store');
  assert.deepEqual(JSON.parse(calls[1].options.body),{references:[reference],profile:'50x30'});
});
test('individual/calibration PDFs are uncached reads and unsuccessful responses never become previews',async()=>{
  let calls=0;
  await labelPdf('/calibration/pdf?profile=70x40',undefined,async(url,options)=>{calls++;assert.equal(options.method,'GET');assert.equal(options.cache,'no-store');return new Response('%PDF',{headers:{'Content-Type':'application/pdf'}});});
  assert.equal(calls,1);
  await assert.rejects(labelPdf('/cards/id/pdf',undefined,async()=>Response.json({detail:'staff_required'},{status:403})),/staff_required/);
  await assert.rejects(labelPdf('/cards/id/pdf',undefined,async()=>Response.json({})),/label_error/);
  calls=0;
  await assert.rejects(labelPdf('/submissions/id/pdf',{references:[reference],profile:'50x30'},async()=>{calls++;return Response.json({},{status:401});}),/authentication_required/);
  assert.equal(calls,1);
  assert.equal(labelError(new Error('batch_limit'),'FR'),labelCopy.FR.limit);
});
