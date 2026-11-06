// Isolated real V1 + real Stripe-hosted Checkout. No financial API mutations here.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile,writeFile,appendFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const phase=process.env.SELBY_QA_PHASE==='2'?'phase2':'phase1';
const out=process.env.SELBY_QA_PHASE==='BDISPUTE'?resolve(root,'validation_artifacts/stripe_sandbox_b_dispute'):process.env.SELBY_QA_PHASE==='B2R'?resolve(root,'validation_artifacts/stripe_sandbox_b2/refunds'):process.env.SELBY_QA_PHASE==='B2'?resolve(root,'validation_artifacts/stripe_sandbox_b2/preparation'):resolve(root,'validation_artifacts/stripe_sandbox_b1r',phase);
const frontend=resolve(root,'../frontend');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const read=async name=>JSON.parse(await readFile(resolve(out,name),'utf8'));
if(process.argv[2]!=='start'){
 const input=await read('browser-command.json');
 const result=await fetch('http://127.0.0.1:19314',{method:'POST',body:JSON.stringify(input)});
 console.log(await result.text());process.exit(result.ok?0:1);
}
let next,chrome,socket,send,nextLog='',failNextCommercial=false;
function startNext(){
 const child=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port','13010'],{cwd:frontend,windowsHide:true,env:{...process.env,SPECTRA_BACKEND_URL:'http://127.0.0.1:18010',SELBY_FRONTEND_TEST_DIST_DIR:'.next-stripe-b1r-qa'},stdio:['ignore','pipe','pipe']});
 child.stdout.on('data',b=>{nextLog+=b;});child.stderr.on('data',b=>{nextLog+=b;});return child;
}
try{
 next=startNext();
 for(let i=0;i<180;i++){
  if(next.exitCode!==null){if(nextLog.includes('This command stopped')){nextLog='';next=startNext();}else throw Error('Next startup failed');}
  try{const r=await fetch('http://127.0.0.1:13010/account',{signal:AbortSignal.timeout(3000)});if(r.ok)break;}catch{}
  await delay(500);if(i===179)throw Error('Next timeout');
 }
 chrome=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=19313',`--user-data-dir=${resolve(out,'private-chrome')}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let targets;
 for(let i=0;i<100;i++){try{targets=await(await fetch('http://127.0.0.1:19313/json/list')).json();if(targets.some(t=>t.type==='page'))break;}catch{}await delay(100);}
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await once(socket,'open');let seq=0;const jobs=new Map();
 send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{jobs.delete(id);reject(Error('CDP timeout '+method));},25000);jobs.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
 socket.addEventListener('message',async event=>{const m=JSON.parse(event.data);if(m.id){const job=jobs.get(m.id);if(!job)return;jobs.delete(m.id);clearTimeout(job.timer);m.error?job.reject(Error(m.error.message)):job.resolve(m.result);return;}
  if(m.method==='Fetch.requestPaused'){
   if(failNextCommercial&&m.params.request.method==='GET'&&m.params.request.url.startsWith('http://127.0.0.1:13010/api/submissions/')&&m.params.request.url.endsWith('/commercial-state')){
    failNextCommercial=false;await writeFile(resolve(out,'diagnostic-injected-read-failure.json'),JSON.stringify({at:new Date().toISOString(),synthetic:true,method:'GET',path:new URL(m.params.request.url).pathname,error:'Failed',financial_mutation:false},null,2));
    await send('Fetch.failRequest',{requestId:m.params.requestId,errorReason:'Failed'});await send('Fetch.disable');
   }else await send('Fetch.continueRequest',{requestId:m.params.requestId});
  }
  if(m.method==='Network.loadingFailed')await appendFile(resolve(out,'browser-loading-failures.jsonl'),JSON.stringify({at:new Date().toISOString(),requestId:m.params.requestId,error:m.params.errorText,canceled:m.params.canceled??false})+'\n');
  if(m.method==='Network.responseReceived'&&m.params.response.url.startsWith('http://127.0.0.1:13010/api/submissions/')&&/commercial-state|stripe-checkout/.test(m.params.response.url)){
   const {requestId,response}=m.params;setTimeout(async()=>{try{const b=await send('Network.getResponseBody',{requestId});const data=JSON.parse(b.body);delete data.url;await appendFile(resolve(out,'v1-api.jsonl'),JSON.stringify({at:new Date().toISOString(),path:new URL(response.url).pathname,http:response.status,body:data})+'\n');}catch{}},100);
  }
 });
 await send('Page.enable');await send('Network.enable');await send('Runtime.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 const server=createServer(async(req,res)=>{try{let raw='';for await(const chunk of req)raw+=chunk;const command=JSON.parse(raw);let result;
  if(command.op==='case'){
   const manifest=await read('manifest.json');const c=manifest.cases[command.name];if(!c)throw Error('Unknown QA case');
   const access=(await read('private-access.json'))[command.name];
   await send('Network.setCookie',{name:'spectra_session',value:access.token,url:'http://127.0.0.1:13010',path:'/',httpOnly:true,sameSite:'Lax'});
   result=await send('Page.navigate',{url:'http://127.0.0.1:13010/account/submissions/'+c.submission_id});
  }else if(command.op==='fail-next-commercial-read'){
   failNextCommercial=true;await send('Fetch.enable',{patterns:[{urlPattern:'http://127.0.0.1:13010/api/submissions/*/commercial-state',requestStage:'Request'}]});result={armed:true,scope:'one local GET commercial-state only'};
  }else if(command.op==='eval'){
   const r=await send('Runtime.evaluate',{expression:command.expression,returnByValue:true,awaitPromise:true,...(command.contextId?{contextId:command.contextId}:{})},command.sessionId);
   if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));result=r.result.value;
  }else if(command.op==='screenshot'){
   if(!/^[a-zA-Z0-9_-]+$/.test(command.name))throw Error('Invalid filename');
   const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(resolve(out,command.name+'.png'),Buffer.from(r.data,'base64'));result={saved:command.name+'.png'};
  }else if(command.op==='cdp'){result=await send(command.method,command.params??{},command.sessionId);}
  else throw Error('Unknown operation');
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result??null));
 }catch(error){res.statusCode=500;res.end(JSON.stringify({error:error.message}));}});
 await new Promise(r=>server.listen(19314,'127.0.0.1',r));console.log('QA_BROWSER_READY ports=13010,19313,19314');
 await new Promise(r=>{process.on('SIGINT',r);process.on('SIGTERM',r);});server.close();
}finally{await writeFile(resolve(out,'next.log'),nextLog);socket?.close();chrome?.kill();next?.kill();}
