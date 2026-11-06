// Production Next + headless Chrome with a synthetic API; never touches customer databases.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';

const origin='http://127.0.0.1:18182';
const customer={id:'library-customer',email:'library@example.invalid',first_name:'Library',last_name:'Fixture',preferred_language:'EN',email_verified:true};
let sequence=0;const orders=new Map();let failure=false;
const copies=Array.from({length:26},(_,i)=>({id:randomUUID(),reference:`CC-FIXTURE-${i}`,version:1,game:'pokemon',card_name:i===0?'Unavailable copy':`Library copy ${i}`,expansion:'Fixture set',card_number:`A-${i}`,language:'EN',notes:'',catalog_card_id:null,created_at:new Date().toISOString(),available:i!==0,active_submission_id:i===0?'existing-order':null,pre_shipment_photos:[],identity_verified:false}));
const calls=[];
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture');let data={};let raw='';for await(const chunk of req)raw+=chunk;
 const payload=raw?JSON.parse(raw):{};calls.push([req.method,url.pathname]);
 res.setHeader('Content-Type','application/json');
 if(url.pathname==='/api/auth/me')data=customer;
 else if(url.pathname==='/api/auth/csrf')data={csrf_token:'fixture'};
 else if(url.pathname==='/api/library/copies'){
  if(failure){res.statusCode=503;data={detail:'unavailable'};}
  else if(req.method==='POST'){const copy={...copies[1],...payload,id:randomUUID(),reference:'CC-NEW-'+(++sequence),available:true,active_submission_id:null};copies.unshift(copy);res.statusCode=201;data=copy;}
  else{const filtered=copies.filter(c=>c.card_name.toLowerCase().includes((url.searchParams.get('search')??'').toLowerCase()));const offset=Number(url.searchParams.get('offset')??0);const limit=Number(url.searchParams.get('limit')??25);data={items:filtered.slice(offset,offset+limit),has_more:filtered.length>offset+limit};}
 }
 else if(url.pathname==='/api/submissions/catalog'){res.statusCode=503;data={detail:'pricing_unavailable'};}
 else if(url.pathname==='/api/submissions'){
  if(req.method==='POST'){const id='order-'+(++sequence);data={id,reference:'SP-FIXTURE-'+sequence,library_enabled:true,status:'draft',notes:'',version:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),confirmed_at:null,card_count:0,entries:[]};orders.set(id,data);res.statusCode=201;}
  else data=[...orders.values()];
 }
 else if(url.pathname.startsWith('/api/submissions/')){
  const [, , ,id,action,target]=url.pathname.split('/');const order=orders.get(id);
  if(!order){res.statusCode=404;data={detail:'submission_not_found'};}
  else if(req.method==='GET'&&!action)data=order;
  else if(action==='library-copies'){
   const copy=copies.find(c=>c.id===payload.copy_id);
   if(!copy.available){res.statusCode=409;data={detail:'copy_unavailable'};}
   else{copy.available=false;copy.active_submission_id=id;order.entries.push({...copy,id:randomUUID(),owned_copy_id:copy.id,quantity:1,processing_tier:'standard',upgrade_ids:['classic']});order.version++;order.card_count++;data=order;res.statusCode=201;}
  }
  else if(action==='library-register'){
   for(let n=0;n<payload.quantity;n++){const copy={...copies[1],...payload,id:randomUUID(),reference:'CC-ORDER-'+(++sequence),available:false,active_submission_id:id,version:1};copies.unshift(copy);order.entries.push({...copy,id:randomUUID(),owned_copy_id:copy.id,quantity:1,processing_tier:'standard',upgrade_ids:['classic']});}
   order.version++;order.card_count=order.entries.length;data=order;res.statusCode=201;
  }
  else if(action==='entries'&&req.method==='DELETE'){
   const entry=order.entries.find(e=>e.id===target);const copy=copies.find(c=>c.id===entry.owned_copy_id);copy.available=true;copy.active_submission_id=null;order.entries=order.entries.filter(e=>e!==entry);order.version++;order.card_count=order.entries.length;data=order;
  }
  else if(action==='confirm'){order.status='submitted';order.confirmed_at=new Date().toISOString();order.version++;data=order;}
  else if(action==='quotes')data=[];
  else{res.statusCode=503;data={detail:'unavailable'};}
 }
 else if(url.pathname==='/api/addresses')data=[];
 else{res.statusCode=404;data={detail:'unavailable'};}
 res.end(JSON.stringify(data));
});
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(18181,'127.0.0.1',resolve);});
const next=spawn(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','18182'],{env:{...process.env,SPECTRA_BACKEND_URL:'http://127.0.0.1:18181'},windowsHide:true,stdio:'ignore'});
const profile=resolve(`.visual-review/library-${randomUUID()}`);await mkdir(profile,{recursive:true});
const chrome=spawn(process.env.CHROME_PATH??'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=18183',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
let socket;let evaluate;let send;const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let n=0;n<120;n++){try{if(await fn())return;}catch{}await delay(100);}throw Error('Library browser condition timed out');}
try{
 await until(async()=>(await fetch(origin+'/login')).ok);
 let targets;await until(async()=>{targets=await(await fetch('http://127.0.0.1:18183/json/list')).json();return targets.some(t=>t.type==='page');});
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await once(socket,'open');let id=0;const pending=new Map();
 send=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});socket.send(JSON.stringify({id:key,method,params}));});
 socket.addEventListener('message',async event=>{const message=JSON.parse(event.data);if(message.id){const job=pending.get(message.id);pending.delete(message.id);if(message.error)job.reject(Error(message.error.message));else job.resolve(message.result);}else if(message.method==='Fetch.requestPaused'){
  const {requestId,request}=message.params;const url=new URL(request.url);const response=await fetch('http://127.0.0.1:18181'+url.pathname+url.search,{method:request.method,body:request.postData});await send('Fetch.fulfillRequest',{requestId,responseCode:response.status,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(await response.arrayBuffer()).toString('base64')});
 }});
 evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error('Browser expression failed');return r.result.value;};
 const click=(label,root='document')=>evaluate(`Array.from(${root}.querySelectorAll('button')).find(b=>b.textContent===${JSON.stringify(label)})?.click()`);
 const setValue=(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(e.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
 const navigate=async path=>{await send('Page.navigate',{url:origin+path});await until(()=>evaluate(`!!document.querySelector('.submissions')`));};
 await send('Fetch.enable',{patterns:[{urlPattern:'*/api/*'}]});await send('Network.setCookie',{name:'spectra_language',value:'EN',url:origin});
 await navigate('/account');await until(()=>evaluate(`document.querySelectorAll('#my-cards article').length===25`));
 assert.ok(await evaluate(`document.body.textContent.includes('My Cards')&&document.body.textContent.includes('My Orders')`));
 await click('Show more',`document.querySelector('#my-cards')`);await until(()=>evaluate(`document.querySelectorAll('#my-cards article').length===26`));
 await click('Register one copy',`document.querySelector('#my-cards')`);
 await setValue('#my-cards [name="card_name"]','Standalone registered copy');await setValue('#my-cards [name="language"]','EN');
 await evaluate(`document.querySelector('#my-cards form:has([name="card_name"])').requestSubmit()`);
 await until(()=>copies.length===27);assert.equal(orders.size,0,'library registration must not create an order');
 await click('Create order');await until(()=>evaluate(`document.body.textContent.includes('Add a card')`));
 const order=[...orders.values()][0];assert.equal(order.card_count,0);
 await click('Choose from my cards');
 await until(()=>evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Add this copy')`));
 assert.ok(await evaluate(`Array.from(document.querySelectorAll('article')).find(a=>a.textContent.includes('Unavailable copy')).querySelector('button').disabled`));
 await click('Add this copy');await until(()=>order.card_count===1);
 const copyId=order.entries[0].owned_copy_id;assert.ok(copyId);
 await send('Page.reload');await until(()=>evaluate(`document.querySelectorAll('[data-testid="order-selected-cards"] > article').length===1`));
 await click('Remove');await until(()=>order.card_count===0);assert.ok(copies.find(c=>c.id===copyId).available);
 await click('Add a card');await until(()=>evaluate(`!!document.querySelector('#order-card-form')`));await setValue('[name="card_name"]','Two identical copies');await setValue('[name="language"]','EN');await setValue('[name="quantity"]','2');
 await evaluate(`document.querySelector('.submissions form:has([name="card_name"])').requestSubmit()`);
 await until(()=>order.card_count===2);assert.equal(new Set(order.entries.map(e=>e.owned_copy_id)).size,2);
 await click('Continue to quote');await click('Review order');await click('Confirm order');await until(()=>order.status==='submitted');
 assert.ok(await evaluate(`!Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Remove')`));
 await navigate('/account');failure=true;await click('Reload',`document.querySelector('#my-cards')`);await until(()=>evaluate(`document.querySelector('#my-cards').textContent.includes('Unable to load or save')`));failure=false;await click('Reload',`document.querySelector('#my-cards')`);await until(()=>evaluate(`!document.querySelector('#my-cards').textContent.includes('Unable to load or save')`));
 customer.preferred_language='FR';await navigate('/account');await until(()=>evaluate(`document.body.textContent.includes('Mes cartes')&&document.body.textContent.includes('Créer une commande')`));
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.ok(await evaluate(`document.documentElement.scrollWidth<=document.documentElement.clientWidth+1`),'mobile layout must not overflow');
 const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(resolve('.visual-review/library-mobile.png'),Buffer.from(shot.data,'base64'));
 console.log(JSON.stringify({passed:true,cases:['standalone registration','pagination','empty order','unavailable copies','assignment','refresh persistence','draft removal','identical copies','confirmation','network retry','FR/EN','mobile layout'],writes:calls.filter(([method])=>method!=='GET').length}));
 }catch(error){if(evaluate){try{const dump=await evaluate(`JSON.stringify({body:document.body.innerText,buttons:Array.from(document.querySelectorAll('button')).map(b=>({text:b.textContent,disabled:b.disabled}))})`);await writeFile(resolve('.visual-review/library-failure.json'),dump);}catch{}}throw error;
}finally{if(send)await Promise.race([send('Browser.close').catch(()=>{}),delay(1000)]);socket?.close();chrome.kill();next.kill();server.closeAllConnections();server.close();}
