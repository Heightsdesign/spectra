// Real Pointer Events on synthetic offline imagery; never creates a real-card reference.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const page=resolve(process.argv[2]), roundtrip=process.argv[3]==='roundtrip';
// Keep Chrome's profile path short: reopened reference pages can be deeply nested
// below immutable version directories and exceed Windows profile path limits.
const profile=resolve(dirname(fileURLToPath(import.meta.url)),'../local_data/physical-reference-browser-profiles',randomUUID());
await mkdir(profile,{recursive:true});
const chrome=spawn(process.env.CHROME_PATH??'C:/Program Files/Google/Chrome/Application/chrome.exe',[
  '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank',
],{windowsHide:true,stdio:'ignore'});
chrome.on('error',error=>console.error(error.message));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const close=(a,b,tolerance=.002)=>assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);
let socket;
try{
  let port,targets;
  for(let i=0;i<100;i++){
    try{port=Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{await pause(100);}
  }
  assert.ok(port,'Chrome DevTools ready');
  for(let i=0;i<100;i++){
    try{targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(targets.some(t=>t.type==='page'))break;}catch{/* Listener startup. */}
    await pause(100);
  }
  assert.ok(targets?.some(t=>t.type==='page'));
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await once(socket,'open');
  let sequence=0;
  const pending=new Map(),errors=[];
  function send(method,params={}){
    return new Promise((resolve,reject)=>{
      const id=++sequence,timeout=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},10000);
      pending.set(id,{resolve,reject,timeout});socket.send(JSON.stringify({id,method,params}));
    });
  }
  socket.addEventListener('message',event=>{
    const m=JSON.parse(event.data);
    if(m.id){const job=pending.get(m.id);if(!job)return;pending.delete(m.id);clearTimeout(job.timeout);if(m.error)job.reject(Error(m.error.message));else job.resolve(m.result);}
    else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);
  });
  async function evaluate(expression){
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    assert.equal(r.exceptionDetails,undefined,JSON.stringify(r.exceptionDetails));return r.result.value;
  }

  const $="document.getElementById";
  async function change(id,value){await evaluate(`document.getElementById('${id}').value=${JSON.stringify(value)};document.getElementById('${id}').dispatchEvent(new Event('change'))`);}
  async function click(id){await evaluate(`document.getElementById('${id}').click()`);}
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1200,height:1100,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:pathToFileURL(page).href});
  for(let i=0;i<100;i++){if(await evaluate("!!document.getElementById('view') && document.getElementById('zoom').value!=='1'"))break;await pause(50);}
  const data=await evaluate("JSON.parse(document.getElementById('blind-data').textContent)");
  assert.ok(data.reference.sides.every(s=>s.endpoints===null&&!s.confirmed));
  assert.equal(await evaluate("document.querySelectorAll('input[type=file]').length"),0);
  await evaluate("globalThis.exportBlob=null;URL.createObjectURL=b=>{globalThis.exportBlob=b;return 'blob:test'};URL.revokeObjectURL=()=>{};HTMLAnchorElement.prototype.click=()=>{}");
  await click('export');assert.equal(await evaluate('globalThis.exportBlob'),null);
  await change('reviewer','SYNTHETIC BROWSER REVIEW');await change('exposure','none');await click('declaration');
  const pairs=[[[80,80],[240,80]],[[260,100],[260,300]],[[240,320],[80,320]],[[60,300],[60,100]]];
  for(let i=0;i<4;i++){
    await change('side',['top','right','bottom','left'][i]);
    await click('place');await evaluate("document.getElementById('view').scrollIntoView({block:'center'})");
    for(const p of pairs[i]){
      const xy=await evaluate(`(()=>{const c=document.getElementById('view'),r=c.getBoundingClientRect(),z=Number(document.getElementById('zoom').value);return [r.left+((${p[0]}-160)*z+550)*r.width/1100,r.top+((${p[1]}-200)*z+325)*r.height/650]})()`);
      await send('Input.dispatchMouseEvent',{type:'mousePressed',x:xy[0],y:xy[1],button:'left',buttons:1,clickCount:1});
      await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:xy[0],y:xy[1],button:'left',buttons:0,clickCount:1});
    }
    assert.ok(await evaluate("document.getElementById('x1').value!==''"));
    await change('status',i===0?'uncertain':'certain');
    if(i===0){await change('notes','SYNTHETIC blurred edge');await change('uncertainty','1.5');}
    await click('confirm');
  }
  assert.ok((await evaluate("document.getElementById('confirmations').textContent")).split(' | ').every(s=>!s.includes('unconfirmed')));
  // Actual pointer events at CSS-scaled canvas sizes and several zoom levels.
  await change('side','top');
  let center=[160,200], zoom=1;
  async function endpoints(){return evaluate("['x1','y1','x2','y2'].map(id=>Number(document.getElementById(id).value))");}
  const drawableBounds="(()=>{const c=document.getElementById('view'),r=c.getBoundingClientRect(),s=getComputedStyle(c),l=parseFloat(s.borderLeftWidth),t=parseFloat(s.borderTopWidth);return {left:r.left+l,top:r.top+t,width:r.width-l-parseFloat(s.borderRightWidth),height:r.height-t-parseFloat(s.borderBottomWidth)}})()";
  async function client(p){return evaluate(`SpectraReferenceGeometry.imageToClient(${JSON.stringify(p)},${drawableBounds},{center:${JSON.stringify(center)},zoom:${zoom},width:1100,height:650})`);}
  async function mouse(type,p,extra={}){await send('Input.dispatchMouseEvent',{type,x:p[0],y:p[1],...extra});}
  async function dragImage(from,to,kind){
    await evaluate("document.getElementById('view').scrollIntoView({block:'center'})");
    const a=await client(from),b=await client(to);
    await mouse('mouseMoved',a);
    assert.equal(await evaluate("document.getElementById('view').dataset.interaction"),kind==='dragging-line'?'line':'endpoint');
    await mouse('mousePressed',a,{button:'left',buttons:1,clickCount:1});
    assert.equal(await evaluate("document.getElementById('view').dataset.interaction"),kind);
    await mouse('mouseMoved',b,{button:'left',buttons:1});
    await mouse('mouseReleased',b,{button:'left',buttons:0,clickCount:1});
  }
  await evaluate("document.getElementById('view').style.width='550px'");
  for(const z of [.75,1.5,4]){
    await click('fit');center=[160,200];zoom=z;await change('zoom',String(z));
    // Pan using Shift even over a line. Move center to the top edge at 4x.
    if(z===4){
      await evaluate("document.getElementById('view').scrollIntoView({block:'center'})");
      const bounds=await evaluate(drawableBounds);
      const a=[bounds.left+bounds.width/2,bounds.top+50*bounds.height/650],b=[a[0],a[1]+480*bounds.height/650];
      const before=await endpoints();
      await mouse('mousePressed',a,{button:'left',buttons:1,clickCount:1,modifiers:8});
      assert.equal(await evaluate("document.getElementById('view').dataset.interaction"),'panning');
      await mouse('mouseMoved',b,{button:'left',buttons:1,modifiers:8});
      await mouse('mouseReleased',b,{button:'left',buttons:0,clickCount:1,modifiers:8});
      center=[160,80];assert.deepEqual(await endpoints(),before);
    }
    const before=await endpoints(), midpoint=[(before[0]+before[2])/2,(before[1]+before[3])/2];
    await click('confirm');
    await dragImage(midpoint,[midpoint[0]+.625,midpoint[1]+1.25],'dragging-line');
    let after=await endpoints();
    for(let k=0;k<4;k++)close(after[k],before[k]+(k%2?1.25:.625),.015);
    close(after[2]-after[0],before[2]-before[0],1e-8);close(after[3]-after[1],before[3]-before[1],1e-8);
    assert.ok((await evaluate("document.getElementById('confirmations').textContent")).startsWith('top: unconfirmed'));
    assert.equal(await evaluate("document.getElementById('notes').value"),'SYNTHETIC blurred edge');
    assert.equal(await evaluate("document.getElementById('uncertainty').value"),'1.5');
    // Each handle moves independently; the other must remain bit-for-bit fixed.
    for(const endpoint of [0,1]){
      const p=await endpoints(),k=endpoint*2;
      await dragImage(p.slice(k,k+2),[p[k]+.375,p[k+1]-.5],'dragging-endpoint');
      after=await endpoints();close(after[k],p[k]+.375,.015);close(after[k+1],p[k+1]-.5,.015);
      assert.deepEqual(after.slice(2-k,4-k),p.slice(2-k,4-k));
    }
    // No accidental camera movement: the moved handle remains hit-testable.
    const p=await endpoints();await mouse('mouseMoved',await client(p.slice(0,2)));
    assert.equal(await evaluate("document.getElementById('view').dataset.interaction"),'endpoint');
  }
  await click('confirm');
  // Empty-space panning changes the view, not geometry or confirmation.
  const panningBefore=await endpoints();
  const empty=await client([160,100]);
  await mouse('mousePressed',empty,{button:'left',buttons:1,clickCount:1});
  assert.equal(await evaluate("document.getElementById('view').dataset.interaction"),'panning');
  await mouse('mouseMoved',[empty[0]+20,empty[1]+10],{button:'left',buttons:1});
  await mouse('mouseReleased',[empty[0]+20,empty[1]+10],{button:'left',buttons:0,clickCount:1});
  assert.deepEqual(await endpoints(),panningBefore);
  assert.ok((await evaluate("document.getElementById('confirmations').textContent")).startsWith('top: confirmed'));
  await click('fit');await change('side','left');
  // A fine adjustment clears confirmation and blocks export until reconfirmed.
  await change('x1','60.05');await click('apply');await click('export');assert.equal(await evaluate('globalThis.exportBlob'),null);
  await click('confirm');await click('export');
  for(let i=0;i<100;i++){if(await evaluate('globalThis.exportBlob!==null'))break;await pause(25);}
  const bundle=await evaluate('globalThis.exportBlob.text().then(JSON.parse)');
  const ref=JSON.parse(bundle.reference_json);
  assert.ok(ref.sides.every(s=>s.confirmed&&s.origin==='manual'));
  assert.equal(ref.sides[0].status,'uncertain');assert.equal(ref.sides[0].uncertainty_pixels,1.5);
  assert.equal(ref.candidate_overlays_seen,false);assert.equal(bundle.prior_detector_exposure,'none');
  for(const side of ref.sides){
    assert.deepEqual(side.reviewed.endpoints,side.endpoints);
    const [a,b,c]=side.line_abc;
    for(const p of side.endpoints)close(a*p[0]+b*p[1]+c,0,1e-8);
  }
  const html=await readFile(page,'utf8');
  for(const forbidden of ['candidate_layers','detector_seed','0.2.0','0.3.0','L0'])assert.ok(!html.includes(forbidden),forbidden);
  assert.equal(await evaluate("document.getElementById('place').disabled"),true);
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('Blind browser interactions passed: whole-line and both endpoint dragging at 0.75x/1.5x/4x, CSS scaling, pan separation, confirmation invalidation, manual isolation, export geometry and lock.');
  await send('Browser.close');
}finally{socket?.close();if(chrome.exitCode===null)chrome.kill();}
