// Dedicated output directory; never deploys, starts the app or contacts PostgreSQL/Stripe.
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const output=resolve('.visual-review/order-workspace-v1');await mkdir(output,{recursive:true});
let combined='';
function build(){return new Promise((resolve,reject)=>{
  let log='';const child=spawn(process.execPath,['node_modules/next/dist/bin/next','build','--webpack'],{env:{...process.env,SELBY_FRONTEND_TEST_DIST_DIR:'.next-order-ux-build'},windowsHide:true,stdio:['ignore','pipe','pipe']});
  child.stdout.on('data',chunk=>{log+=chunk;process.stdout.write(chunk);});child.stderr.on('data',chunk=>{log+=chunk;process.stderr.write(chunk);});child.on('error',reject);child.on('exit',code=>{combined+=log;resolve({code,log});});
});}
let result=await build();
// The installed CLI explicitly asks for a second invocation after its security reminder.
// Do not change dependencies or disable checks; retain the warning in the validation log.
if(result.code!==0&&result.log.includes('This command stopped'))result=await build();
await writeFile(resolve(output,'build.log'),combined);
await writeFile(resolve(output,'build-result.json'),JSON.stringify({passed:result.code===0,postgresql_access:false,payments:0,security_reminder:combined.includes('security vulnerability')},null,2));
process.exitCode=result.code??1;
