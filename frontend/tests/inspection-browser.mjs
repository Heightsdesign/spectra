// Synthetic browser fixtures exercise UI behavior; they never authorize production APIs.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const output = resolve('.visual-review/inspection');
await mkdir(output, { recursive: true });
const ref = 'PC-' + 'A'.repeat(32);
const stamp = '2026-10-17T10:00:00Z';
let language = 'EN';
const backend = createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ id: 'staff-fixture', role: 'operator', language }));
});
backend.listen(18191, '127.0.0.1');
await once(backend, 'listening');
const next = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '18192'], {
  env: { ...process.env, SPECTRA_BACKEND_URL: 'http://127.0.0.1:18191' }, windowsHide: true, stdio: 'pipe',
});
let serverLog = '';
next.stdout.on('data', b => { serverLog += b; });
next.stderr.on('data', b => { serverLog += b; });
const chrome = spawn(process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=18193', `--user-data-dir=${resolve(output, 'profile')}`, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
chrome.on('error', error => { console.error(error.message); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitFor(check, name) {
  for (let i = 0; i < 150; i++) { if (await check()) return; await sleep(100); }
  throw Error('Timed out: ' + name + '\n' + serverLog);
}
let socket;
let blocked = true;
let fixture;
let confirmation = true;
const commands = [];
let dialogs = 0;
const errors = [];
function reset() {
  const allowed = { eligible: true, reasons: [] };
  fixture = {
    card: { reference: ref }, submission: { id: 'submission-fixture', reference: 'SP-' + 'B'.repeat(32), customer_id: 'customer-fixture' },
    entry: { card_name: 'Synthetic collector card', expansion: 'Inspection test set', card_number: '1/100', language: 'FR' },
    inspection: null, eligibility: Object.fromEntries(['start', 'pause', 'resume', 'image'].map(op => [op, allowed])), images: [], custody: [],
  };
}
function result() {
  const value = structuredClone(fixture);
  if (blocked) for (const op of Object.keys(value.eligibility)) value.eligibility[op] = { eligible: false, reasons: [{ code: 'payment_unverified', en: 'Independent payment confirmation unavailable.', fr: 'Confirmation indépendante du paiement indisponible.' }] };
  return value;
}
try {
  await waitFor(async () => { try { return (await fetch('http://127.0.0.1:18192/login')).ok; } catch { return false; } }, 'Next');
  let targets;
  await waitFor(async () => { try { targets = await (await fetch('http://127.0.0.1:18193/json/list')).json(); return targets.some(t => t.type === 'page'); } catch { return false; } }, 'Chrome');
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await once(socket, 'open');
  let sequence = 0;
  const pending = new Map();
  function send(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
  }
  socket.addEventListener('message', async event => {
    const m = JSON.parse(event.data);
    if (m.id) { const job = pending.get(m.id); pending.delete(m.id); if (m.error) job.reject(Error(m.error.message)); else job.resolve(m.result); }
    else if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text);
    else if (m.method === 'Page.javascriptDialogOpening') { dialogs++; await send('Page.handleJavaScriptDialog', { accept: confirmation }); }
    else if (m.method === 'Fetch.requestPaused') {
      const { requestId, request } = m.params;
      const path = new URL(request.url).pathname;
      let body;
      if (path === '/api/auth/csrf') body = { csrf_token: 'fixture-csrf' };
      else if (request.method === 'POST') {
        const payload = JSON.parse(request.postData);
        assert.equal(request.headers['X-Csrf-Token'] ?? request.headers['X-CSRF-Token'], 'fixture-csrf');
        commands.push({ path, payload });
        const old = fixture.inspection;
        if (path.endsWith('/command')) {
          const paused = payload.action === 'pause';
          fixture.inspection = { id: 'inspection-fixture', status: paused ? 'paused' : 'in_progress', location: paused ? 'inspection_hold_storage' : 'inspection_workstation', version: (old?.version ?? 0) + 1 };
          fixture.custody.push({ id: crypto.randomUUID(), actor_id: 'staff-fixture', source: old?.location ?? 'secure_intake_storage', destination: fixture.inspection.location, reason: payload.reason, created_at: stamp });
        } else {
          fixture.images.push({ id: crypto.randomUUID(), side: payload.side, version: fixture.images.filter(i => i.side === payload.side).length + 1, sha256: payload.sha256 });
          fixture.inspection.version++;
        }
        body = result();
      } else body = result();
      await send('Fetch.fulfillRequest', { requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from(JSON.stringify(body)).toString('base64') });
    }
  });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*/internal/inspection/*' }, { urlPattern: '*/api/auth/csrf' }] });
  async function evaluate(expression) {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw Error(r.exceptionDetails.text);
    return r.result.value;
  }
  async function input(selector, value) {
    await evaluate(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)}); el.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  }
  async function scan() {
    await input('#inspection-scan', 'SP:PC:1:' + ref);
    await evaluate(`document.querySelector('#inspection-scan').focus()`);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', text: '\r', unmodifiedText: '\r', windowsVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    try {
      await waitFor(() => evaluate('!!document.querySelector(".inspection-identity")'), 'scan result');
    } catch (error) {
      console.error(await evaluate('document.querySelector(".inspection-workstation").innerText'), errors);
      throw error;
    }
  }
  async function layout() {
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'No horizontal overflow');
    assert.equal(await evaluate('[...document.querySelectorAll(".inspection-workstation input, .inspection-workstation select")].every(el=>el.labels.length>0)'), true, 'Labelled controls');
    assert.equal(await evaluate('document.querySelectorAll("main").length'), 1, 'One main landmark');
  }
  for (const [width, height] of [[1440, 1000], [390, 844]]) for (const lang of ['FR', 'EN']) {
    language = lang; blocked = true; reset();
    const before = commands.length;
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: 'http://127.0.0.1:18192/admin/inspection' });
    await waitFor(() => evaluate('document.readyState === "complete" && !!document.querySelector("#inspection-scan")'), 'workstation');
    await sleep(500); // Let React attach form handlers before emulating scanner input.
    await scan();
    assert.equal(commands.length, before, 'Scanning never mutates');
    assert.equal(await evaluate('document.querySelector("[data-action=start]").disabled'), true, 'Payment block');
    assert.equal(await evaluate('document.querySelector("[data-reason=payment_unverified]").textContent'), lang === 'FR' ? 'Confirmation indépendante du paiement indisponible.' : 'Independent payment confirmation unavailable.');
    await layout();
    const { data: screenshot } = await send('Page.captureScreenshot', { format: 'png' });
    await writeFile(resolve(output, `${width}-${lang}-blocked.png`), Buffer.from(screenshot, 'base64'));
    blocked = false;
    await scan(); await input('#inspection-reason', 'Confirmed synthetic physical handover');
    confirmation = false;
    await evaluate('document.querySelector("[data-action=start]").click()');
    await sleep(100);
    assert.equal(commands.length, before, 'Cancel does not start');
    confirmation = true;
    await evaluate('document.querySelector("[data-action=start]").click()');
    await waitFor(() => evaluate('!!document.querySelector("[data-action=pause]")'), 'explicit start');
    assert.equal(commands.length, before + 1);
    assert.equal(await evaluate('document.querySelector("[data-image-status=front]").textContent'), lang === 'FR' ? 'Absente' : 'Missing');
    await evaluate('document.querySelector("[data-action=pause]").click()');
    await waitFor(() => evaluate('!!document.querySelector("[data-action=resume]")'), 'pause');
    await evaluate('document.querySelector("[data-action=resume]").click()');
    await waitFor(() => evaluate('!!document.querySelector("[data-action=pause]")'), 'resume');
    assert.equal(await evaluate('document.querySelectorAll(".inspection-history li").length'), 3);
    // Browser-created File exercises the same acquisition path as a file picker.
    for (const side of ['front', 'back']) {
      await evaluate(`(() => { const transfer=new DataTransfer(); transfer.items.add(new File([new Uint8Array([1,2,3,4])], '${side}.png', {type:'image/png'})); const el=document.querySelector('#inspection-${side}'); el.files=transfer.files; el.dispatchEvent(new Event('change',{bubbles:true})); })()`);
      await waitFor(() => evaluate(`document.querySelector('[data-image-status=${side}]').textContent===${JSON.stringify(lang === 'FR' ? 'Présente' : 'Present')}`), side + ' association');
    }
    await layout();
    assert.equal(await evaluate('document.querySelector("[data-testid=inspection-status]").textContent'), lang === 'FR' ? 'En cours' : 'In progress');
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    await writeFile(resolve(output, `${width}-${lang}-active.png`), Buffer.from(shot.data, 'base64'));
  }
  assert.equal(errors.length, 0, errors.join('\n'));
  assert.ok(dialogs >= 20);
  console.log('Inspection browser integration: 4 passed (FR/EN × desktop/mobile; scanner, blocked reasons, cancel/confirm start, pause/resume, front/back acquisition, custody, layout).');
} finally {
  socket?.close(); chrome.kill(); next.kill(); backend.close();
}
