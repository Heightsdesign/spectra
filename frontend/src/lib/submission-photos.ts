import type { Submission } from './submissions.ts';
export const MAX_PHOTO_BYTES=8*1024*1024;
export function photoFileError(file:Pick<File,'size'|'type'>):string|null {
 if(file.size>MAX_PHOTO_BYTES)return 'photo_too_large';
 if(!file.size||!['image/jpeg','image/png'].includes(file.type))return 'invalid_photo';
 return null;
}
export function photoPath(submissionId:string,entryId:string,photoId?:string):string {
 return `/api/submissions/${encodeURIComponent(submissionId)}/entries/${encodeURIComponent(entryId)}/photos${photoId?`/${encodeURIComponent(photoId)}`:''}`;
}
export async function uploadPhoto<T=Submission>(path:string,payload:object,onProgress:(value:number)=>void,signal?:AbortSignal):Promise<T> {
 const csrf=await fetch('/api/auth/csrf',{cache:'no-store',signal});
 if(!csrf.ok)throw Error(csrf.status===401?'authentication_required':'photo_unavailable');
 const token=(await csrf.json()).csrf_token;
 return new Promise((resolve,reject)=>{
  const request=new XMLHttpRequest();
  const abort=()=>request.abort();
  signal?.addEventListener('abort',abort,{once:true});
  request.onloadend=()=>signal?.removeEventListener('abort',abort);
  request.onabort=()=>reject(Error('photo_cancelled'));
  request.open('POST',path);request.timeout=120000;
  request.setRequestHeader('Content-Type','application/json');request.setRequestHeader('X-Spectra-Client','1');request.setRequestHeader('X-CSRF-Token',token);
  request.upload.onprogress=event=>{if(event.lengthComputable)onProgress(Math.round(event.loaded/event.total*100));};
  request.onerror=request.ontimeout=()=>reject(Error('photo_unavailable'));
  request.onload=()=>{try{const result=JSON.parse(request.responseText);if(request.status>=200&&request.status<300)resolve(result);else reject(Error(typeof result.detail==='string'?result.detail:'invalid_photo'));}catch{reject(Error('photo_unavailable'));}};
  if(signal?.aborted){reject(Error('photo_cancelled'));signal.removeEventListener('abort',abort);return;}
  request.send(JSON.stringify(payload));
 });
}
export function photoData(file:File):Promise<string> {
 return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(Error('invalid_photo'));reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.readAsDataURL(file);});
}
