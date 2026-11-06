// Actual Next UI + headless Chrome. All API traffic goes to this in-memory fixture.
// No PostgreSQL access, real Stripe API, payment or customer data.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

const apiPort=18581,webPort=18582,chromePort=18583,origin=`http://127.0.0.1:${webPort}`;
const folder=resolve(process.env.SELBY_ORDER_BROWSER_OUTPUT??'.visual-review/order-workspace-v1');await mkdir(folder,{recursive:true});
const local=value=>({FR:value,EN:value});const calls=[];const cases=[];
const customer={id:randomUUID(),email:'ux@example.invalid',first_name:'Camille',last_name:'TEST',preferred_language:'FR',email_verified:true};
const address={id:randomUUID(),version:1,recipient:'Client TEST',line1:'1 rue du Test',line2:'',postal_code:'75001',city:'Paris',country:'FR',phone:'',instructions:''};
const addresses=[address];
const catalog={version:randomUUID(),schema_version:1,name:'FICTIF — STRIPE TEST',currency:'EUR',development_only:true,stripe_test_only:true,base_price_minor:1000,tiers:{standard:{name:local('Standard'),description:local('Service fictif'),price_adjustment_minor:0,available:true,display_order:0,estimated_turnaround:null},express:{name:local('Express'),description:local('Option synthétique'),price_adjustment_minor:500,available:true,display_order:1,estimated_turnaround:null}},upgrades:{classic:{name:local('Classic'),description:local('Incluse'),price_minor:0,group:'label',available:true,display_order:0,incompatible_with:[],allowed_tiers:null}},groups:{label:{min_selected:1,max_selected:1}},tax_mode:'exempt',tax_rate_bps:0,tax_description:local('Fiscalité synthétique 0 %')};
const item={id:'ux-order',reference:'SP-TEST-UX-V1',status:'draft',library_enabled:true,notes:'',version:1,card_count:2,created_at:'2026-11-05T12:00:00Z',updated_at:'2026-11-05T12:00:00Z',confirmed_at:null,entries:['Pikachu','Évoli'].map(name=>({id:randomUUID(),card_name:name,processing_tier:'standard',upgrade_ids:['classic'],game:'pokemon',expansion:'Base',card_number:'TEST',language:'FR',quantity:1,notes:'',catalog_card_id:null,pre_shipment_photos:[]}))};
let quote=null,payment='quote_not_accepted',ready=false,failRead=false,failWrite=false,ordinary=false;
const commercialPlans=[],summaryPlans=[],readOutcomes=[];
let declarations=[],receipts=[];const delivery={version:0,address_id:null,declared_value_minor:null,service_id:null,parcel:{}};
function summary(){const lines=item.entries.map(entry=>{const unit=1000+(entry.processing_tier==='express'?500:0);return {entry_id:entry.id,card_name:entry.card_name,quantity:entry.quantity,processing_tier:entry.processing_tier,tier_name:local(entry.processing_tier==='express'?'Express':'Standard'),estimated_turnaround:null,base_unit_minor:1000,speed_unit_minor:unit-1000,upgrades:[{id:'classic',name:local('Classic'),unit_minor:0}],unit_minor:unit,subtotal_minor:unit*entry.quantity,discount_minor:0,net_minor:unit*entry.quantity,tax_minor:0,total_minor:unit*entry.quantity};});const grading=lines.reduce((n,line)=>n+line.total_minor,0);return {stripe_test_only:!ordinary,commercial_terms_version:'FICTIF-STRIPE-TEST-v1-NO-REAL-SERVICE',submission_reference:item.reference,quantity:item.card_count,currency:'EUR',grading:{development_only:true,stripe_test_only:!ordinary,tax_mode:'exempt',lines,base_minor:grading,speed_minor:0,upgrades_minor:0,discount_minor:0,net_minor:grading,tax_minor:0,total_minor:grading,tax_description:local('Fiscalité synthétique 0 %'),volume_bracket:null},return_address:delivery.address_id?address:null,delivery:{...delivery},shipping:{status:ready?'configured':'pending',charge_minor:ready?500:null,service:ready?{name:local('Retour TEST France'),coverage:local('Couverture simulée'),exclusions:local('Aucun transport réel')}:null},available_services:[{id:'test-return',name:local('Retour TEST France'),countries:['FR']}],readiness:{ready:ready&&!ordinary,states:ordinary?['development_rates']:ready?['ready_for_checkout']:['missing_return_address','shipping_price_pending']},final_payable_minor:ready&&!ordinary?grading+500:null,tax_total_minor:ready?0:null,net_total_minor:ready?grading+500:null,inbound_receiving_address:null};}
function commercial(){return {charging_enabled:quote?.status==='accepted'&&!['verified','restricted'].includes(payment)&&Boolean(quote.snapshot.checkout),accepted_quote_id:quote?.status==='accepted'?quote.id:null,payment_status:payment,financial_restrictions:payment==='restricted'?['commercial_hold']:[],verified_payment_at:['verified','restricted'].includes(payment)?'2026-11-05T12:00:00Z':null,dispatch_deadline:['verified','restricted'].includes(payment)?'2026-12-05T12:00:00Z':null,indicators:[],shipment_declarations:declarations,parcel_receipts:receipts};}
function makeQuote(){return {id:randomUUID(),status:'valid',pricing_configuration_version:catalog.version,created_at:new Date().toISOString(),expires_at:new Date(Date.now()+3600000).toISOString(),accepted_at:null,snapshot:{...summary().grading,currency:'EUR',commercial_terms_version:'FICTIF-STRIPE-TEST-v1-NO-REAL-SERVICE',checkout:summary(),quantity:item.card_count,subtotal_minor:summary().grading.total_minor,discount:null,discount_scope:'base',tax_rate_bps:0}};}
const extra={id:randomUUID(),physical_card_id:'PC-TEST',status:'valid',payment_status:'not_accepted',charging_enabled:false,snapshot:{commercial_terms_version:'FICTIF-EXTRA',lines:[{entry_id:'extra',card_name:'PC-TEST',tier_name:local('Standard'),unit_minor:1000,quantity:1,total_minor:1000}],checkout:{currency:'EUR',final_payable_minor:1000,tax_total_minor:0,net_total_minor:1000,shipping:{charge_minor:0,service:{name:local('Retour TEST')}},return_address:address}}};
let supplementary=false;
const server=createServer(async(req,res)=>{try{
  const path=new URL(req.url,'http://fixture').pathname;let raw='';for await(const chunk of req)raw+=chunk;const payload=raw?JSON.parse(raw):{};calls.push({method:req.method,path,payload});res.setHeader('Content-Type','application/json');
  const plans=path.endsWith('/commercial-state')?commercialPlans:path.endsWith('/order-summary')?summaryPlans:null;
  if(req.method==='GET'&&plans?.length){
    const plan=plans.shift();const snapshot=path.endsWith('/commercial-state')?{...commercial(),...plan.state}:quote?.status==='accepted'&&quote.snapshot.checkout?{...quote.snapshot.checkout,terms_accepted:true}:{...summary(),terms_accepted:quote?.status==='accepted'};
    if(plan.delay)await new Promise(r=>setTimeout(r,plan.delay));
    const status=plan.fail?503:200;readOutcomes.push({tag:plan.tag,status});res.writeHead(status);res.end(JSON.stringify(plan.fail?{detail:'unavailable'}:snapshot));return;
  }
  if(failRead&&path.endsWith('/order-summary')){res.writeHead(503);res.end(JSON.stringify({detail:'unavailable'}));return;}
  if(failWrite&&req.method!=='GET'&&!path.includes('/csrf')){res.writeHead(409);res.end(JSON.stringify({detail:'submission_conflict'}));return;}
  let data;
  if(path==='/api/auth/me')data=customer;
  else if(path==='/api/auth/csrf')data={csrf_token:'fixture'};
  else if(path==='/api/submissions/catalog')data={...catalog,stripe_test_only:!ordinary};
  else if(path==='/api/addresses'){if(req.method==='POST')addresses.push({...payload,id:randomUUID(),version:1});data=req.method==='POST'?addresses.at(-1):addresses;}
  else if(path==='/api/library/copies')data={items:[],has_more:false};
  else if(path===`/api/submissions/${item.id}`)data=item;
  else if(path.endsWith('/order-summary'))data=quote?.status==='accepted'&&quote.snapshot.checkout?{...quote.snapshot.checkout,terms_accepted:true}:{...summary(),terms_accepted:quote?.status==='accepted'};
  else if(path.endsWith('/commercial-state'))data=commercial();
  else if(path.endsWith('/supplementary-quotes'))data=supplementary?[extra]:[];
  else if(path.includes('/supplementary-quotes/')&&path.endsWith('/accept')){assert.deepEqual(payload,{accept_terms:true});extra.status='accepted';data=extra;}
  else if(path.endsWith('/configuration')){assert.equal(item.status,'draft');assert.equal(payload.version,item.version);const id=path.match(/entries\/([^/]+)\/configuration/)?.[1];for(const entry of item.entries.filter(e=>!id||e.id===id)){entry.processing_tier=payload.processing_tier;entry.upgrade_ids=payload.upgrade_ids;}item.notes=payload.notes??item.notes;item.version++;if(quote)quote.status='invalidated';data=item;}
  else if(path.endsWith('/delivery')){assert.notEqual(quote?.status,'accepted');assert.equal(payload.version,delivery.version);Object.assign(delivery,payload,{version:delivery.version+1});ready=Boolean(delivery.address_id&&delivery.service_id&&delivery.declared_value_minor!==null);if(quote)quote.status='invalidated';data=summary();}
  else if(path.endsWith('/quotes')){if(req.method==='POST'){quote=makeQuote();data=quote;res.statusCode=201;}else data=quote?[quote]:[];}
  else if(path.includes('/quotes/')&&path.endsWith('/accept')){assert.equal(item.status,'submitted');assert.equal(quote.status,'valid');assert.equal(payload.accept_terms,true);assert.equal(quote.snapshot.checkout.readiness.ready,true);quote.status='accepted';quote.accepted_at=new Date().toISOString();payment='awaiting_payment';data=quote;}
  else if(path.endsWith('/confirm')){assert.equal(item.status,'draft');item.status='submitted';item.confirmed_at=new Date().toISOString();item.version++;data=item;}
  else if(path.endsWith('/stripe-checkout')){assert.deepEqual(payload,{quote_id:quote.id});assert.equal(quote.status,'accepted');assert.equal(quote.snapshot.checkout.final_payable_minor,2500);await new Promise(r=>setTimeout(r,150));payment='pending';data={url:null,status:'pending'};}
  else if(path.endsWith('/shipment-declarations')){if(payment==='restricted'){res.writeHead(409);res.end(JSON.stringify({detail:'payment_financial_restriction'}));return;}assert.equal(payment,'verified');declarations=[{id:randomUUID(),carrier:payload.carrier,tracking:payload.tracking,declared_dispatch_at:null,recorded_at:new Date().toISOString(),verification:'customer_declared_only'}];data=commercial();}
  else if(path.startsWith('/api/submissions')&&req.method==='GET')data=[];
  else {res.writeHead(404);data={detail:'fixture_route_not_found'};}
  res.end(JSON.stringify(data));
}catch(error){res.writeHead(500);res.end(JSON.stringify({detail:'fixture_failure'}));console.error(error.message);}});
await new Promise(r=>server.listen(apiPort,'127.0.0.1',r));
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let nextLog='',retried=false,closing=false;
function startNext(){
 const child=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port',String(webPort)],{env:{...process.env,SPECTRA_BACKEND_URL:`http://127.0.0.1:${apiPort}`,SELBY_FRONTEND_TEST_DIST_DIR:'.next-order-ux-test'},windowsHide:true,stdio:['ignore','pipe','pipe']});
 child.stdout.on('data',chunk=>{nextLog+=chunk;});child.stderr.on('data',chunk=>{nextLog+=chunk;});
 child.once('exit',()=>{if(!closing&&!retried&&nextLog.includes('This command stopped')){retried=true;console.log('Browser: retrying Next startup after CLI reminder');next=startNext();}});
 return child;
}
let next=startNext();
const chrome=spawn(process.env.CHROME_PATH??'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run',`--remote-debugging-port=${chromePort}`,`--user-data-dir=${resolve(folder,'chrome-'+randomUUID())}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
let socket,send,evaluate;
async function until(fn,label){for(let i=0;i<250;i++){try{if(await fn())return;}catch{}await delay(100);}throw Error('Timed out: '+label);}
try{
  await until(async()=>{const active=next;const r=await fetch(origin+'/account',{signal:AbortSignal.timeout(5000)});await delay(1000);return r.status===200&&active===next&&active.exitCode===null;},'Next startup');
  let targets;await until(async()=>{targets=await(await fetch(`http://127.0.0.1:${chromePort}/json/list`)).json();return targets.some(t=>t.type==='page');},'Chrome startup');
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await once(socket,'open');let seq=0;const jobs=new Map();
  send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{jobs.delete(id);reject(Error('Browser command timeout: '+method));},20000);jobs.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  socket.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const job=jobs.get(m.id);if(!job)return;jobs.delete(m.id);clearTimeout(job.timer);if(m.error)job.reject(Error(m.error.message));else job.resolve(m.result);}});
  evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;};
  const navigate=query=>send('Page.navigate',{url:origin+'/account/submissions/'+item.id+(query??'')});
  const text=()=>evaluate('document.body.innerText');
  const click=async label=>{await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled&&b.getClientRects().length)`),'button '+label);await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled&&b.getClientRects().length).focus();Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled&&b.getClientRects().length).click()`);};
  const value=(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});const proto=e.tagName==='SELECT'?HTMLSelectElement.prototype:e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
  const stage=label=>until(async()=>await evaluate(`document.querySelector('#order-step-heading')?.textContent===${JSON.stringify(label)}`),label);
  const step=name=>evaluate(`Array.from(document.querySelectorAll('.order-stepper button')).find(b=>b.textContent.endsWith(${JSON.stringify(name)})).click()`);
  const focusRead=()=>evaluate(`window.dispatchEvent(new Event('focus'))`);
  const hasAlert=()=>evaluate(`!!document.querySelector('[role="alert"]')`);
  const outcome=tag=>readOutcomes.some(row=>row.tag===tag);
  const canShip=()=>evaluate(`Array.from(document.querySelectorAll('.order-tracking button')).some(b=>b.textContent.startsWith('Déclarer mon envoi')&&!b.disabled&&b.getClientRects().length)`);
  await send('Emulation.setDeviceMetricsOverride',{width:1360,height:980,deviceScaleFactor:1,mobile:false});
  await navigate('?step=cards');await stage('Mes cartes');console.log('Browser: cards');await until(()=>evaluate(`!!document.querySelector('.order-stepper button[aria-current]')`),'hydration');
  assert.ok((await text()).includes('À déterminer'));assert.equal(await evaluate(`document.querySelectorAll('main').length`),1);cases.push('unresolved total and single main landmark');
  await click('+ Ajouter une carte');await until(()=>evaluate(`document.querySelector('dialog')?.open`),'add dialog');assert.equal(await evaluate(`document.querySelector('dialog').contains(document.activeElement)`),true);
  for(let i=0;i<18;i++){await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});assert.equal(await evaluate(`document.querySelector('dialog').contains(document.activeElement)`),true);}
  await value('dialog textarea[name="notes"]','Brouillon non enregistré');await click('×');await until(()=>evaluate(`document.querySelectorAll('dialog[open]').length===2`),'unsaved guard');
  await click('Revenir au formulaire');assert.equal(await evaluate(`document.querySelector('dialog textarea[name="notes"]').value`),'Brouillon non enregistré');
  await click('×');await click('Abandonner les modifications');await until(()=>evaluate(`!document.querySelector('dialog')`),'discard closes add');
  await until(()=>evaluate(`document.activeElement.textContent.trim()==='+ Ajouter une carte'`),'restored opener focus');cases.push('modal focus return and unsaved dismissal guard');
  await click('Choisir dans mes cartes');await until(()=>evaluate(`!!document.querySelector('dialog[open]')`),'library modal');await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await until(()=>evaluate(`!document.querySelector('dialog')`),'escape closes clean modal');cases.push('Tab containment and Escape');
  await click('Continuer');await stage('Service');
  await until(()=>evaluate(`!!document.querySelector('.order-stage form select[name="processing_tier"]')`),'service catalog');
  await evaluate(`document.querySelector('.order-stage details:has(.order-per-card)').open=true`);await value('.order-per-card select[name="processing_tier"]','express');await evaluate(`document.querySelector('.order-per-card').requestSubmit()`);await until(()=>item.entries[0].processing_tier==='express','per-card save');await until(()=>evaluate(`document.querySelector('.order-per-card select[name="processing_tier"]').value==='express'&&!document.querySelector('.order-per-card fieldset').disabled`),'mixed saved UI');assert.equal(item.entries[1].processing_tier,'standard');
  await value('.order-per-card select[name="processing_tier"]','standard');await evaluate(`document.querySelector('.order-per-card').requestSubmit()`);await until(()=>item.entries[0].processing_tier==='standard','restore standard');await until(()=>evaluate(`!document.querySelector('.order-stage form fieldset').disabled`),'saved aggregate');cases.push('mixed per-card service preservation');
  await value('.order-stage form select[name="processing_tier"]','express');
  await step('Retour');await until(()=>evaluate(`!!document.querySelector('dialog[open]')`),'step guard');await click('Revenir au formulaire');assert.equal(await evaluate(`document.querySelector('.order-stage select[name="processing_tier"]').value`),'express');
  await step('Retour');await click('Abandonner les modifications');await stage('Retour');cases.push('unsaved service navigation');console.log('Browser: return');
  await until(()=>evaluate(`document.querySelector('select[name="address"]').options.length>1`),'saved address loaded');await value('select[name="address"]',address.id);await value('input[name="declared"]','100');await value('select[name="service"]','test-return');await click('Enregistrer et continuer');await stage('Devis');
  await click('Générer le devis');await until(()=>quote!==null,'quote created');await until(async()=>(await text()).includes('1. Confirmer la commande'),'confirm shown');
  assert.equal(calls.filter(c=>c.path.endsWith('/accept')).length,0);assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Accepter le devis'&&b.getClientRects().length)`),false);
  failWrite=true;await click('Confirmer la commande');await until(()=>evaluate(`!!document.querySelector('[role="alert"]')`),'write error');assert.equal(item.status,'draft');failWrite=false;
  await click('Confirmer la commande');await until(()=>item.status==='submitted','confirm');await until(()=>evaluate(`!!document.querySelector('.order-commit-accept input')`),'consent');assert.equal(quote.status,'valid');
  assert.equal(await evaluate(`document.querySelector('.order-commit-accept button').disabled`),true);
  await evaluate(`document.querySelector('.order-commit-accept input').click()`);await click('Accepter le devis');await stage('Paiement');assert.equal(quote.status,'accepted');console.log('Browser: acceptance');cases.push('separate confirmation and explicit consent; errors preserve draft');
  await step('Mes cartes');await stage('Mes cartes');assert.equal(await evaluate(`Array.from(document.querySelectorAll('.order-card-tools button')).filter(b=>b.getClientRects().length).length`),0);await navigate();await stage('Paiement');cases.push('confirmed read-only and accepted-order resume');
  await evaluate(`(()=>{const b=Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Payer avec Stripe TEST');b.click();b.click();})()`);await until(()=>payment==='pending','mock initiation');await until(async()=>(await text()).includes('Paiement en cours de vérification'),'pending');
  assert.equal(calls.filter(c=>c.path.endsWith('/stripe-checkout')).length,1);await navigate('?stripe_return=1&paid=true');await stage('Paiement');assert.equal(await evaluate(`!!document.querySelector('.order-tracking')`),false);cases.push('double click suppression; browser return never marks paid');
  summaryPlans.push({tag:'poll-fail',fail:true});await until(()=>outcome('poll-fail'),'failed real polling read');await until(hasAlert,'polling error');
  summaryPlans.push({tag:'poll-recover'});await until(()=>outcome('poll-recover'),'successful real polling read');await until(async()=>!await hasAlert(),'polling recovery clears read error');cases.push('polling failure recovers without manual clearing or new Checkout');
  let shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(resolve(folder,'payment-desktop.png'),Buffer.from(shot.data,'base64'));
  payment='failed';await click('Actualiser le statut');await until(async()=>(await text()).includes('Tentative échouée'),'failed');
  payment='action_required';await click('Actualiser le statut');await until(async()=>(await text()).includes('Action requise'),'action required');
  payment='verified';await click('Actualiser le statut');await until(()=>evaluate(`!!document.querySelector('.order-tracking')`),'tracking');assert.equal(await evaluate(`!!document.querySelector('.order-stepper')`),false);assert.ok((await text()).includes('25,00'));assert.ok((await text()).includes('aucune expédition réelle'));cases.push('verified-only dashboard and TEST isolation labels');
  commercialPlans.push({tag:'focus-fail',fail:true});await focusRead();await until(hasAlert,'focus error');
  commercialPlans.push({tag:'focus-recover'});await focusRead();await until(()=>outcome('focus-recover'),'focus success');await until(async()=>!await hasAlert(),'focus recovery clears error');cases.push('focus read error clears automatically on recovery');
  commercialPlans.push({tag:'old-failure',delay:900,fail:true});await focusRead();await until(()=>commercialPlans.length===0,'older failure started');
  commercialPlans.push({tag:'new-success'});await focusRead();await until(()=>outcome('new-success'),'newer success');await until(()=>outcome('old-failure'),'late old failure');await delay(100);assert.equal(await hasAlert(),false);cases.push('old failure cannot overwrite newer success');
  commercialPlans.push({tag:'old-success',delay:900});await focusRead();await until(()=>commercialPlans.length===0,'older success started');
  commercialPlans.push({tag:'new-failure',fail:true});await focusRead();await until(hasAlert,'newer failure');await until(()=>outcome('old-success'),'late old success');await delay(100);assert.equal(await hasAlert(),true);
  await focusRead();await until(async()=>!await hasAlert(),'recover newer failure');cases.push('old success cannot clear newer failure');
  commercialPlans.push({tag:'old-verified',delay:900});await focusRead();await until(()=>commercialPlans.length===0,'old financial state requested');
  payment='restricted';commercialPlans.push({tag:'new-restriction'});await focusRead();await until(async()=>(await text()).includes('Examen requis'),'new restriction');await until(()=>outcome('old-verified'),'old verified arrived');await delay(100);assert.ok((await text()).includes('Examen requis'));
  payment='verified';await focusRead();await until(canShip,'recover financial state');cases.push('stale commercial response cannot remove a newer financial restriction');
  summaryPlans.push({tag:'summary-fail',fail:true});await click('Actualiser le statut');await until(hasAlert,'full summary error');
  commercialPlans.push({tag:'commercial-only-success'});await focusRead();await until(()=>outcome('commercial-only-success'),'partial read success');await delay(100);assert.equal(await hasAlert(),true);
  await click('Actualiser le statut');await until(async()=>!await hasAlert(),'complete recovery');cases.push('commercial success cannot hide a full-load error');
  commercialPlans.push({tag:'commercial-error-for-full',fail:true});await focusRead();await until(hasAlert,'commercial error before complete recovery');await click('Actualiser le statut');await until(async()=>!await hasAlert(),'full success clears covered error');cases.push('full successful load clears the commercial read error it covers');
  summaryPlans.push({tag:'old-full',delay:900});await click('Actualiser le statut');await until(()=>summaryPlans.length===0,'old full load started');
  payment='restricted';await focusRead();await until(async()=>(await text()).includes('Examen requis'),'restriction during old full load');await until(()=>outcome('old-full'),'old full load complete');await delay(100);assert.ok((await text()).includes('Examen requis'));
  payment='verified';await focusRead();await until(canShip,'restored verified');cases.push('old full response preserves a newer commercial-only response');
  summaryPlans.push({tag:'old-full-fail',delay:900,fail:true});await click('Actualiser le statut');await until(()=>summaryPlans.length===0,'old failing full request started');
  summaryPlans.push({tag:'new-full-success'});await click('Actualiser le statut');await until(()=>outcome('new-full-success'),'new full success');await until(()=>outcome('old-full-fail'),'late full failure');await delay(100);assert.equal(await hasAlert(),false);cases.push('older full failure cannot overwrite newer full success');
  summaryPlans.push({tag:'old-full-success',delay:900});await click('Actualiser le statut');await until(()=>summaryPlans.length===0,'old successful full request started');
  summaryPlans.push({tag:'new-full-fail',fail:true});await click('Actualiser le statut');await until(hasAlert,'new full failure');await until(()=>outcome('old-full-success'),'late full success');await delay(100);assert.equal(await hasAlert(),true);await click('Actualiser le statut');await until(async()=>!await hasAlert(),'full race recovery');cases.push('older full success cannot clear newer full failure');
  supplementary=true;await navigate();await until(async()=>(await text()).includes('Devis complémentaires'),'supplement');await evaluate(`document.querySelector('.order-supplementary').open=true`);
  await evaluate(`Array.from(document.querySelectorAll('form')).find(f=>f.textContent.includes('devis complémentaire')).querySelector('input[type="checkbox"]').click()`);await click('Accepter le devis complémentaire');await until(()=>extra.status==='accepted','supplementary acceptance');cases.push('existing supplementary consent retained');
  await click('Déclarer mon envoi · TEST');await value('dialog input[name="tracking"]','UNSAVED-FOCUS');
  commercialPlans.push({tag:'dirty-read-error',fail:true});await focusRead();await until(hasAlert,'dirty modal read error');await focusRead();await until(async()=>!await hasAlert(),'dirty modal read recovery');
  assert.equal(await evaluate(`document.querySelector('dialog input[name="tracking"]').value`),'UNSAVED-FOCUS');assert.ok((await text()).includes('Des modifications ne sont pas enregistrées.'));cases.push('read recovery preserves unsaved shipment and dirty guard');
  payment='restricted';await evaluate(`window.dispatchEvent(new Event('focus'))`);
  await until(()=>evaluate(`document.body.innerText.includes('Examen requis')`),'focus restriction');
  assert.equal(await evaluate(`document.querySelector('dialog input[name="tracking"]').value`),'UNSAVED-FOCUS');
  payment='verified';await evaluate(`window.dispatchEvent(new Event('focus'))`);
  await until(canShip,'focus verified');
  payment='restricted';await evaluate(`document.querySelector('dialog form').requestSubmit()`);
  await until(()=>evaluate(`document.body.innerText.includes('Examen requis')`),'409 restriction refresh');
  assert.equal(await evaluate(`document.querySelector('dialog input[name="tracking"]').value`),'UNSAVED-FOCUS');
  assert.equal(declarations.length,0);cases.push('focus and restriction 409 refresh preserve unsaved shipment');
  const businessError=await evaluate(`document.querySelector('dialog [role="alert"]').textContent`);commercialPlans.push({tag:'read-after-business-error'});await focusRead();await until(()=>outcome('read-after-business-error'),'success after business rejection');await delay(100);
  assert.equal(await evaluate(`document.querySelector('dialog [role="alert"]').textContent`),businessError);assert.equal(await evaluate(`document.querySelector('dialog input[name="tracking"]').value`),'UNSAVED-FOCUS');cases.push('successful read preserves business 409 error and unsaved values');
  payment='verified';await evaluate(`window.dispatchEvent(new Event('focus'))`);
  await until(canShip,'restore verified');
  await value('dialog input[name="tracking"]','TEST-TRACK');await click('Enregistrer la déclaration');await until(()=>declarations.length===1,'shipment declaration');await until(async()=>(await text()).includes('Envoi déclaré'),'declared');assert.equal(receipts.length,0);cases.push('declared shipment never implies physical receipt');
  receipts=[{id:randomUUID(),reference:'PARCEL-TEST',received_at:'2026-11-05T13:00:00Z'}];await click('Actualiser le statut');await until(async()=>(await text()).includes('Colis reçu'),'received');
  payment='restricted';await click('Actualiser le statut');await until(async()=>(await text()).includes('Examen requis'),'restriction');assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.startsWith('Déclarer mon envoi'))`),false);cases.push('financial restriction removes shipment actions');
  shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(resolve(folder,'tracking-desktop.png'),Buffer.from(shot.data,'base64'));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await delay(200);assert.equal(await evaluate(`document.documentElement.scrollWidth<=document.documentElement.clientWidth+1`),true);
  shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(resolve(folder,'tracking-mobile.png'),Buffer.from(shot.data,'base64'));
  payment='awaiting_payment';await navigate();await stage('Paiement');await until(()=>evaluate(`!document.querySelector('.order-summary details').open`),'mobile summary collapsed');assert.equal(await evaluate(`document.documentElement.scrollWidth<=document.documentElement.clientWidth+1`),true);cases.push('mobile layout and collapsible summary');
  const saved=structuredClone(quote);delete quote.snapshot.checkout;await navigate();await stage('Paiement');assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Payer avec Stripe TEST')`),false);cases.push('historical accepted quote never invents payable amount');quote=saved;
  failRead=true;await navigate();await until(()=>evaluate(`!!document.querySelector('[role="alert"]')`),'read error');failRead=false;await click('Réessayer');await stage('Paiement');cases.push('load failure retry');
  customer.preferred_language='EN';await navigate();await stage('Payment');assert.ok((await text()).includes('FICTIONAL — STRIPE TEST'));cases.push('FR and EN');
  commercialPlans.push({tag:'english-focus-error',fail:true});await focusRead();await until(hasAlert,'English read error');assert.ok((await text()).includes('Unable to load'));await focusRead();await until(async()=>!await hasAlert(),'English recovery');cases.push('English read recovery');
  ordinary=true;quote=null;payment='quote_not_accepted';item.status='submitted';await navigate('?step=quote');await stage('Quote');assert.equal(await evaluate(`!!document.querySelector('.order-commit-accept input:not(:disabled)')`),false);cases.push('ordinary development remains blocked');
  commercialPlans.push({tag:'unmounted-failure',delay:900,fail:true});await focusRead();await until(()=>commercialPlans.length===0,'pending read before leaving');await evaluate(`document.querySelector('a[href="/account"]').click()`);await until(()=>evaluate(`location.pathname==='/account'`),'workspace unmounted');await until(()=>outcome('unmounted-failure'),'late failure after unmount');await delay(100);assert.equal(await hasAlert(),false);cases.push('late read failure after unmount does not create an alert');
  const report={passed:true,cases,postgresql_access:false,real_payments:0,real_stripe_requests:0,mock_checkout_requests:calls.filter(c=>c.path.endsWith('/stripe-checkout')).length};await writeFile(resolve(folder,'validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}catch(error){if(evaluate){try{await writeFile(resolve(folder,'failure.txt'),await evaluate('document.body.innerText'));await writeFile(resolve(folder,'focus.txt'),await evaluate('document.activeElement.outerHTML'));}catch{}}await writeFile(resolve(folder,'next.log'),nextLog);await writeFile(resolve(folder,'requests.json'),JSON.stringify(calls,null,2));throw error;}
finally{closing=true;if(send)await Promise.race([send('Browser.close').catch(()=>{}),delay(1000)]);socket?.close();chrome.kill();next.kill();server.closeAllConnections();server.close();}
