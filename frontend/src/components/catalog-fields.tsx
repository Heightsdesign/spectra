"use client";
import { useState } from 'react';
import { games, submissionMessages, type Entry } from '@/lib/submissions';
import { restoreDeclaration, resetDeclaration, selectExpansion, selectCard, manualDeclaration } from '@/lib/catalog';
import type { Language } from '@/lib/i18n';
import { CatalogCombobox } from './catalog-combobox';

type SetRow = {id:string;name:string;code:string};
type CardRow = {id:string;name:string;collector_number:string;language:string;expansion_name:string;expansion_code:string};

export function CatalogFields({entry,lang,onDirty}:{entry:Entry|null;lang:Language;onDirty:()=>void}) {
 const t=submissionMessages[lang]; const fr=lang==='FR';
 const [values,setValues]=useState(()=>restoreDeclaration(entry));
 const [manual,setManual]=useState(!entry?.catalog_card_id);
 const [language,setLanguage]=useState(entry?.language==='en'?'en':entry?.language==='fr'?'fr':lang.toLowerCase());
 const [expansion,setExpansion]=useState<SetRow|null>(null);
 function reset(game=values.game){setExpansion(null);setValues(resetDeclaration(game));onDirty();}
 const scope=`game=${encodeURIComponent(values.game)}&language=${encodeURIComponent(language)}`;
 return <>
  <label>{t.game}<select name="game" required value={values.game} onChange={e=>reset(e.target.value)}>{Object.entries(games).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
  <label className="catalog-assistance"><input type="checkbox" checked={!manual} onChange={e=>{setManual(!e.target.checked);setValues(manualDeclaration);onDirty();}}/>{fr?'Aide du catalogue (facultative)':'Catalog assistance (optional)'}</label>
  {!manual&&<>
   <label>{fr?'Langue du catalogue':'Catalog language'}<select aria-label={fr?'Langue du catalogue':'Catalog language'} value={language} onChange={e=>{setLanguage(e.target.value);reset();}}><option value="fr">Français</option><option value="en">English</option></select></label>
   <CatalogCombobox<SetRow> key={`sets-${scope}`} path={`expansions?${scope}`} lang={lang}
    label={fr?'Extension (filtre facultatif)':'Set (optional filter)'} selected={expansion?`${expansion.name} (${expansion.code})`:''}
    render={row=>`${row.name} (${row.code})`}
    onSelect={row=>{onDirty();setExpansion(row);setValues(v=>selectExpansion(v,row.name));}}
    onClear={()=>reset()}/>
   <CatalogCombobox<CardRow> key={`cards-${scope}-${expansion?.id??'all'}`} lang={lang}
    path={`cards?${scope}${expansion?`&expansion_id=${encodeURIComponent(expansion.id)}`:''}`}
    label={fr?'Rechercher une carte':'Search cards'}
    selected={values.catalog_card_id?`${values.card_name} — ${values.expansion} — ${values.card_number} — ${values.language.toUpperCase()}`:''}
    render={row=>`${row.name} — ${row.expansion_name} (${row.expansion_code}) — ${row.collector_number} — ${row.language.toUpperCase()}`}
    onSelect={row=>{onDirty();setValues(v=>selectCard(v,row));}}
    onClear={()=>{onDirty();setValues(v=>selectExpansion(v,expansion?.name??''));}}/>
  </>}
  <input type="hidden" name="catalog_card_id" value={values.catalog_card_id}/>
  <div className="form-pair">{(['card_name','expansion','card_number','language'] as const).map(key=><label key={key}>{t[key]}{(key==='expansion'||key==='card_number')&&(fr?' (facultatif)':' (optional)')}<input name={key} required={key==='card_name'||key==='language'} maxLength={key==='card_name'||key==='expansion'?200:64} value={values[key]} onChange={e=>setValues(v=>({...v,[key]:e.target.value,catalog_card_id:''}))}/></label>)}</div>
 </>;
}
