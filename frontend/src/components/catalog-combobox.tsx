"use client";
import { useEffect, useId, useRef, useState } from 'react';
import type { Language } from '@/lib/i18n';

const messages = {
 FR: {loading:'Chargement…',empty:'Aucun résultat. Essayez une autre recherche ou la saisie manuelle.',error:'Impossible de charger le catalogue.',retry:'Réessayer',more:'Afficher plus de résultats',clear:'Effacer',end:'Tous les résultats sont affichés.'},
 EN: {loading:'Loading…',empty:'No results. Try another search or manual entry.',error:'Unable to load the catalog.',retry:'Retry',more:'Load more results',clear:'Clear',end:'All results are shown.'},
};

/** Input retains focus while aria-activedescendant exposes the highlighted option. */
export function CatalogCombobox<T extends {id:string}>({path,label,selected,lang,onSelect,onClear,render,requiredSelection=false}:{
 path:string;label:string;selected:string;lang:Language;onSelect:(row:T)=>void;onClear:()=>void;render:(row:T)=>string;requiredSelection?:boolean;
}) {
 const t=messages[lang]; const id=useId(); const input=useRef<HTMLInputElement>(null);
 const list=useRef<HTMLUListElement>(null);
 const [open,setOpen]=useState(false); const [query,setQuery]=useState('');
 const [rows,setRows]=useState<T[]>([]); const [offset,setOffset]=useState(0);
 const [more,setMore]=useState(false); const [active,setActive]=useState(-1);
 const [state,setState]=useState<'loading'|'ready'|'error'>('loading'); const [retry,setRetry]=useState(0);
 useEffect(()=>{input.current?.setCustomValidity(requiredSelection&&!selected
  ?lang==='FR'?'Sélectionnez une impression de la carte ou utilisez la saisie manuelle.':'Select a card printing or use manual entry.'
  :'');},[requiredSelection,selected,lang]);
 useEffect(()=>{
  if(!open)return;
  const controller=new AbortController();
  const timer=setTimeout(()=>{
   fetch(`/api/catalog/${path}&q=${encodeURIComponent(query)}&offset=${offset}&limit=20`,{signal:controller.signal,cache:'no-store'})
    .then(async response=>{if(!response.ok)throw Error();return await response.json() as T[];})
    .then(data=>{if(controller.signal.aborted)return;setRows(previous=>offset?[...previous,...data.filter(row=>!previous.some(p=>p.id===row.id))]:data);setMore(data.length===20);setState('ready');})
    .catch(()=>{if(!controller.signal.aborted)setState('error');});
  },300);
  return ()=>{clearTimeout(timer);controller.abort();};
 },[open,path,query,offset,retry]);
 useEffect(()=>{if(active>=0)list.current?.children[active]?.scrollIntoView({block:'nearest'});},[active]);
 function show(){if(open)return;setQuery('');setRows([]);setOffset(0);setActive(-1);setMore(false);setState('loading');setOpen(true);}
 function choose(row:T){onSelect(row);setOpen(false);setActive(-1);input.current?.focus();}
 function loadMore(){setState('loading');setOffset(rows.length);}
 return <div className="catalog-combobox" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget)){setOpen(false);setActive(-1);}}}>
  <label htmlFor={id}>{label}</label>
  <div className="catalog-combobox-control">
   <input ref={input} id={id} role="combobox" autoComplete="off" aria-autocomplete="list" aria-expanded={open}
    aria-controls={`${id}-list`} aria-describedby={open?`${id}-status`:undefined} aria-activedescendant={open&&active>=0?`${id}-option-${active}`:undefined}
    value={open?query:selected} placeholder={label} onFocus={show} onClick={show}
    onChange={event=>{setQuery(event.target.value);setOffset(0);setRows([]);setActive(-1);setMore(false);setState('loading');setOpen(true);}}
    onKeyDown={event=>{
     if(event.key==='Escape'){event.preventDefault();setOpen(false);setActive(-1);}
     else if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      event.preventDefault();if(!open){show();return;}
      if(rows.length)setActive(n=>event.key==='ArrowDown'?Math.min(n+1,rows.length-1):Math.max(n-1,0));
     }else if(event.key==='Enter'){event.preventDefault();if(!open)show();else if(active>=0&&rows[active])choose(rows[active]);}
    }}/>
   <button type="button" aria-label={`${t.clear}: ${label}`} disabled={!selected&&!query} onClick={()=>{onClear();setQuery('');setRows([]);setOffset(0);setActive(-1);setState('loading');setOpen(true);setRetry(n=>n+1);input.current?.focus();}}>{t.clear}</button>
  </div>
  {open&&<div className="catalog-combobox-popup">
   <ul ref={list} id={`${id}-list`} role="listbox" aria-label={label} aria-busy={state==='loading'}>
    {rows.map((row,index)=><li key={row.id} id={`${id}-option-${index}`} role="option" aria-selected={index===active}
     className={index===active?'is-active':''} onMouseDown={event=>event.preventDefault()} onClick={()=>choose(row)}>{render(row)}</li>)}
   </ul>
   <p id={`${id}-status`} role="status">{state==='loading'?t.loading:state==='error'?t.error:!rows.length?t.empty:!more?t.end:''}</p>
   {state==='error'&&<button type="button" onClick={()=>{setState('loading');setRetry(n=>n+1);}}>{t.retry}</button>}
   {more&&state!=='error'&&<button type="button" disabled={state==='loading'} onClick={loadMore}>{t.more}</button>}
  </div>}
 </div>;
}
