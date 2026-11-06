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
  async function change(id,value){await evaluate(`$('${id}').value=${JSON.stringify(value)};$('${id}').dispatchEvent(new Event('change'))`);}
  async function click(id){await evaluate(`$('${id}').click()`);}

  async function client(point){return evaluate(`G.imageToClient(${JSON.stringify(point)},canvas.getBoundingClientRect(),camera)`);}
  async function mouse(type,p,extra={}){await send('Input.dispatchMouseEvent',{type,x:p[0],y:p[1],...extra});}
  async function dragHandle(from,to){
    await evaluate("canvas.scrollIntoView({block:'center'})");const a=await client(from),b=await client(to);
    await mouse('mousePressed',a,{button:'left',buttons:1,clickCount:1});assert.equal(await evaluate('drag?.kind'), 'edit', JSON.stringify({a,b,error:await evaluate("$('error').textContent")}));
    await mouse('mouseMoved',b,{button:'left',buttons:1});
    await mouse('mouseReleased',b,{button:'left',buttons:0,clickCount:1});
  }
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1200,height:1000,deviceScaleFactor:1.25,mobile:false});
  await send('Page.navigate',{url:pathToFileURL(page).href});
  for(let i=0;i<100;i++){if(await evaluate("typeof image!=='undefined'&&image.naturalWidth>0"))break;await pause(50);}
  assert.equal(await evaluate('reference.sides.every(s=>!s.confirmed&&s.line_abc===null)'),true);
  assert.equal(await evaluate("$('candidates').checked"),false);
  assert.equal(await evaluate('detailViews.length'),8);

  // Candidate identification is independent of annotation state. Capture actual
  // canvas drawing calls as well as the accessible DOM key/metadata.
  const untouched=await evaluate('JSON.stringify(reference.sides)');
  assert.equal(await evaluate('candidatePaintPlan(0).length'),0);
  assert.equal(await evaluate("$('showFrozen').checked&&$('showExperimental').checked"),true);
  assert.equal(await evaluate("$('candidate').options.length"),7);
  async function audit(){return evaluate(`(()=>{
    const labels=[],strokes=[],text=ctx.fillText,stroke=ctx.stroke;
    ctx.fillText=function(value,...args){labels.push(value);return text.call(this,value,...args)};
    ctx.stroke=function(){strokes.push({color:this.strokeStyle,alpha:this.globalAlpha,width:this.lineWidth,dash:this.getLineDash()});return stroke.call(this)};
    try{drawScene(ctx,camera,true,0)}finally{ctx.fillText=text;ctx.stroke=stroke}
    return {labels,strokes};
  })()`);}
  await click('candidates');
  assert.equal(await evaluate('candidatePaintPlan(0).length'),6);
  assert.equal(await evaluate("new Set(candidates.filter(c=>c.reportIndex===0&&c.side===0).map(c=>c.color)).size"),3);
  let painted=await audit();
  for(const id of ['F1:L0','F1:L1','F1:L2','E2:L0','E2:L1','E2:L2'])assert.ok(painted.labels.some(label=>label.includes(id)),id);
  await change('candidate','1-0-L1');
  assert.equal(await evaluate('selectedCandidates[0]'),'1-0-L1');
  assert.equal(await evaluate('candidatePaintPlan(0).at(-1).key'),'1-0-L1');
  assert.equal(await evaluate('candidatePaintPlan(0).filter(c=>!c.highlighted).every(c=>c.alpha===.18)'),true);
  painted=await audit();
  assert.ok(painted.labels.includes('> E2:L1'));
  assert.ok(painted.strokes.some(s=>s.width===2.5&&s.alpha===1&&s.dash.join(',')==='2,4'));
  const metadata=await evaluate("$('candidateInfo').textContent");
  for(const value of ['0.3.0-exp1','L1','62.5%','1.25','side_coverage','synthetic_ambiguity','provisional selection: no'])assert.ok(metadata.includes(value),value);
  // Selection survives zoom/render and side changes without placing a reference.
  await change('zoom','2');await change('side','right');await change('side','top');
  assert.equal(await evaluate("$('candidate').value"),'1-0-L1');
  await click('showExperimental');painted=await audit();
  assert.equal(await evaluate("candidatePaintPlan(0).every(c=>c.family==='frozen')"),true);
  assert.ok(!painted.labels.some(label=>label.includes('E2:L')));
  assert.ok((await evaluate("$('candidateInfo').textContent")).includes('hidden'));
  assert.equal(await evaluate('candidatePaintPlan(0).every(c=>c.alpha===1)'),true);
  await click('showFrozen');assert.equal(await evaluate('candidatePaintPlan(0).length'),0);
  await click('showSelected');
  assert.equal(await evaluate("$('showExperimental').checked&&!$('showFrozen').checked"),true);
  assert.equal(await evaluate("candidatePaintPlan(0).every(c=>c.family==='experimental')"),true);
  // The labeled legend is keyboard-accessible and uses the same selection key.
  await evaluate("document.querySelector('[data-candidate-key=\"1-0-L0\"]').click()");
  assert.equal(await evaluate("$('candidate').value"),'1-0-L0');
  assert.ok((await evaluate("$('candidateInfo').textContent")).includes('provisional selection: yes'));
  assert.equal(await evaluate('JSON.stringify(reference.sides)'),untouched);
  await click('showFrozen');await click('candidates');
  assert.equal(await evaluate('candidatePaintPlan(0).length'),0);
  assert.equal(await evaluate('reference.candidate_overlays_seen'),true);

  await click('download');assert.equal(await evaluate('lastExport'),null);
  await evaluate("$('reviewer').value='SYNTHETIC BROWSER ONLY';$('reviewer').dispatchEvent(new Event('input'));$('independent').checked=true;$('independent').dispatchEvent(new Event('change'))");
  await evaluate("$('candidate').selectedIndex=1;$('candidate').dispatchEvent(new Event('change'))");await click('seed');
  assert.equal(await evaluate('reference.sides[0].confirmed'),false);
  assert.equal(await evaluate('reference.candidate_overlays_seen'),true);
  assert.equal(await evaluate('reference.sides[0].status'),'unreviewed');
  await change('status','certain');await click('confirm');
  assert.equal(await evaluate('reference.sides[0].confirmed'),true);
  for(const zoom of [.25,1,4,16]){
    await evaluate(`camera.zoom=${zoom};camera.center=[...current().endpoints[0]];render()`);
    const p=await evaluate('current().endpoints');
    await dragHandle(p[0],[p[0][0]+.125,p[0][1]+2.5]);
    const q=await evaluate('current().endpoints');
    close(q[0][0],p[0][0]+.125);close(q[0][1],p[0][1]+2.5);
    assert.deepEqual(q[1],p[1]);assert.equal(await evaluate('current().confirmed'),false);
    await click('undo');assert.deepEqual(await evaluate('current().endpoints'),p);
  }
  await evaluate("camera.zoom=8;focus();$('step').value='0.05'");
  const p=await evaluate('current().endpoints');await click('inward');const q=await evaluate('current().endpoints');close(Math.hypot(q[0][0]-p[0][0],q[0][1]-p[0][1]),.05);
  await change('status','uncertain');await change('uncertainty','1.5');await change('notes','SYNTHETIC blur interval');await click('confirm');
  assert.equal(await evaluate('current().confirmed'),true);
  await change('notes','SYNTHETIC revised interval');assert.equal(await evaluate('current().confirmed'),false);await click('confirm');
  // A numerical draft must invalidate review and survive side switching.
  await evaluate("$('x0').value=String(Number($('x0').value)+.01);$('x0').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate('current().confirmed'),false);
  await change('side','right');await click('download');assert.equal(await evaluate('lastExport'),null);
  await change('side','top');await click('apply');await click('confirm');
  for(const side of ['right','bottom']){
    await change('side',side);await evaluate("$('candidate').selectedIndex=1;$('candidate').dispatchEvent(new Event('change'))");await click('seed');await change('status','certain');await click('confirm');
    assert.equal(await evaluate('current().confirmed'),true);
  }
  // Indeterminate geometry is deliberately absent and still requires confirmation.
  await change('side','left');await change('status','indeterminate');await change('notes','SYNTHETIC material edge cannot be located');await click('confirm');
  assert.equal(await evaluate('current().line_abc'),null);assert.equal(await evaluate('current().confirmed'),true);
  await evaluate("URL.createObjectURL=()=> 'blob:test';URL.revokeObjectURL=()=>{};HTMLAnchorElement.prototype.click=()=>{}");
  await click('download');const result=await evaluate('lastExport');assert.ok(result);
  assert.equal(result.kind,'physical_boundary_reference');assert.equal(result.sides[0].status,'uncertain');assert.equal(result.sides[3].status,'indeterminate');
  assert.ok(result.sides.every(s=>s.confirmed));assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify(result));await send('Browser.close');
}finally{socket?.close();if(chrome.exitCode===null)chrome.kill();}
