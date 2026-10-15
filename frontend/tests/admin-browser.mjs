// Production-browser regression / screenshots with synthetic data only.
// Run after npm run build: npm run test:admin-browser
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { once } from 'node:events';

const output = resolve('.visual-review/admin');
await mkdir(output, { recursive: true });
const labelFixture=await readFile(resolve('../backend/label_samples/sample-50x30.pdf'));
const stamp = '2026-10-14T10:00:00Z';
const detail = {
  id: 'submission-fixture', reference: 'SP-2026-INTAKE-001', customer_reference: '9eead62a-5b9d-4329-aa73-602739791cc4',
  status: 'reconciliation_pending', declared_quantity: 36, received_quantity: 36,
  submitted_at: stamp, commercially_accepted: true, operational_override: true,
  entries: Array.from({ length: 12 }, (_, i) => ({ id: `entry-${i}`, card_name: `Collector card ${i + 1}`, game: 'pokemon', expansion: 'Collection édition spéciale', card_number: `${i + 1}/102`, language: 'FR', quantity: 3 })),
  parcels: [{ id: 'parcel-1', reference: 'PARCEL-2026-001', carrier: 'Colissimo', tracking: 'TRACKING-001', notes: 'Packaging intact. Receipt recorded by intake staff.', status: 'reconciling', received_at: stamp }],
  cards: Array.from({ length: 36 }, (_, i) => ({ id: `card-${i}`, reference: `PC-${(i+1).toString(16).toUpperCase().padStart(32,'0')}`, parcel_id: 'parcel-1', entry_id: i < 30 ? `entry-${Math.floor(i / 3)}` : null, notes: 'Review condition and declared identity before matching.', status: i < 30 ? 'matched' : 'unidentified' })),
  discrepancies: [{ id: 'issue-1', card_id: 'card-35', entry_id: null, kind: 'damaged', quantity: 1, notes: 'Corner damage recorded on arrival.', status: 'open', resolution: null }],
  events: Array.from({ length: 10 }, (_, i) => ({ id: `event-${i}`, actor_id: 'staff-fixture', action: 'physical_card_created', entity_id: `card-${i}`, data: { reference: `CARD-${i + 1}` }, reason: 'Physical receipt', created_at: stamp })),
};
const customerId = detail.customer_reference;
const customer = { id: customerId, first_name: 'Claire', last_name: 'Collector', email: 'claire@example.invalid',
  status: 'active', email_verified: true, created_at: stamp, saved_addresses: [{ id:'address-fixture',recipient:'Shipment recipient',line1:'1 Example Street',line2:'',postal_code:'75001',city:'Paris',country:'FR',phone:'+33123456789',instructions:'Shipment instructions' }], addresses_truncated: false };
