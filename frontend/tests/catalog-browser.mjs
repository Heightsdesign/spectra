// Production Next + headless Chrome, synthetic backend. No real accounts/provider calls.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {resolve} from 'node:path';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

let item={id:'catalog-fixture',reference:'SP-FIXTURE',status:'draft',notes:'',version:1,created_at:'2026-10-25T00:00:00Z',entries:[],card_count:0};
let catalogFailure=false;
let photoFailure=false;
const photoBytes=new Map();let photoSequence=0;
const catalogRequests=[];
const sets=Array.from({length:43},(_,i)=>({id:`set-${i}`,name:`Fixture set ${String(i).padStart(2,'0')}`,code:`TEST${i}`}));
const cards=sets.map((set,i)=>({id:`card-${i}`,name:'Fixture card',collector_number:`TG${String(i).padStart(2,'0')}`,expansion_id:set.id,expansion_name:set.name,expansion_code:set.code}));
const customer={id:'fixture',email:'test@example.invalid',email_verified:true,preferred_language:'EN'};
const priceCatalog=JSON.parse(await readFile('../backend/pricing/development-example.json','utf8'));
let pricingAvailable=false;
const configurationWrites=[];const orderNoteWrites=[];const quotes=[];
const invalidateQuotes=()=>{for(const quote of quotes)quote.status='invalidated';};
function quotedOrder(){
 const lines=item.entries.map(entry=>{
  const tier=priceCatalog.tiers[entry.processing_tier];
  const upgrades=entry.upgrade_ids.map(id=>({...priceCatalog.upgrades[id],id,unit_minor:priceCatalog.upgrades[id].price_minor}));
  const unit=priceCatalog.base_price_minor+tier.price_adjustment_minor+upgrades.reduce((sum,u)=>sum+u.unit_minor,0);
  return {...entry,entry_id:entry.id,tier_name:tier.name,estimated_turnaround:null,base_unit_minor:priceCatalog.base_price_minor,speed_unit_minor:tier.price_adjustment_minor,upgrades,unit_minor:unit,subtotal_minor:unit*entry.quantity,discount_minor:0,net_minor:unit*entry.quantity,tax_minor:0,total_minor:unit*entry.quantity};
 });
 const total=lines.reduce((sum,line)=>sum+line.total_minor,0);
 return {id:`quote-${quotes.length+1}`,status:'valid',created_at:new Date().toISOString(),expires_at:new Date(Date.now()+3600000).toISOString(),pricing_configuration_version:'fixture-price',accepted_at:null,snapshot:{...priceCatalog,submission_notes:item.notes,quantity:item.card_count,lines,subtotal_minor:total,discount_minor:0,net_minor:total,tax_minor:0,total_minor:total,discount:null}};
}
// Synthetic return data only; never commercial configuration.
let returnDelivery={version:0,address_id:null,declared_value_minor:null,service_id:'legacy-unavailable',parcel:{weight_g:650,length_mm:240,width_mm:160,height_mm:80}};
const returnAddresses=[{id:'address-fr',version:1,recipient:'Fixture collector',line1:'1 Fixture Street',line2:'',postal_code:'75001',city:'Paris',country:'FR',phone:'+33123456789',instructions:''}];
const deliveryWrites=[];
function returnOrder(){return {terms_accepted:false,submission_reference:item.reference,quantity:item.card_count,currency:'EUR',grading:{development_only:true,tax_mode:'pending',base_minor:1000,speed_minor:0,upgrades_minor:0,discount_minor:0,net_minor:1000,tax_minor:0,total_minor:1000,lines:[],tax_description:{FR:'Fiscalité TEST en attente',EN:'TEST tax pending'},volume_bracket:null},return_address:returnAddresses.find(address=>address.id===returnDelivery.address_id)??null,delivery:returnDelivery,shipping:{status:'pending',charge_minor:null,service:null},available_services:[],readiness:{ready:false,states:['development_rates','tax_configuration_pending','shipping_price_pending']},final_payable_minor:null,inbound_receiving_address:null};}
const server=createServer(async(req,res)=>{
 res.setHeader('Content-Type','application/json');
 const url=new URL(req.url,'http://local');
 let body={};
 if(url.pathname==='/api/auth/me')body=customer;
 else if(url.pathname==='/api/auth/csrf')body={csrf_token:'fixture'};
 else if(url.pathname==='/api/submissions/catalog'){
  if(pricingAvailable)body={...priceCatalog,version:'fixture-price'};
  else{res.statusCode=503;body={detail:'pricing_unavailable'};}
 }
 else if(url.pathname.endsWith('/configuration')){
  let raw='';for await(const chunk of req)raw+=chunk;const payload=JSON.parse(raw);configurationWrites.push(payload);
  invalidateQuotes();for(const entry of item.entries){entry.processing_tier=payload.processing_tier;entry.upgrade_ids=payload.upgrade_ids;}
  item={...item,notes:payload.notes??item.notes,version:item.version+1};body=item;
 }
 else if(url.pathname.endsWith('/quotes')){
  if(req.method==='POST'){const quote=quotedOrder();quotes.unshift(quote);body=quote;}
  else body=quotes;
 }
 else if(url.pathname==='/api/addresses')body=returnAddresses;
 else if(url.pathname.endsWith('/order-summary'))body=returnOrder();
 else if(url.pathname.endsWith('/delivery')){
  let raw='';for await(const chunk of req)raw+=chunk;const payload=JSON.parse(raw);deliveryWrites.push(payload);
  returnDelivery={...returnDelivery,...payload,version:returnDelivery.version+1};body=returnOrder();
 }
 else if(url.pathname.includes('/photos')){
  const match=/\/entries\/([^/]+)\/photos(?:\/([^/]+))?$/.exec(url.pathname);
  const entry=item.entries.find(entry=>entry.id===match?.[1]);
  if(req.method==='GET'){
   const photo=entry?.pre_shipment_photos?.find(photo=>photo.id===match?.[2]);
   if(!photo){res.statusCode=404;res.end('{}');return;}
   res.setHeader('Content-Type',photo.mime_type);res.setHeader('Cache-Control','private, no-store');res.end(photoBytes.get(photo.id));return;
  }
  let raw='';for await(const chunk of req)raw+=chunk;
  const payload=JSON.parse(raw);
  if(photoFailure){res.statusCode=503;body={detail:'photo_storage_unavailable'};}
  else if(item.status!=='draft'){res.statusCode=409;body={detail:'submission_immutable'};}
  else if(req.method==='DELETE'){entry.pre_shipment_photos=entry.pre_shipment_photos.filter(photo=>photo.id!==match[2]);item={...item,version:item.version+1};body=item;}
  else {
   const bytes=Buffer.from(payload.data,'base64');const id=`photo-${++photoSequence}`;
   const photo={id,entry_id:entry.id,copy_number:payload.copy_number,side:payload.side,uploaded_by:'fixture-customer',uploaded_at:'2026-10-25T12:00:00Z',original_filename:payload.filename,mime_type:'image/png',sha256:createHash('sha256').update(bytes).digest('hex'),file_size:bytes.length,provenance:'customer_pre_shipment',identity_verified:false};
   photoBytes.set(id,bytes);entry.pre_shipment_photos=[...(entry.pre_shipment_photos??[]).filter(p=>!(p.copy_number===photo.copy_number&&p.side===photo.side)),photo];
   item={...item,version:item.version+1};body=item;
  }
 }
 else if(url.pathname.startsWith('/api/catalog/')){
  catalogRequests.push(url);
  await new Promise(resolve=>setTimeout(resolve,url.searchParams.get('q')==='slow'?900:100));
  if(catalogFailure){res.statusCode=503;body={detail:'unavailable'};}
  else {
   const query=(url.searchParams.get('q')??'').toLowerCase();
   const language=url.searchParams.get('language');
   let rows=url.pathname.endsWith('/expansions')?sets:cards.map(card=>({...card,language}));
   if(url.searchParams.get('game')!=='pokemon')rows=[];
   if(url.searchParams.has('expansion_id'))rows=rows.filter(row=>row.expansion_id===url.searchParams.get('expansion_id'));
   rows=rows.filter(row=>`${row.name} ${row.code??row.collector_number}`.toLowerCase().includes(query));
   const offset=Number(url.searchParams.get('offset')??0);const limit=Number(url.searchParams.get('limit')??20);
   body=rows.slice(offset,offset+limit);
  }
 }
 else if(url.pathname.endsWith('/entries')&&req.method==='POST'){
  let raw='';for await(const chunk of req)raw+=chunk;
  const entry=JSON.parse(raw);delete entry.version;
  const first=item.entries[0];invalidateQuotes();
  item={...item,version:item.version+1,card_count:item.card_count+entry.quantity,entries:[...item.entries,{processing_tier:first?.processing_tier??'standard',upgrade_ids:first?.upgrade_ids??['classic'],...entry,id:`entry-${item.entries.length}`}]};body=item;
 }else if(url.pathname.endsWith('/confirm')){item={...item,status:'submitted',version:item.version+1};body=item;}
 else if(url.pathname==='/api/submissions/catalog-fixture'&&req.method==='PATCH'){
  let raw='';for await(const chunk of req)raw+=chunk;const payload=JSON.parse(raw);orderNoteWrites.push(payload);invalidateQuotes();item={...item,version:item.version+1,notes:payload.notes};body=item;
 }
 else if(url.pathname==='/api/submissions')body=[item];
 else if(url.pathname==='/api/submissions/catalog-fixture')body=item;
 else {res.statusCode=503;body={detail:'pricing_unavailable'};}
 res.end(JSON.stringify(body));
});
server.listen(18171,'127.0.0.1');await once(server,'listening');
const next=spawn(process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','18172'],{env:{...process.env,SPECTRA_BACKEND_URL:'http://127.0.0.1:18171'},windowsHide:true,stdio:'ignore'});
await mkdir('.visual-review/catalog-profile',{recursive:true});
const photoFixture=resolve('.visual-review/catalog-profile/customer.png');
await writeFile(photoFixture,Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==','base64'));
const chrome=spawn(process.env.CHROME_PATH??'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=18173',`--user-data-dir=${resolve('.visual-review/catalog-profile')}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let n=0;n<100;n++){try{if(await fn())return;}catch{}await delay(100);}throw Error('Browser condition timed out');}
let socket;
try{
 await until(async()=>(await fetch('http://127.0.0.1:18172/standards')).ok);
 let targets;await until(async()=>{targets=await(await fetch('http://127.0.0.1:18173/json/list')).json();return targets.some(t=>t.type==='page');});
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await once(socket,'open');
 let id=0;const pending=new Map();
 socket.addEventListener('message',async e=>{const data=JSON.parse(e.data);if(data.id){const job=pending.get(data.id);pending.delete(data.id);if(data.error)job.reject(Error(data.error.message));else job.resolve(data.result);}
 else if(data.method==='Fetch.requestPaused'){const {requestId,request}=data.params;const url=new URL(request.url);const response=await fetch('http://127.0.0.1:18171'+url.pathname+url.search,{method:request.method,body:request.postData});await send('Fetch.fulfillRequest',{requestId,responseCode:response.status,responseHeaders:[{name:'Content-Type',value:response.headers.get('content-type')??'application/json'}],body:Buffer.from(await response.arrayBuffer()).toString('base64')}).catch(error=>{if(!error.message.includes('Invalid InterceptionId'))throw error;});}});
 const send=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});socket.send(JSON.stringify({id:key,method,params}));});
 const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
 const click=label=>evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent===${JSON.stringify(label)})?.click()`);
 const value=name=>evaluate(`document.querySelector('[name="${name}"]')?.value`);
 const setValue=(selector,value)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});const setter=Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
 await send('Fetch.enable',{patterns:[{urlPattern:'*/api/*'}]});
 await send('Emulation.setFocusEmulationEnabled',{enabled:true});
 await send('Page.navigate',{url:'http://127.0.0.1:18172/account/submissions/catalog-fixture'});
 const combo=index=>`document.querySelectorAll('[role="combobox"]')[${index}]`;
 const focus=index=>evaluate(`${combo(index)}.focus()`);
 const key=async key=>{await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:key,...(key==='Enter'?{text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13}:{})});await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:key});};
 const options=()=>evaluate(`Array.from(document.querySelectorAll('[role="option"]')).map(el=>el.textContent)`);
 const mouseOption=async index=>{
  const point=await evaluate(`(()=>{const el=document.querySelectorAll('[role="option"]')[${index}];el.scrollIntoView({block:'center',behavior:'instant'});const rect=el.getBoundingClientRect();return {x:rect.x+rect.width/2,y:rect.y+rect.height/2};})()`);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',...point});
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
 };
 const waitCount=count=>until(async()=>await evaluate(`document.querySelectorAll('[role="option"]').length`)===count);
 await until(()=>evaluate(`!!document.querySelector('.catalog-assistance input')`));
 await until(()=>evaluate(`!!document.querySelector('[name="order_notes"]')`));
 assert.equal(await evaluate(`document.querySelectorAll('select[name="processing_tier"]').length`),0);
 await setValue('[name="order_notes"]','Notes before services are available');await click('Save order notes');
 await until(()=>orderNoteWrites.length===1);
 assert.equal(item.notes,'Notes before services are available');
 pricingAvailable=true;await click('Refresh services and quote');
 await until(()=>evaluate(`document.querySelectorAll('select[name="processing_tier"]').length===1`));
 assert.equal(await evaluate(`document.querySelector('[name="card_name"]').readOnly`),false);
 assert.equal(await evaluate(`document.querySelector('[name="expansion"]').required`),false);
 assert.equal(await evaluate(`document.querySelector('[name="card_number"]').required`),false);
 await evaluate(`document.querySelector('.catalog-assistance input').click()`);
 await until(()=>evaluate(`document.querySelectorAll('[role="combobox"]').length===2`));
 assert.equal(catalogRequests.length,0,'closed selectors do not fetch');
 // Card-name-first selection: matching names never imply a printing.
 await focus(1);
 await until(()=>evaluate(`document.body.textContent.includes('Loading…')`));
 await waitCount(20);
 assert.ok((await options())[1].includes('Fixture set 01 (TEST1) — TG01 — EN'));
 await key('Enter');assert.equal(await value('catalog_card_id'),'');
 assert.equal(await evaluate(`${combo(1)}.validity.valid`),true,'catalog selection is optional');
 await key('ArrowDown');await key('ArrowDown');await key('Enter');
 assert.equal(await value('catalog_card_id'),'card-1');assert.equal(await value('expansion'),'Fixture set 01');
 assert.equal(await value('card_number'),'TG01');assert.equal(await value('language'),'en');
 assert.equal(await evaluate(`${combo(1)}===document.activeElement`),true);
 assert.equal(await evaluate(`${combo(1)}.getAttribute('aria-expanded')`),'false');
 await click('Save card');await until(()=>item.entries.length===1);
 assert.equal(item.entries[0].catalog_card_id,'card-1');
 await send('Page.reload');await until(()=>evaluate(`document.body.textContent.includes('Fixture card × 1')`));
 await evaluate(`document.querySelector('.catalog-assistance input').click()`);
 // Empty expansion query and complete navigation, including an item on page three.
 await focus(0);await waitCount(20);
 assert.equal(catalogRequests.at(-1).searchParams.get('q'),'');
 await click('Load more results');await waitCount(40);
 await click('Load more results');await waitCount(43);
 assert.ok(await evaluate(`document.body.textContent.includes('All results are shown.')`));
 await mouseOption(42);
 await until(()=>evaluate(`${combo(0)}.value==='Fixture set 42 (TEST42)'`));
 const setLabel=await evaluate(`${combo(0)}.value`);
 assert.equal(setLabel,'Fixture set 42 (TEST42)');
 // Harmless interface rerender preserves selected filter and search language.
 await setValue('select','FR');
 assert.equal(await evaluate(`${combo(0)}.value`),setLabel);
 await setValue('select','EN');
 await focus(1);await waitCount(1);
 assert.equal(catalogRequests.at(-1).searchParams.get('expansion_id'),'set-42');
 await evaluate(`document.querySelector('[role="option"]').click()`);
 assert.equal(await value('catalog_card_id'),'card-42');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await focus(0);await waitCount(20);
 assert.equal(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`),true,'dropdown fits narrow viewport');
 await key('Escape');
 await send('Emulation.clearDeviceMetricsOverride');
 await evaluate(`document.querySelector('[aria-label="Clear: Set (optional filter)"]').click()`);
 assert.equal(await value('catalog_card_id'),'');assert.equal(await value('expansion'),'');
 await key('Escape');
 // Cards also permit complete browsing and query cancellation.
 await focus(1);await waitCount(20);
 await click('Load more results');await waitCount(40);
 await click('Load more results');await waitCount(43);
 // Use an ID selector so the exact card input is targeted.
 const cardInputId=await evaluate(`${combo(1)}.id`);
 await setValue(`[id="${cardInputId}"]`,'slow');await delay(400);
 await setValue(`[id="${cardInputId}"]`,'Fixture');await waitCount(20);await delay(900);
 assert.equal((await options()).length,20,'late cancelled response never replaces current results');
 // Error, retry and empty states without discarding the saved submission.
 catalogFailure=true;
 await setValue(`[id="${cardInputId}"]`,'error');
 await until(()=>evaluate(`document.body.textContent.includes('Unable to load the catalog.')`));
 catalogFailure=false;await click('Retry');
 await until(()=>evaluate(`document.body.textContent.includes('No results. Try another search or manual entry.')`));
 await setValue(`[id="${cardInputId}"]`,'Fixture');await waitCount(20);
 await key('Escape');
 assert.equal(await evaluate(`${combo(1)}.getAttribute('aria-expanded')`),'false');
 assert.equal(await evaluate(`${combo(1)}===document.activeElement`),true);
 // Manual mode has no catalog prerequisite and keeps unrelated unsaved fields.
 await evaluate(`document.querySelector('input[type="checkbox"]').click()`);
 for(const [name,text] of Object.entries({card_name:'Manual second',expansion:'Other set',card_number:'A-01',language:'JP',quantity:'2'}))await setValue(`[name="${name}"]`,text);
 await evaluate(`document.querySelector('textarea[name="notes"]').value='Keep this note';document.querySelector('textarea[name="notes"]').dispatchEvent(new Event('input',{bubbles:true}))`);
 await evaluate(`document.querySelector('input[type="checkbox"]').click()`);
 assert.equal(await value('card_name'),'Manual second');assert.equal(await value('quantity'),'2');
 assert.equal(await evaluate(`document.querySelector('textarea[name="notes"]').value`),'Keep this note');
 await evaluate(`document.querySelector('input[type="checkbox"]').click()`);
 await click('Save card');await until(()=>item.entries.length===2);
 assert.equal(item.entries[1].catalog_card_id,null);assert.equal(item.entries[1].card_number,'A-01');
 await send('Page.reload');await until(()=>evaluate(`document.body.textContent.includes('Manual second × 2')`));
 await evaluate(`document.querySelector('.catalog-assistance input').click()`);
 // Changing catalog language/game invalidates a selected localized printing.
 await focus(1);await waitCount(20);await key('ArrowDown');await key('Enter');
 assert.equal(await value('catalog_card_id'),'card-0');
 await setValue('[aria-label="Catalog language"]','fr');
 assert.equal(await value('catalog_card_id'),'');assert.equal(await value('card_name'),'');
 await focus(1);await waitCount(20);await key('ArrowDown');await key('Enter');
 assert.equal(await value('language'),'fr');
 await setValue('[name="game"]','one-piece');
 assert.equal(await value('card_name'),'');assert.equal(await value('expansion'),'');assert.equal(await value('catalog_card_id'),'');
 await focus(0);await until(()=>evaluate(`document.body.textContent.includes('No results. Try another search or manual entry.')`));
 await setValue('select','FR');
 assert.ok(await evaluate(`document.body.textContent.includes('Aide du catalogue (facultative)')`));
 // A complete manual declaration needs neither suggestions nor optional text fields.
 await setValue('select','EN');
 await evaluate(`document.querySelector('.catalog-assistance input').click()`);
 await setValue('[name="card_name"]','Photo card');await setValue('[name="language"]','EN');await setValue('[name="quantity"]','2');
 assert.equal(await value('expansion'),'');assert.equal(await value('card_number'),'');
 await click('Save card');await until(()=>item.entries.length===3);
 const photoEntry=item.entries.find(entry=>entry.card_name==='Photo card');
 assert.equal(photoEntry.catalog_card_id,null);
 // Exactly one order-level pair, with one note field for each distinct scope.
 await until(()=>evaluate(`document.querySelectorAll('.order-configuration').length===1`));
 await until(()=>evaluate(`document.querySelectorAll('.order-configuration select[name="processing_tier"]:enabled').length===1`));
 assert.equal(await evaluate(`document.querySelectorAll('select[name="processing_tier"]').length`),1);
 assert.equal(await evaluate(`document.querySelectorAll('select[name="upgrade_ids"]').length`),1);
 assert.equal(await evaluate(`document.querySelector('[name="card_name"]').form.querySelectorAll('[name="processing_tier"],[name="upgrade_ids"]').length`),0);
 assert.equal(await evaluate(`document.querySelectorAll('textarea[name="notes"]').length`),1);
 assert.equal(await evaluate(`document.querySelectorAll('textarea[name="order_notes"]').length`),1);
 const cardNotesBefore=item.entries.map(entry=>entry.notes);
 await setValue('[name="processing_tier"]','express');await setValue('select[name="upgrade_ids"]','detailed');await setValue('[name="order_notes"]','Whole order note');
 await click('Save order choices and notes');await until(()=>configurationWrites.length===1);
 assert.ok(item.entries.every(entry=>entry.processing_tier==='express'&&entry.upgrade_ids[0]==='detailed'));
 assert.deepEqual(item.entries.map(entry=>entry.notes),cardNotesBefore);
 await send('Page.navigate',{url:'http://127.0.0.1:18172/standards'});
 await until(()=>evaluate(`location.pathname==='/standards'`));
 await send('Page.navigate',{url:'http://127.0.0.1:18172/account/submissions/catalog-fixture'});
 await until(async()=>await value('processing_tier')==='express');
 assert.equal(await value('upgrade_ids'),'detailed');assert.equal(await value('order_notes'),'Whole order note');
 // Legacy exceptions remain intact through reads and a notes-only save.
 item.entries[1].processing_tier='priority';item.version++;
 const legacy=item.entries.map(entry=>[entry.processing_tier,[...entry.upgrade_ids]]);
 await send('Page.reload');
 await until(()=>evaluate(`document.body.textContent.includes('This draft has different per-card configurations')`));
 assert.deepEqual(item.entries.map(entry=>[entry.processing_tier,[...entry.upgrade_ids]]),legacy);
 assert.equal(await evaluate(`document.querySelectorAll('select[name="processing_tier"]:enabled').length`),0);
 assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Review submission').disabled`),true);
 const noteWritesBefore=orderNoteWrites.length;
 await setValue('[name="order_notes"]','Legacy notes without replacement');await click('Save order notes');await until(()=>orderNoteWrites.length===noteWritesBefore+1);
 assert.equal(configurationWrites.length,1);assert.deepEqual(item.entries.map(entry=>[entry.processing_tier,[...entry.upgrade_ids]]),legacy);
 await until(()=>evaluate(`!!document.querySelector('.order-configuration input[type="checkbox"]')`));
 await evaluate(`document.querySelector('.order-configuration input[type="checkbox"]').click()`);
 await until(()=>evaluate(`document.querySelectorAll('select[name="processing_tier"]:enabled').length===1`));
 await setValue('[name="processing_tier"]','priority');await setValue('select[name="upgrade_ids"]','classic');await click('Save order choices and notes');
 await until(()=>configurationWrites.length===2);
 assert.ok(item.entries.every(entry=>entry.processing_tier==='priority'&&entry.upgrade_ids[0]==='classic'));
 await until(()=>evaluate(`!document.querySelector('[name="card_name"]').matches(':disabled')`));
 await setValue('[name="card_name"]','Inherited card');await setValue('[name="language"]','EN');await click('Save card');await until(()=>item.entries.length===4);
 assert.equal(item.entries[3].processing_tier,'priority');assert.deepEqual(item.entries[3].upgrade_ids,['classic']);
 await until(()=>evaluate(`!!Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Generate / recalculate quote'&&!button.disabled)`));
 await click('Generate / recalculate quote');await until(()=>quotes.length===1);
 const oldQuote=quotes[0];const oldSnapshot=JSON.stringify(oldQuote.snapshot);
 assert.equal(oldQuote.snapshot.total_minor,item.card_count*2000);
 await setValue('[name="processing_tier"]','express');await setValue('select[name="upgrade_ids"]','detailed');await click('Save order choices and notes');await until(()=>configurationWrites.length===3);
 assert.equal(oldQuote.status,'invalidated');assert.equal(JSON.stringify(oldQuote.snapshot),oldSnapshot);
 await until(()=>evaluate(`!!Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Generate / recalculate quote'&&!button.disabled)`));
 await click('Generate / recalculate quote');await until(()=>quotes.length===2);
 assert.equal(quotes[0].snapshot.total_minor,item.card_count*1800);
 assert.equal(await evaluate(`document.querySelectorAll('select[name="processing_tier"]').length`),1);
 assert.equal(await evaluate(`document.querySelectorAll('select[name="upgrade_ids"]').length`),1);
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert.equal(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`),true);
 assert.equal(await evaluate(`Array.from(document.querySelectorAll('.order-configuration select,.order-configuration textarea')).every(control=>control.labels.length>0)`),true);
 await send('Emulation.clearDeviceMetricsOverride');
 const article=`Array.from(document.querySelectorAll('article.info-card')).find(el=>el.querySelector('h3')?.textContent.includes('Photo card'))`;
 await until(()=>evaluate(`!!(${article})`));
 await evaluate(`(${article}).querySelector('summary').click()`);
 assert.equal(await evaluate(`(${article}).querySelector('input[capture]').getAttribute('capture')`),'environment');
 const selectPhoto=async side=>{
  const result=await send('Runtime.evaluate',{expression:`(${article}).querySelectorAll('input[type="file"]')[${side==='front'?0:2}]`});
  await send('DOM.setFileInputFiles',{objectId:result.result.objectId,files:[photoFixture]});
  await until(()=>evaluate(`(${article}).textContent.includes('Local preview')`));
  assert.ok(await evaluate(`Array.from((${article}).querySelectorAll('img')).some(img=>img.src.startsWith('blob:'))`));
 };
 await selectPhoto('front');await click('Save photo');await until(()=>photoEntry.pre_shipment_photos?.length===1);
 const originalFront=photoEntry.pre_shipment_photos[0].id;
 await selectPhoto('back');await click('Save photo');await until(()=>photoEntry.pre_shipment_photos.length===2);
 await selectPhoto('front');await click('Save photo');await until(()=>photoEntry.pre_shipment_photos.find(p=>p.side==='front').id!==originalFront);
 assert.equal(photoEntry.pre_shipment_photos.length,2);
 await evaluate(`(${article}).querySelectorAll('.submission-photo-slot')[1].querySelector('button').click()`);
 await until(()=>photoEntry.pre_shipment_photos.length===1);
 // Second identical physical copy gets its own front reference.
 await evaluate(`(()=>{const select=(${article}).querySelector('select');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,'2');select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await selectPhoto('front');await click('Save photo');await until(()=>photoEntry.pre_shipment_photos.length===2);
 assert.deepEqual(photoEntry.pre_shipment_photos.map(p=>p.copy_number).sort(),[1,2]);
 photoFailure=true;await selectPhoto('back');await click('Save photo');
 await until(()=>evaluate(`(${article}).textContent.includes('Upload could not be confirmed.')`));
 assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Save card').disabled`),false,'upload failure does not block manual registration');
 photoFailure=false;
 await send('Page.reload');await until(()=>evaluate(`!!(${article})`));
 await evaluate(`(${article}).querySelector('summary').click()`);
 await until(()=>evaluate(`Array.from((${article}).querySelectorAll('img')).some(img=>img.complete&&img.naturalWidth===2)`));
 const snapshot=JSON.stringify(photoEntry.pre_shipment_photos);
 await click('Review submission');
 assert.equal(await evaluate(`(${article}).querySelectorAll('input[type="file"]').length`),0);
 await click('Confirm submission');await until(()=>item.status==='submitted');
 await until(()=>evaluate(`document.querySelectorAll('select[name="processing_tier"]').length===0`));
 assert.equal(JSON.stringify(photoEntry.pre_shipment_photos),snapshot);
 assert.equal(await evaluate(`(${article}).querySelectorAll('input[type="file"]').length`),0);
 // Return preparation keeps the saved parcel while customer saves only address/value.
 await until(()=>evaluate(`!!document.querySelector('[name="declared"]')`));
 for(const field of ['weight_g','length_mm','width_mm','height_mm'])assert.equal(await evaluate(`document.querySelector('[name="${field}"]')===null`),true);
 assert.equal(await evaluate(`document.querySelector('[name="service"]')===null`),true);
 assert.ok(await evaluate(`document.body.textContent.includes('No return service is available')`));
 assert.ok(await evaluate(`document.body.textContent.includes('SELBY will package the cards after encapsulation')`));
 assert.ok(await evaluate(`document.body.textContent.includes('Development estimate without commercial validity')`));
 assert.ok(await evaluate(`document.body.textContent.includes('Pending tax validation')`));
 assert.equal(await evaluate(`document.querySelector('[name="declared"]').getAttribute('aria-describedby')`),'return-value-help');
 assert.equal(await evaluate(`document.querySelector('a[href="/account/settings"]')!==null`),true);
 const savedParcel=JSON.stringify(returnDelivery.parcel);
 await setValue('[name="address"]','address-fr');await setValue('[name="declared"]','1250,50');
 await evaluate(`document.querySelector('[name="declared"]').form.requestSubmit()`);
 await until(()=>deliveryWrites.length===1);
 assert.deepEqual(deliveryWrites[0],{version:0,address_id:'address-fr',declared_value_minor:125050});
 assert.equal(JSON.stringify(returnDelivery.parcel),savedParcel);assert.equal(returnDelivery.service_id,'legacy-unavailable');
 await send('Page.reload');await until(async()=>await value('declared')==='1250.50');
 assert.equal(await value('address'),'address-fr');
 assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Payment unavailable').disabled`),true);
 assert.ok(await evaluate(`document.body.textContent.includes('Final payable amount: Undetermined')`));
 console.log('PASS: return address/value, no customer measurements or empty service selector, draft reload, legacy parcel preservation, development/tax warnings and payment block');
 console.log('PASS: name-first printings, optional set, 43-row dropdowns, keyboard/mouse, rerenders, resets, manual drafts, cancellation, loading/error/retry/empty, localization');
 console.log('PASS: manual-first optional text, per-copy front/back photos, real file selection, preview, replacement/removal, upload failure fallback, reload and read-only confirmation');
 console.log('PASS: one editable speed/label pair, distinct card/order notes, atomic settings, navigation persistence, explicit legacy conversion, new-card inheritance, quote consistency, mobile labels and confirmed read-only configuration');
}finally{socket?.close();chrome.kill();next.kill();server.closeAllConnections();server.close();}
