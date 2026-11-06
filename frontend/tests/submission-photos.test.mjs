import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_PHOTO_BYTES,photoFileError,photoPath,uploadPhoto} from '../src/lib/submission-photos.ts';

test('optional photo picker limits formats and byte size',()=>{
 assert.equal(photoFileError({type:'image/jpeg',size:MAX_PHOTO_BYTES}),null);
 assert.equal(photoFileError({type:'image/png',size:1}),null);
 for(const type of ['image/tiff','image/gif','image/svg+xml','image/heic',''])assert.equal(photoFileError({type,size:1}),'invalid_photo');
 assert.equal(photoFileError({type:'image/png',size:0}),'invalid_photo');
 assert.equal(photoFileError({type:'image/png',size:MAX_PHOTO_BYTES+1}),'photo_too_large');
});

test('photo paths stay in the authenticated submission namespace',()=>{
 assert.equal(photoPath('submission','entry','image'),'/api/submissions/submission/entries/entry/photos/image');
 assert.equal(photoPath('a/b','entry'),'/api/submissions/a%2Fb/entries/entry/photos');
});

test('uploads retain CSRF, progress, errors, timeout and cancellation',async t=>{
 const previousFetch=globalThis.fetch;const previousXHR=globalThis.XMLHttpRequest;
 t.after(()=>{globalThis.fetch=previousFetch;globalThis.XMLHttpRequest=previousXHR;});
 class Request {
  static latest;
  constructor(){Request.latest=this;this.upload={};this.headers={};}
  open(method,path){this.method=method;this.path=path;}
  setRequestHeader(key,value){this.headers[key]=value;}
  send(body){this.body=JSON.parse(body);}
  abort(){this.onabort();this.onloadend();}
 }
 globalThis.XMLHttpRequest=Request;
 globalThis.fetch=async()=>Response.json({csrf_token:'csrf'});
 const progress=[];const promise=uploadPhoto('/private',{version:2,copy_number:2,side:'back'},n=>progress.push(n));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(Request.latest.headers['X-CSRF-Token'],'csrf');assert.equal(Request.latest.headers['X-Spectra-Client'],'1');
 assert.equal(Request.latest.method,'POST');assert.equal(Request.latest.timeout,120000);assert.equal(Request.latest.body.copy_number,2);
 Request.latest.upload.onprogress({lengthComputable:true,loaded:50,total:100});
 Request.latest.status=201;Request.latest.responseText=JSON.stringify({id:'draft',version:3});Request.latest.onload();
 assert.deepEqual(await promise,{id:'draft',version:3});assert.deepEqual(progress,[50]);
 const failed=uploadPhoto('/private',{},()=>{});await new Promise(resolve=>setImmediate(resolve));
 Request.latest.status=413;Request.latest.responseText=JSON.stringify({detail:'photo_too_large'});Request.latest.onload();
 await assert.rejects(failed,/photo_too_large/);
 const offline=uploadPhoto('/private',{},()=>{});await new Promise(resolve=>setImmediate(resolve));Request.latest.onerror();await assert.rejects(offline,/photo_unavailable/);
 const timeout=uploadPhoto('/private',{},()=>{});await new Promise(resolve=>setImmediate(resolve));Request.latest.ontimeout();await assert.rejects(timeout,/photo_unavailable/);
 const controller=new AbortController();const cancelled=uploadPhoto('/private',{},()=>{},controller.signal);await new Promise(resolve=>setImmediate(resolve));controller.abort();await assert.rejects(cancelled,/photo_cancelled/);
 globalThis.fetch=async()=>Response.json({},{status:401});
 await assert.rejects(uploadPhoto('/private',{},()=>{}),/authentication_required/);
});
