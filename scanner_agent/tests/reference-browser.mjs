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
const profile=resolve(dirname(fileURLToPath(import.meta.url)),'../local_data/reference-browser-profiles',randomUUID());
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
  async function centerCanvas(){await evaluate("canvas.scrollIntoView({block:'center'})");}
  async function mouse(type,p,extra={}){await send('Input.dispatchMouseEvent',{type,x:p[0],y:p[1],...extra});}
  async function client(point){return evaluate(`G.imageToClient(${JSON.stringify(point)},bounds(),camera)`);}
  async function drag(from,to,{fine=false,pan=false}={}){
    await centerCanvas();
    const a=await client(from),b=await client(to),before=await evaluate('JSON.stringify(state.sides)');
    await mouse('mouseMoved',a);
    await mouse('mousePressed',a,{button:'left',buttons:1,clickCount:1,modifiers:fine?8:0});
    await mouse('mouseMoved',b,{button:'left',buttons:1,modifiers:fine?8:0});
    assert.equal(await evaluate('JSON.stringify(state.sides)'),before,'Preview does not mutate stored annotation');
    if(!pan)assert.equal(await evaluate('preview?.kind'),'drag');
    await mouse('mouseReleased',b,{button:'left',buttons:0,clickCount:1,modifiers:fine?8:0});
  }
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1024,height:900,deviceScaleFactor:1.25,mobile:false});
  await send('Page.navigate',{url:pathToFileURL(page).href});
  for(let i=0;i<100;i++){if(await evaluate("document.getElementById('candidate')?.options.length>1"))break;await pause(50);}
  if(!roundtrip){
    assert.equal(await evaluate('reference.sides.every(s=>s.line_abc===null)'),true);
    assert.equal(await evaluate("$('showCandidates').checked"),false,'Candidates hidden initially');
    await change('candidate','top-0');
    assert.equal(await evaluate('state.sides[0].status'),'unannotated');
    await change('status','annotated');
    assert.equal(await evaluate('state.sides[0].status'),'unannotated','Status selector cannot bypass confirm button');
    await click('confirm');assert.equal(await evaluate('state.sides[0].status'),'annotated');
    const initialLine=await evaluate('state.sides[0].line_abc');
    for(const zoom of [.25,1,4,16]){
      await click('reset');
      await evaluate(`camera.zoom=${zoom};focusAt(.5)`);
      const points=await evaluate('state.handles[0]'),middle=points[0].map((v,i)=>(v+points[1][i])/2);
      await drag(middle,[middle[0],middle[1]+3.125]);
      const moved=await evaluate('state.handles[0]');
      close(moved[0][1],points[0][1]+3.125);close(moved[1][1],points[1][1]+3.125);
      assert.equal(await evaluate('state.sides[0].status'),'unannotated');
      assert.equal(await evaluate('state.sides[0].definition'),'manual');
      const manual=await evaluate('state.sides[0].line_abc');
      await click('undo');assert.deepEqual(await evaluate('state.sides[0].line_abc'),initialLine);
      await click('redo');assert.deepEqual(await evaluate('state.sides[0].line_abc'),manual);
    }
    await evaluate('camera.zoom=4;focusAt(0)');
    const beforeHandle=await evaluate('state.handles[0]');
    await drag(beforeHandle[0],[beforeHandle[0][0]+1.25,beforeHandle[0][1]+2.5]);
    const afterHandle=await evaluate('state.handles[0]');
    close(afterHandle[0][0],beforeHandle[0][0]+1.25);close(afterHandle[0][1],beforeHandle[0][1]+2.5);
    assert.deepEqual(afterHandle[1],beforeHandle[1],'Independent endpoint preserves opposite endpoint');
    close(Number(await evaluate("$('d0').value")),await evaluate('G.atLine(corners,0,state.sides[0].line_abc,state.sides[0].valid_span_fraction[0]).distance'),1e-10);
    // Endpoint arrow nudge remains in original pixels, independent of zoom.
    await evaluate('canvas.focus()');
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown',modifiers:8});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowDown',code:'ArrowDown'});
    close((await evaluate('state.handles[0]'))[0][1],afterHandle[0][1]+.1);
    const edited=await evaluate('state.sides[0].line_abc');
    await change('side','right');await change('side','top');
    assert.deepEqual(await evaluate('state.sides[0].line_abc'),edited,'Side switching preserves edits');
    await click('reset');assert.deepEqual(await evaluate('state.sides[0].line_abc'),initialLine);
    // Numerical span edits do not move a candidate line; numeric offsets do.
    await evaluate("$('span0').value=.25;$('span0').dispatchEvent(new Event('input'))");await click('apply');
    assert.deepEqual(await evaluate('state.sides[0].line_abc'),initialLine);
    await evaluate("$('d0').value=18.125;$('d1').value=24.375;$('d0').dispatchEvent(new Event('input'))");await click('apply');
    close(Number(await evaluate("$('d0').value")),18.125,1e-10);close(Number(await evaluate("$('d1').value")),24.375,1e-10);
    await click('confirm');
    await evaluate("$('d0').value='';$('d0').dispatchEvent(new Event('input'))");
    await change('side','right');await change('side','top');
    assert.equal(await evaluate("$('d0').value"),'','Invalid draft is retained across side switch');
    await click('discardDraft');
    // Pointer-centered zoom and panning preserve geometry.
    await evaluate('camera.zoom=1;focusAt(.5)');await centerCanvas();
    const anchor=await evaluate('camera.center.map((v,i)=>v+[30,-20][i])'),at=await client(anchor);
    // WheelEvent coordinates may be quantized by Chrome. Test anchoring at the
    // delivered event position, not an unrepresentable fractional CDP request.
    await evaluate("canvas.addEventListener('wheel',e=>{window.wheelClient=[e.clientX,e.clientY];window.wheelAnchor=G.clientToImage(window.wheelClient,bounds(),camera)},{capture:true,once:true})");
    await mouse('mouseWheel',at,{deltaX:0,deltaY:-100});await pause(80);
    const under=await evaluate('G.clientToImage(window.wheelClient,bounds(),camera)'),wheelAnchor=await evaluate('window.wheelAnchor');
    under.forEach((v,i)=>close(v,wheelAnchor[i],1e-10));
    const geometryBeforePan=await evaluate('JSON.stringify(state.sides)');
    const cameraBeforePan=await evaluate('camera.center');
    await evaluate("$('panMode').checked=true");
    await drag(anchor,[anchor[0]+10,anchor[1]+5],{pan:true});
    assert.equal(await evaluate('JSON.stringify(state.sides)'),geometryBeforePan);
    const cameraAfterPan=await evaluate('camera.center');
    close(cameraAfterPan[0],cameraBeforePan[0]-10);close(cameraAfterPan[1],cameraBeforePan[1]-5);
    await evaluate("$('panMode').checked=false");
    for(const name of ['right','bottom']){await change('side',name);await evaluate("$('candidate').selectedIndex=1;$('candidate').dispatchEvent(new Event('change'))");assert.equal(await evaluate('state.sides[current].status'),'unannotated');await click('confirm');}
    // Blind manual placement does not require selecting or showing a candidate.
    await change('side','left');await evaluate('camera.zoom=1;focusAt(.5)');await centerCanvas();
    await click('place');
    for(const point of [[110,500],[110,200]]){const p=await client(point);await mouse('mousePressed',p,{button:'left',buttons:1,clickCount:1});await mouse('mouseReleased',p,{button:'left',buttons:0,clickCount:1});}
    assert.equal(await evaluate('state.sides[3].definition'),'manual');
    assert.equal(await evaluate('state.sides[3].status'),'unannotated');
    await change('status','ambiguous');assert.equal(await evaluate('state.sides[3].status'),'ambiguous');
    await click('confirm');
  }
  // Capture JSON in memory: real datasets are never annotated by this driver.
  const exportedBefore=await evaluate('JSON.stringify(state.sides)');
  await evaluate("URL.createObjectURL=b=>{window.captured=b.text();return 'blob:test'};URL.revokeObjectURL=()=>{};HTMLAnchorElement.prototype.click=()=>{};$('annotationId').value='SYNTHETIC-BROWSER-TEST';$('layout').value='supported';$('download').click()");
  const annotation=JSON.parse(await evaluate('window.captured'));
  assert.equal(JSON.stringify(annotation.sides),exportedBefore,'Export preserves all double-precision line coefficients');
  assert.equal(annotation.coordinate_system,'original_image_pixels_xy_right_down_v1');
  assert.ok(annotation.sides.every(s=>s.status==='annotated'),'All final sides explicitly confirmed');
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('SYNTHETIC_EXPORT:'+JSON.stringify(annotation));
  console.log('Offline annotation UI: passed (pointer transforms, 4 zooms, translation, endpoint edit, confirmation, history, side retention, reset, numeric sync, zoom/pan, blind placement, exact export'+(roundtrip?', import roundtrip':'')+').');
  await send('Browser.close');
}finally{socket?.close();if(chrome.exitCode===null)chrome.kill();}
