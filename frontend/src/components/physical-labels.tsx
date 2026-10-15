"use client";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { labelCopy, labelError, labelPdf, labelReferences, MAX_LABEL_BATCH, type LabelProfile } from '@/lib/physical-labels';

type LabelControls = { selected:Set<string>; toggle:(reference:string)=>void; prepare:(references:string[])=>void; busy:boolean; language:'FR'|'EN' };
const LabelContext=createContext<LabelControls|null>(null);
export function CardLabelActions({ reference }: { reference:string }) {
  const controls=useContext(LabelContext);
  if(!controls) return null;
  const t=labelCopy[controls.language];
  return <div className="card-label-actions"><label><input type="checkbox" checked={controls.selected.has(reference)} disabled={controls.busy} onChange={()=>controls.toggle(reference)} />{t.select} <span className="sr-only">{reference}</span></label><div className="intake-toolbar"><button type="button" className="button button-outline" disabled={controls.busy} onClick={()=>controls.prepare([reference])}>{t.print}</button><button type="button" className="button button-outline" disabled={controls.busy} onClick={()=>controls.prepare([reference])}>{t.reprint}</button></div></div>;
}
export function PhysicalLabelsPanel({ submissionId, references, language, children }: { submissionId:string; references:string[]; language:'FR'|'EN'; children:ReactNode }) {
  const [selected,setSelected]=useState<Set<string>>(new Set());
  const [profile,setProfile]=useState<LabelProfile>('50x30');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<unknown>(null);
  const [preview,setPreview]=useState<{url:string;filename:string;count:number}|null>(null);
  const objectUrl=useRef<string|null>(null);
  const mounted=useRef(true);
  const heading=useRef<HTMLHeadingElement>(null);
  const t=labelCopy[language];
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;if(objectUrl.current) URL.revokeObjectURL(objectUrl.current);};},[]);
  useEffect(()=>{if(preview) heading.current?.focus();},[preview]);
  function close() {
    if(objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current=null;setPreview(null);
  }
  async function prepare(values:string[], calibration=false) {
    setError(null);setBusy(true);
    try {
      const refs=calibration?[]:labelReferences(values);
      close();
      const blob=await labelPdf(calibration?`/calibration/pdf?profile=${profile}`:`/submissions/${encodeURIComponent(submissionId)}/pdf`,calibration?undefined:{references:refs,profile});
      if(!mounted.current) return;
      const url=URL.createObjectURL(blob);
      objectUrl.current=url;
      setPreview({url,filename:calibration?`spectra-calibration-${profile}.pdf`:`spectra-labels-${profile}.pdf`,count:calibration?1:refs.length});
    } catch(error) {if(mounted.current) setError(error);}
    finally {if(mounted.current) setBusy(false);}
  }
  const controls:LabelControls={selected,busy,language,toggle:reference=>setSelected(previous=>{const next=new Set(previous);if(next.has(reference)) next.delete(reference);else next.add(reference);return next;}),prepare:values=>{void prepare(values);}};
  return <LabelContext.Provider value={controls}><section className="physical-label-panel" aria-labelledby="physical-label-title"><h3 id="physical-label-title">{t.title}</h3><div className="label-settings"><label>{t.profile}<select value={profile} disabled={busy} onChange={e=>setProfile(e.target.value as LabelProfile)}><option value="50x30">50 × 30 mm</option><option value="70x40">70 × 40 mm</option></select></label><p>{t.selected}: <strong>{selected.size}</strong> / {MAX_LABEL_BATCH}</p></div><div className="intake-toolbar"><button type="button" className="button button-outline" disabled={busy} onClick={()=>setSelected(new Set(references))}>{t.all}</button><button type="button" className="button button-outline" disabled={busy} onClick={()=>setSelected(new Set())}>{t.clear}</button><button type="button" className="button button-dark" disabled={busy||!selected.size||selected.size>MAX_LABEL_BATCH} onClick={()=>void prepare([...selected])}>{t.batch}</button><button type="button" className="button button-outline" disabled={busy||!selected.size||selected.size>MAX_LABEL_BATCH} onClick={()=>void prepare([...selected])}>{t.reprintBatch}</button><button type="button" className="button button-outline" disabled={busy} onClick={()=>void prepare([],true)}>{t.calibration}</button></div><p className="intake-help">{t.unverified}</p><div role="status" aria-live="polite">{busy&&<p>{t.loading}</p>}{!!error&&<p>{labelError(error,language)}</p>}{selected.size>MAX_LABEL_BATCH&&<p>{t.limit}</p>}</div>
    {preview&&<section className="label-preview" aria-labelledby="label-preview-title"><h3 id="label-preview-title" ref={heading} tabIndex={-1}>{t.preview} · {preview.count}</h3><p className="intake-warning">{t.notice}</p><div className="intake-toolbar"><a className="button button-dark" href={preview.url} target="_blank" rel="noopener noreferrer">{t.open}</a><a className="button button-outline" href={preview.url} download={preview.filename}>{t.download}</a><button type="button" className="button button-outline" onClick={close}>{t.close}</button></div><iframe src={preview.url} title={t.preview} /></section>}
    </section>{children}</LabelContext.Provider>;
}
