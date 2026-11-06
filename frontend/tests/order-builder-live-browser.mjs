// Explicit opt-in: real local portal/backend writes ONE fictional customer's order.
// Requires the PostgreSQL preflight guard. Never prints passwords, cookies or response bodies.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';

if(process.env.SELBY_LIVE_ORDER_BUILDER_TEST!=='1')throw Error('Explicit SELBY_LIVE_ORDER_BUILDER_TEST=1 is required');
const folder=resolve('.visual-review/order-builder-live');
const guard=JSON.parse(await readFile(resolve(folder,'guard.json'),'utf8'));
assert.equal(guard.database,'spectra');assert.equal(guard.auth_environment,'development');
assert.equal(guard.portal,'http://127.0.0.1:3000');assert.equal(guard.before_customer_orders,0);
assert.match(guard.email,/^client0[123]@selby\.test$/);
let password;
for(const line of (await readFile('../SELBY_LOCAL_TEST_CREDENTIALS.md','utf8')).split('\n')){
 const cells=line.split('|').slice(1,-1).map(value=>value.trim());
 if(cells.length===7&&cells[1]===guard.email&&/^[A-Za-z0-9_-]{43}$/.test(cells[2]))password=cells[2];
}
if(!password)throw Error('Fictional account credentials unavailable');
const origin=guard.portal;
let report;
try{report=JSON.parse(await readFile(resolve(folder,'progress.json'),'utf8'));}catch{report={email:guard.email,run:randomUUID().slice(0,8),ac:{},screenshots:[],requests:[],phase:'starting'};}
assert.equal(report.email,guard.email);
const save=()=>writeFile(resolve(folder,'progress.json'),JSON.stringify(report,null,2));
const phase=async value=>{report.phase=value;await save();console.log('Browser:',value);};
const profile=resolve(folder,'chrome-'+randomUUID());await mkdir(profile,{recursive:true});
const chrome=spawn(process.env.CHROME_PATH??'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--disable-save-password-bubble','--remote-debugging-port=18403',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
let socket,send,evaluate;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,label){for(let i=0;i<200;i++){try{if(await fn())return;}catch{}await delay(100);}throw Error('Timed out: '+label);}
try{
 let targets;await until(async()=>{targets=await(await fetch('http://127.0.0.1:18403/json/list')).json();return targets.some(t=>t.type==='page');},'Chrome startup');
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await once(socket,'open');let id=0;const pending=new Map();
 send=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;const timer=setTimeout(()=>{pending.delete(key);reject(Error('Browser command timed out'));},15000);pending.set(key,{resolve,reject,timer});socket.send(JSON.stringify({id:key,method,params}));});
 socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.id){const job=pending.get(message.id);if(!job)return;pending.delete(message.id);clearTimeout(job.timer);if(message.error)job.reject(Error('Browser command failed'));else job.resolve(message.result);}else if(message.method==='Network.requestWillBeSent'){
  const request=message.params.request;const url=new URL(request.url);if(url.origin===origin&&url.pathname.startsWith('/api/'))report.requests.push({method:request.method,path:url.pathname});
 }});
 evaluate=async expression=>{const response=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(response.exceptionDetails)throw Error('Browser expression failed');return response.result.value;};
 const click=async label=>{await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled)`),'enabled '+label);return evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled).click()`);};
 const setValue=(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Input unavailable');Object.getOwnPropertyDescriptor(e.tagName==='SELECT'?HTMLSelectElement.prototype:e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
 const get=path=>evaluate(`fetch(${JSON.stringify(path)},{cache:'no-store'}).then(async r=>({status:r.status,data:await r.json()}))`);
 const write=(path,method,payload)=>evaluate(`(async()=>{const c=await fetch('/api/auth/csrf',{cache:'no-store'});const token=(await c.json()).csrf_token;const r=await fetch(${JSON.stringify(path)},{method:${JSON.stringify(method)},headers:{'Content-Type':'application/json','X-Spectra-Client':'1','X-CSRF-Token':token},body:JSON.stringify(${JSON.stringify(payload)})});return {status:r.status,data:await r.json()};})()`);
 const navigate=async path=>{await send('Page.navigate',{url:origin+path});};
 async function login(){
  await navigate('/login');await until(()=>evaluate(`!!document.querySelector('form [name="password"]')`),'login form');
  await until(()=>evaluate(`(()=>{const f=document.querySelector('form:has([name="password"])');return Object.keys(f).some(k=>k.startsWith('__reactProps$')&&typeof f[k]?.onSubmit==='function');})()`),'hydrated login form');
  await setValue('[name="email"]',guard.email);await setValue('[name="password"]',password);
  assert.ok(await evaluate(`document.querySelector('form:has([name="password"])').checkValidity()`),'Login fields must pass native validation');
  await evaluate(`document.querySelector('form:has([name="password"])').requestSubmit()`);
  await until(()=>evaluate(`location.pathname==='/account'&&!!document.querySelector('#my-orders')`),'authenticated dashboard');
 }
 async function order(){const r=await get('/api/submissions/'+report.id);assert.equal(r.status,200);return r.data;}
 const visibleCount=number=>until(()=>evaluate(`document.querySelector('[data-testid="order-card-count"]')?.textContent.trim()==='Cartes : ${number}'&&document.querySelectorAll('[data-testid="order-selected-cards"] > article').length===${number}`),'visible card count '+number);
 async function screenshot(name,selector='.order-builder'){
  await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({block:'start',behavior:'instant'})`);await delay(180);
  const layout=await send('Page.getLayoutMetrics');const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:layout.cssLayoutViewport.clientWidth,height:Math.min(10000,layout.cssContentSize.height),scale:1}});
  const path=resolve(folder,name);await writeFile(path,Buffer.from(shot.data,'base64'));if(!report.screenshots.includes(path))report.screenshots.push(path);await save();
 }
 await send('Network.enable');await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
 await phase('live login');await login();
 const identity=await get('/api/auth/me');assert.equal(identity.data.email,guard.email);
 if(report.ac.AC6&&report.database?.verified){
  await phase('read-only persisted order and mobile validation');
  await navigate('/account/submissions/'+report.id);await visibleCount(3);assert.equal((await order()).status,'submitted');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await delay(150);
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=document.documentElement.clientWidth+1`),'Order page must fit mobile width');
  await screenshot('07-mobile-confirmed-order.png');report.mobile_verified=true;
  await send('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
  await navigate('/account');await until(()=>evaluate(`document.querySelector('#my-orders')?.textContent.includes('Cartes : 3')`),'persisted dashboard');
  await evaluate(`document.querySelector('#my-orders').scrollIntoView({block:'start',behavior:'instant'})`);await delay(150);
  const dashboard=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  const path=resolve(folder,'08-dashboard-viewport.png');await writeFile(path,Buffer.from(dashboard.data,'base64'));if(!report.screenshots.includes(path))report.screenshots.push(path);
  report.status='PASS';report.phase='complete; database, Workstation and mobile readback verified';await save();
  await write('/api/auth/logout','POST',{});
  console.log(JSON.stringify({status:'PASS',mode:'read-only verification',reference:report.reference,cards:3,submissions_created:report.submissions_created,mobile:true}));
 }else{
 let list=(await get('/api/submissions?limit=100')).data;
 if(!report.id){
  assert.equal(list.length,0,'Fictional customer must start without orders');
  await phase('create exactly one SP draft');await click('Créer une commande');
  await until(()=>evaluate(`location.pathname.startsWith('/account/submissions/')`),'new order navigation');
  report.id=await evaluate(`location.pathname.split('/').at(-1)`);let value=await order();report.reference=value.reference;await save();
 }
 await navigate('/account/submissions/'+report.id);
 await until(()=>evaluate(`document.querySelector('.order-builder-actions')?.textContent.includes('Ajouter une carte')`),'explicit order builder');
 let value=await order();assert.equal(value.status,'draft');assert.equal((await get('/api/submissions?limit=100')).data.length,1);
 if(value.card_count===0)await screenshot('01-empty-draft.png');
 const names=[1,2,3].map(i=>`SELBY Multi ${i} - ${report.run}`);
 for(let i=0;i<3;i++){
  value=await order();if(!value.entries.some(e=>e.card_name===names[i])){
   await phase('add card '+(i+1)+' to same SP');await click('Ajouter une carte');
   await until(()=>evaluate(`!!document.querySelector('#order-card-form [name="card_name"]')`),'card registration panel');
   assert.ok(await evaluate(`document.querySelector('#order-card-form').textContent.includes(${JSON.stringify(report.reference)})`));
   await setValue('#order-card-form [name="game"]',['pokemon','one-piece','dragon-ball'][i]);
   await setValue('#order-card-form [name="card_name"]',names[i]);await setValue('#order-card-form [name="language"]','FR');await setValue('#order-card-form [name="quantity"]','1');
   await setValue('#order-card-form [name="notes"]','Validation locale fictive — aucune carte réelle.');
   await click('Enregistrer et revenir à la commande');
   await until(()=>evaluate(`!document.querySelector('#order-card-form')&&location.pathname==='/account/submissions/${report.id}'`),'return to originating order');
   report.ac.AC2=true;
  }
  value=await order();await visibleCount(value.card_count);
  assert.ok(value.card_count>=i+1);assert.ok(value.entries.some(e=>e.card_name===names[i]));
  if(i===0&&value.card_count===1){
   if(!value.entries[0].pre_shipment_photos.length){
    await phase('optional front photograph on same order');
    await evaluate(`document.querySelector('.submission-photos').open=true`);
    const document=await send('DOM.getDocument',{depth:-1});const node=await send('DOM.querySelector',{nodeId:document.root.nodeId,selector:'.submission-photo-slot input[type="file"]'});
    await send('DOM.setFileInputFiles',{nodeId:node.nodeId,files:[resolve(folder,'front.png')]});
    await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Enregistrer la photo')`),'photo preview');await click('Enregistrer la photo');
    await until(async()=>(await order()).entries[0].pre_shipment_photos.length===1,'persisted optional photo');
    await until(()=>evaluate(`!document.querySelector('.submission-photo-slot:disabled')`),'photo upload finished');
    await evaluate(`document.querySelector('.submission-photos').open=false`);
   }
   await screenshot('02-order-one-card.png');
  }
  await save();
 }
 await phase('remove and reselect available owned copy');value=await order();const removed=value.entries.find(e=>e.card_name===names[2]);const copyId=removed.owned_copy_id;
 await evaluate(`Array.from(document.querySelectorAll('[data-testid="order-selected-cards"] > article')).find(a=>a.querySelector('h3').textContent.includes(${JSON.stringify(names[2])})).querySelector('.submission-actions button').click()`);
 await visibleCount(2);assert.ok((await get('/api/library/copies?limit=100')).data.items.find(c=>c.id===copyId).available);
 await click('Choisir dans mes cartes');await until(()=>evaluate(`Array.from(document.querySelectorAll('.card-library article')).some(a=>a.textContent.includes(${JSON.stringify('CC-'+copyId.replaceAll('-','').toUpperCase())}))`),'owned copy chooser');
 await evaluate(`Array.from(document.querySelectorAll('.card-library article')).find(a=>a.textContent.includes(${JSON.stringify('CC-'+copyId.replaceAll('-','').toUpperCase())})).querySelector('button').click()`);
 await visibleCount(3);report.ac.AC3=true;
 value=await order();assert.equal(new Set(value.entries.map(e=>e.owned_copy_id)).size,3);assert.ok(value.entries.every(e=>e.quantity===1));
 const rejected=await write('/api/submissions/'+report.id+'/library-copies','POST',{copy_id:copyId,version:value.version});assert.equal(rejected.status,409);report.ac.AC4_live_duplicate=true;
 await send('Page.reload');await visibleCount(3);report.ac.AC5_refresh=true;
 await screenshot('03-order-three-cards.png');
 await navigate('/account');await until(()=>evaluate(`document.querySelector('#my-orders')?.textContent.includes('Cartes : 3')`),'dashboard count');
 assert.equal(await evaluate(`document.querySelectorAll('#my-orders .submission-list > article').length`),1);
 await screenshot('04-dashboard-one-order-three-cards.png','#my-orders');
 await phase('logout/login persistence');await click('Se déconnecter');await until(()=>evaluate(`location.pathname==='/login'`),'logout');await login();
 await until(()=>evaluate(`document.querySelector('#my-orders')?.textContent.includes('Cartes : 3')`),'restored dashboard count');
 await navigate('/account/submissions/'+report.id);await visibleCount(3);report.ac.AC5=true;
 const labels=['Ajouter une carte','Choisir dans mes cartes','Continuer vers le devis'];
 assert.ok(await evaluate(`(${JSON.stringify(labels)}).every(label=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent===label))`));report.ac.AC7=true;
 await phase('configuration, quote and one order confirmation');await click('Continuer vers le devis');
 await until(()=>evaluate(`!!document.querySelector('#order-configuration .pricing-panel')`),'existing configuration and quote');
 assert.ok(await evaluate(`document.querySelectorAll('select[name="processing_tier"]').length<=1&&document.querySelectorAll('select[name="upgrade_ids"]').length<=1`));
 await screenshot('05-configuration-and-quote.png');await click('Vérifier la commande');
 await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Confirmer la commande'&&!b.disabled)`),'whole-order review');
 await click('Confirmer la commande');await until(async()=>(await order()).status==='submitted','confirmation');
 await until(()=>evaluate(`!Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Ajouter une carte'||b.textContent==='Supprimer')`),'immutable confirmation UI');
 const confirmed=await order();assert.equal(confirmed.card_count,3);
 const deleted=await write('/api/submissions/'+report.id+'/entries/'+confirmed.entries[0].id,'DELETE',{version:confirmed.version});assert.equal(deleted.status,409);
 assert.deepEqual(await order(),confirmed);report.ac.AC6=true;
 list=(await get('/api/submissions?limit=100')).data;assert.equal(list.length,1);assert.equal(list[0].id,report.id);assert.equal(list[0].card_count,3);
 const createRequests=report.requests.filter(r=>r.method==='POST'&&r.path==='/api/submissions');const confirms=report.requests.filter(r=>r.method==='POST'&&r.path===`/api/submissions/${report.id}/confirm`);
 assert.equal(createRequests.length,1);assert.equal(confirms.length,1);report.ac.AC1=true;
 report.cards=confirmed.entries.map(e=>({id:e.id,copy_id:e.owned_copy_id,name:e.card_name,quantity:e.quantity}));report.card_count=3;report.submissions_created=1;report.confirmations=1;report.status='PASS';await save();
 await screenshot('06-confirmed-order.png');
 console.log(JSON.stringify({status:report.status,reference:report.reference,cards:report.card_count,submissions_created:report.submissions_created,ac:report.ac,screenshots:report.screenshots.length}));
 }
}catch(error){
 report.status='FAIL';report.error=String(error.message).slice(0,250);await save();
 if(evaluate&&report.phase.includes('login')){try{report.loginDiagnostic=await evaluate(`({path:location.pathname,hasSensitiveQuery:new URLSearchParams(location.search).has('password'),feedback:document.querySelector('.auth-feedback')?.textContent,invalidFields:Array.from(document.querySelectorAll('form input')).filter(e=>!e.validity.valid).map(e=>({name:e.name,missing:e.validity.valueMissing,typeMismatch:e.validity.typeMismatch}))})`);await save();}catch{}}
 if(evaluate&&!report.phase.includes('login')){try{const body=await evaluate('document.body.innerText');await writeFile(resolve(folder,'failure-page.txt'),body);}catch{}}
 console.error('Live browser check failed during '+report.phase+': '+report.error);process.exitCode=1;
}finally{
 if(send)await Promise.race([send('Browser.close').catch(()=>{}),delay(800)]);
 socket?.close();chrome.kill();
}