const directory = [customer, ...Array.from({length:26},(_,i) => ({...customer,id:`${(i+1).toString(16).padStart(8,'0')}-5b9d-4329-aa73-602739791cc4`,first_name:`Customer ${i+2}`,email:`customer-${i+2}@example.invalid`}))];
const submissionHistory = Array.from({length:27},(_,i) => ({id:i===0?detail.id:`history-${i}`,reference:i===0?detail.reference:`SP-HISTORY-${i}`,status:i===1?'draft':'submitted',created_at:stamp,confirmed_at:i===1?null:stamp,declared_quantity:i===0?36:2,intake_status:i===0?detail.status:null,return_address:i===0?{...customer.saved_addresses[0],recipient:'Historical shipment recipient'}:i===1?customer.saved_addresses[0]:null,return_address_source:i===0?'accepted_snapshot':i===1?'current_selection':null}));
const cardReference = 'PC-'+'A'.repeat(32);
const trace = {card:{id:'card-fixture',reference:cardReference,status:'matched'},parcel:detail.parcels[0],submission:detail,customer,declared_entry:detail.entries[0]};
let operationsFailure = false;
let staffStatus = 200;
let staffLanguage = 'EN';
let role = 'admin';
const backend = createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');
  if (req.url === '/internal/intake/me') { res.statusCode=staffStatus; res.end(JSON.stringify({ role, language: staffLanguage })); }
  else { res.statusCode = 404; res.end('{}'); }
});
backend.listen(18091, '127.0.0.1');
await once(backend, 'listening');
const server = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '18092'], {
  env: { ...process.env, SPECTRA_BACKEND_URL: 'http://127.0.0.1:18091' }, windowsHide: true, stdio: 'pipe',
});
let serverLog = '';
server.stdout.on('data', data => { serverLog += data; });
server.stderr.on('data', data => { serverLog += data; });
const chrome = spawn(process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=18093', `--user-data-dir=${resolve(output, 'profile')}`, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
chrome.on('error', error => { console.error(error.message); });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check, description) {
  for (let i = 0; i < 100; i++) { if (await check()) return; await sleep(100); }
  throw new Error(`Timed out: ${description}`);
}
let socket;
try {
  await waitFor(async () => { try { return (await fetch('http://127.0.0.1:18092/standards')).ok; } catch { return false; } }, 'Next server: ' + serverLog);
  let targets;
  await waitFor(async () => { try { targets = await (await fetch('http://127.0.0.1:18093/json/list')).json(); return targets.some(t => t.type === 'page'); } catch { return false; } }, 'Chrome debugging endpoint');
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await once(socket, 'open');
  let sequence = 0;
  const pending = new Map();
  const errors = [];
  const mutations = [];
  const labelRequests=[];
  let failCreation = false;
  function send(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  socket.addEventListener('message', async event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const job = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) job.reject(new Error(message.error.message)); else job.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    else if (message.method === 'Fetch.requestPaused') {
      const { requestId, request } = message.params;
      const url = new URL(request.url);
      if(url.pathname.startsWith('/internal/labels/')) {
        labelRequests.push({path:url.pathname,headers:request.headers,body:request.postData?JSON.parse(request.postData):null});
        await send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/pdf'},{name:'Cache-Control',value:'private, no-store'}],body:labelFixture.toString('base64')});
        return;
      }
      let responseCode = 200;
      let body;
      if (url.pathname.startsWith('/internal/customer-operations')) {
        if (operationsFailure) { responseCode=503;body={detail:'service_unavailable'}; }
        else if (url.pathname.endsWith('/customers')) {
          const search=(url.searchParams.get('search')??'').toLowerCase();
          const offset=Number(url.searchParams.get('offset')??0);
          const matches=directory.filter(c => !search || `${c.first_name} ${c.last_name} ${c.email}`.toLowerCase().includes(search) || c.id===search);
          body={items:matches.slice(offset,offset+25),limit:25,offset,has_more:matches.length>offset+25};
        } else if (url.pathname.includes('/cards/')) {
          if(url.pathname.endsWith(cardReference)) body=trace;
          else {responseCode=404;body={detail:'card_not_found'};}
        } else if(url.pathname.includes(customerId)) {
          if(url.pathname.endsWith('/submissions')) {
            const offset=Number(url.searchParams.get('offset')??0);
            body={items:submissionHistory.slice(offset,offset+25),limit:25,offset,has_more:submissionHistory.length>offset+25};
          } else body=customer;
        } else {responseCode=404;body={detail:'customer_not_found'};}
      } else if (url.pathname === '/api/auth/csrf') body = { csrf_token: 'fixture-csrf' };
      else if (request.method === 'POST') {
        mutations.push({ path: url.pathname, headers: request.headers, body: JSON.parse(request.postData) });
        if (failCreation) { responseCode = 409; body = { detail: 'idempotency_conflict' }; }
        else body = { id: 'synthetic-result' };
      } else body = url.pathname === '/internal/intake/submissions' ? [detail] : detail;
      await send('Fetch.fulfillRequest', { requestId, responseCode, responseHeaders: [{ name: 'Content-Type', value: 'application/json' },{name:'Cache-Control',value:'private, no-store'}], body: Buffer.from(JSON.stringify(body)).toString('base64') });
    }
  });
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*/internal/intake/*' }, { urlPattern: '*/internal/customer-operations/*' }, {urlPattern:'*/internal/labels/*'}, { urlPattern: '*/api/auth/csrf' }] });
  async function evaluate(expression) {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
  async function navigate(path) {
    await send('Page.navigate', { url: 'http://127.0.0.1:18092' + path });
    await waitFor(() => evaluate(`location.pathname === ${JSON.stringify(path)} && document.readyState === 'complete'`), path);
    await evaluate("document.documentElement.style.scrollBehavior = 'auto'");
  }
  async function screenshot(name) {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    await writeFile(resolve(output, name + '.png'), Buffer.from(data, 'base64'));
  }
  async function click(selector) {
    const point = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.scrollIntoView({block:'center'}); const r = el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', button: 'left', clickCount: 1, ...point });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', button: 'left', clickCount: 1, ...point });
  }
  async function input(selector, value) {
    await evaluate(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)}); el.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  }
  async function checkLayout() {
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'No page-level horizontal overflow');
    assert.equal(await evaluate('document.querySelectorAll("main").length'), 1, 'One main landmark');
    assert.equal(await evaluate('[...document.querySelectorAll(".intake-workspace input, .intake-workspace select")].every(el => el.labels.length > 0)'), true, 'Semantic labels');
    assert.equal(await evaluate('parseFloat(getComputedStyle(document.querySelector(".intake-workspace")).paddingLeft) >= 20'), true, 'Shared page gutters');
    assert.equal(await evaluate('getComputedStyle(document.querySelector(".intake-workspace input")).minHeight'), '48px', 'Compiled control styles');
  }
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await navigate('/admin');
    await waitFor(() => evaluate('!!document.querySelector("tbody button")'), 'submission list loaded');
    await checkLayout();
    await screenshot(name + '-list');
    await click('tbody button');
    await waitFor(() => evaluate('!!document.querySelector("#intake-inventory")'), 'detail loaded');
    await checkLayout();
    assert.equal(await evaluate('document.querySelectorAll("#intake-inventory article").length'), 36);
    assert.equal(await evaluate('document.querySelectorAll("#intake-inventory details[open]").length'), 0, 'Inventory forms start compact');
    await evaluate('scrollTo(0,0)');
    await screenshot(name + '-detail');
    await evaluate('document.querySelector("#intake-inventory").scrollIntoView()');
    await screenshot(name + '-inventory');
    const initialLabelRequests=labelRequests.length;
    await click('.physical-label-panel > .intake-toolbar button:first-child');
    assert.equal(await evaluate('document.querySelectorAll(".card-label-actions input:checked").length'),36);
    await click('.physical-label-panel > .intake-toolbar button:nth-child(3)');
    await waitFor(()=>evaluate('!!document.querySelector(".label-preview iframe")'),'batch preview');
    assert.equal(labelRequests.length,initialLabelRequests+1,'One PDF request per batch');
    assert.equal(labelRequests.at(-1).body.references.length,36);
    assert.equal(labelRequests.at(-1).headers['X-Csrf-Token']??labelRequests.at(-1).headers['X-CSRF-Token'],'fixture-csrf');
    assert.equal(await evaluate('document.querySelectorAll(".label-preview a[target=_blank]").length'),1,'Single PDF printing workflow');
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'),true);
    await screenshot(name+'-labels');
    await click('.label-preview button');
    await click('#intake-inventory article .card-label-actions button:last-child');
    await waitFor(()=>evaluate('!!document.querySelector(".label-preview iframe")'),'individual reprint preview');
    assert.equal(labelRequests.at(-1).body.references.length,1);
    await click('.label-preview button');
    await click('#intake-inventory article summary');
    assert.equal(await evaluate('!!document.querySelector("#intake-inventory details[open] select")'), true);
    await evaluate(`document.querySelector('.intake-language select').value='FR'; document.querySelector('.intake-language select').dispatchEvent(new Event('change',{bubbles:true}))`);
    await waitFor(() => evaluate('document.querySelector("#intake-title").textContent === "Réception physique"'), 'French language switch');
    assert.equal(await evaluate('document.querySelector(".intake-finalize").textContent.includes("fige")'), true);
    await evaluate(`document.querySelector('.intake-language select').value='EN'; document.querySelector('.intake-language select').dispatchEvent(new Event('change',{bubbles:true}))`);
    await waitFor(() => evaluate('document.querySelector("#intake-title").textContent === "Physical intake"'), 'English language switch');
    await evaluate('document.querySelector(".intake-finalize").scrollIntoView({block:"center"})');
    await screenshot(name + '-finalization');
    // Keyboard focus and hit testing must reach footer anchors on both viewports.
    for (const [href, expected] of [['/standards', 'Every detail tells a story.'], ['/how-it-works', 'Your collection. The next chapter.']]) {
      const selector = `.site-footer nav a[href="${href}"]`;
      assert.equal(await evaluate(`(() => { const a=document.querySelector(${JSON.stringify(selector)}); a.scrollIntoView({block:'center'}); a.focus(); const r=a.getBoundingClientRect(); return document.activeElement===a && a.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)) && r.height>=44; })()`), true, 'Footer link not obscured and keyboard focusable');
      if (href === '/standards') await screenshot(name + '-footer');
      if (href === '/standards') await click(selector);
      else { await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }); }
      await waitFor(() => evaluate(`location.pathname===${JSON.stringify(href)} && document.querySelector('h1')?.textContent===${JSON.stringify(expected)}`), 'footer navigation ' + href);
    }
    await navigate('/admin/customers');
    await waitFor(() => evaluate('document.querySelectorAll("tbody tr").length===25'), 'directory page 1');
    assert.equal(await evaluate(`document.querySelector('.admin-navigation a[href="/admin/customers"]').getAttribute('aria-current')`), 'page');
    await checkLayout();
    await screenshot(name+'-customers');
    await click('.operations-pagination button:last-child');
    await waitFor(() => evaluate('document.querySelectorAll("tbody tr").length===2'), 'directory page 2');
    await click('.operations-pagination button:first-child');
    await waitFor(() => evaluate('document.querySelectorAll("tbody tr").length===25'), 'directory previous');
    await input('.operations-search input', 'Claire');
    await click('.operations-search button');
    await waitFor(() => evaluate('document.querySelectorAll("tbody tr").length===1'), 'directory name search');
    await click('tbody a');
    await waitFor(() => evaluate('document.querySelector("#customer-account-title")?.textContent === "Customer account"'), 'customer detail');
    assert.equal(await evaluate('document.body.textContent.includes("Shipment recipient") && document.body.textContent.includes("No account phone number")'), true);
    assert.equal(await evaluate('document.querySelectorAll("#history-title + .operations-feedback + .intake-scroll tbody tr").length'),25);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    await screenshot(name+'-customer-detail');
    await click('.operations-shipment summary');
    assert.equal(await evaluate('document.body.textContent.includes("Historical return address recorded")'),true);
    await click('a[href="/admin/submissions/submission-fixture"]');
    await waitFor(() => evaluate('!!document.querySelector("#intake-inventory")'), 'direct intake route');
    assert.equal(await evaluate(`document.querySelector('#overview-title').textContent===${JSON.stringify(detail.reference)}`),true);
    assert.equal(await evaluate(`document.querySelector('#intake-inventory article a').getAttribute('href')==='/admin/customers/${customerId}'`),true);
    await click('.intake-metrics a');
    await waitFor(() => evaluate('!!document.querySelector("#customer-account-title")'), 'submission to customer link');
    await click('.admin-navigation a[href="/admin/cards"]');
    await waitFor(() => evaluate('document.querySelector("h1")?.textContent === "Physical-card traceability"'), 'lookup route');
    await input('.operations-search input', 'PC-bad');
    await click('.operations-search button');
    assert.equal(await evaluate('document.querySelector("[role=status]").textContent.includes("valid PC-")'),true);
    await input('.operations-search input','PC-'+'B'.repeat(32));
    await click('.operations-search button');
    await waitFor(() => evaluate('document.querySelector("[role=status]").textContent.includes("not found")'), 'unknown reference');
    await input('.operations-search input',cardReference.toLowerCase());
    await click('.operations-search button');
    await waitFor(() => evaluate('!!document.querySelector("#card-trace-title")'), 'exact trace lookup');
    assert.equal(await evaluate(`document.querySelector('#card-trace-title').textContent===${JSON.stringify(cardReference)}`),true);
    assert.equal(await evaluate('document.body.textContent.includes("claire@example.invalid")'),true);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    await screenshot(name+'-card-trace');
    await input('.operations-search input','SP:PC:1:'+cardReference);
    await send('Runtime.evaluate',{expression:"document.querySelector('.operations-search input').focus()"});
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
    await waitFor(()=>evaluate('!!document.querySelector("#card-trace-title")'),'QR keyboard scanner lookup');
    await evaluate(`document.querySelector('.intake-language select').value='FR'; document.querySelector('.intake-language select').dispatchEvent(new Event('change',{bubbles:true}))`);
    await waitFor(() => evaluate('document.querySelector("h1").textContent === "Traçabilité des cartes physiques"'), 'lookup French');
    assert.equal(await evaluate('document.querySelector(".admin-navigation").textContent.includes("Clients")'),true,'Language switch updates protected navigation');
    await navigate('/admin/customers');
    await waitFor(() => evaluate('!!document.querySelector("tbody")'), 'directory reset');
    await input('.operations-search input','no-match');
    await click('.operations-search button');
    await waitFor(() => evaluate('document.querySelector("[role=status]").textContent.includes("No records")'), 'empty search');
    operationsFailure=true;
    await input('.operations-search input','Claire');
    await click('.operations-search button');
    await waitFor(() => evaluate('document.querySelector("[role=status]").textContent.includes("Service unavailable")'), 'directory error');
    operationsFailure=false;
    await click('[role=status] button');
    await waitFor(() => evaluate('document.querySelectorAll("tbody tr").length===1'), 'directory retry');
    console.log(`${name}: customer search/pagination, detail/snapshots, direct intake/customer links, card lookup, FR/EN, empty/error/retry, responsive layout passed`);
    console.log(`${name}: list, detail, 36 cards, labels, styles, French/English, footer mouse/keyboard navigation passed`);
  }
  staffLanguage='FR';
  await navigate('/admin/customers');
  await waitFor(() => evaluate('document.querySelector(".admin-navigation").textContent.includes("Clients")'), 'French protected navigation');
  staffLanguage='EN';
  for (const path of ['/admin/customers','/admin/cards',`/admin/customers/${customerId}`, '/admin/submissions/submission-fixture']) {
    const response=await fetch('http://127.0.0.1:18092'+path);
    assert.ok(response.headers.get('cache-control').includes('no-store'), 'Private admin route cache header');
    assert.equal(response.headers.get('referrer-policy'),'no-referrer');
  }
  staffStatus=401;
  await send('Page.navigate',{url:'http://127.0.0.1:18092/admin/customers'});
  await waitFor(() => evaluate('location.pathname === "/login"'), 'anonymous server-side redirect');
  staffStatus=200;
  await navigate('/admin');
  await waitFor(() => evaluate('!!document.querySelector("tbody button")'), 'list');
  await click('tbody button');
  await waitFor(() => evaluate('!!document.querySelector(".intake-finalize")'), 'finalization form');
  // Dismiss confirmation: no POST. Accept: existing CSRF + reason/action payload.
  await evaluate(`window.confirm = message => { window.lastConfirmation = message; return false; }; document.querySelector('.intake-finalize input').value='Reviewed inventory and discrepancies'`);
  await click('.intake-finalize button');
  assert.equal(mutations.length, 0);
  assert.equal(await evaluate('window.lastConfirmation.includes("cannot be undone")'), true);
  await evaluate('window.confirm = () => true');
  await click('.intake-finalize button');
  await waitFor(() => Promise.resolve(mutations.length === 1), 'finalization POST');
  assert.equal(mutations[0].body.action, 'complete');
  assert.equal(mutations[0].body.reason, 'Reviewed inventory and discrepancies');
  assert.equal(mutations[0].headers['X-Csrf-Token'] ?? mutations[0].headers['X-CSRF-Token'], 'fixture-csrf');
  await waitFor(() => evaluate('!document.querySelector(".intake-finalize button").disabled'), 'save finished');
  failCreation = true;
  await click('#intake-parcels button');
  await waitFor(() => Promise.resolve(mutations.length === 2), 'parcel POST');
  await waitFor(() => evaluate('document.querySelector("[role=status]").textContent.includes("previous request")'), 'localized conflict');
  await click('#intake-parcels button');
  await waitFor(() => Promise.resolve(mutations.length === 3), 'parcel retry');
  assert.equal(mutations[1].body.request_key, mutations[2].body.request_key, 'Retry preserves idempotency key');
  detail.status = 'reconciled';
  await navigate('/admin');
  await waitFor(() => evaluate('!!document.querySelector("tbody button")'), 'reconciled list');
  await click('tbody button');
  await waitFor(() => evaluate('!!document.querySelector("#intake-parcels fieldset")'), 'frozen detail');
  assert.equal(await evaluate('[...document.querySelectorAll(".intake-form fieldset")].every(el => el.disabled)'), true);
  assert.equal(await evaluate('document.querySelector(".card-label-actions button").disabled'),false,'Frozen cards remain printable');
  await click('.card-label-actions button');
  await waitFor(()=>evaluate('!!document.querySelector(".label-preview iframe")'),'frozen-card PDF preview');
  detail.status = 'reconciliation_pending'; detail.operational_override = false; role = 'operator';
  await navigate('/admin');
  await waitFor(() => evaluate('!!document.querySelector("tbody button")'), 'operator list');
  await click('tbody button');
  await waitFor(() => evaluate('!!document.querySelector("#intake-authorization")'), 'operator detail');
  assert.equal(await evaluate('document.querySelector("#intake-authorization").textContent.includes("Authorize processing without")'), false, 'Operator cannot see admin override');
  assert.deepEqual(errors, [], 'No browser runtime errors');
  console.log('Finalization confirmation, CSRF, idempotent retry, frozen controls, operator restriction passed');
  console.log('Screenshots: .visual-review/admin/*.png');
} finally {
  socket?.close();
  chrome.kill();
  server.kill();
  backend.close();
}
