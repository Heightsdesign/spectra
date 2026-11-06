import test from 'node:test';
import assert from 'node:assert/strict';
import {restoreDeclaration,resetDeclaration,selectExpansion,selectCard,manualDeclaration} from '../src/lib/catalog.ts';

const card={id:'catalog-1',name:'Localized name',collector_number:'TG01/030',language:'fr'};
test('parent selection resets card identity and preserves game only',()=>{
 const picked=selectCard(selectExpansion(resetDeclaration('pokemon'),'Set'),card);
 assert.deepEqual(resetDeclaration('one-piece'),{game:'one-piece',card_name:'',expansion:'',card_number:'',language:'',catalog_card_id:''});
 assert.deepEqual(selectExpansion(picked,'Other'),{game:'pokemon',card_name:'',expansion:'Other',card_number:'',language:'',catalog_card_id:''});
});
test('selection populates localized name and opaque collector number',()=>{
 const picked=selectCard(selectExpansion(resetDeclaration('pokemon'),'Set'),card);
 assert.equal(picked.card_name,card.name);assert.equal(picked.card_number,'TG01/030');assert.equal(picked.language,'fr');
 assert.equal(picked.expansion,'Set');assert.equal(picked.catalog_card_id,card.id);
});
test('explicit manual fallback retains declared data and detaches reference',()=>{
 const picked=selectCard(selectExpansion(resetDeclaration('pokemon'),'Set'),card);
 assert.deepEqual(manualDeclaration(picked),{...picked,catalog_card_id:''});
});
test('server drafts restore multiple catalog and legacy declarations independently',()=>{
 const first=selectCard(selectExpansion(resetDeclaration('pokemon'),'Set'),card);
 const second={...resetDeclaration('naruto'),card_name:'Manual',expansion:'Unknown',card_number:'A-01',language:'JP'};
 const restored=JSON.parse(JSON.stringify([first,second])).map(restoreDeclaration);
 assert.deepEqual(restored,[first,second]);
 assert.equal(selectCard(restored[0],{...card,name:'Changed'}).card_name,'Changed');
 assert.equal(restored[1].card_name,'Manual');
});

test('name-first search selects a specific printing and fills its expansion',()=>{
 const first=selectCard(resetDeclaration('pokemon'),{...card,expansion_name:'First set'});
 const second=selectCard(first,{...card,id:'catalog-2',expansion_name:'Second set',collector_number:'021'});
 assert.equal(first.card_name,second.card_name);
 assert.notEqual(first.catalog_card_id,second.catalog_card_id);
 assert.equal(second.expansion,'Second set');assert.equal(second.card_number,'021');
});

test('language reset removes the old localized printing and manual data stays explicit',()=>{
 const selected=selectCard(resetDeclaration('pokemon'),{...card,expansion_name:'Set'});
 assert.equal(resetDeclaration(selected.game).catalog_card_id,'');
 assert.equal(resetDeclaration(selected.game).language,'');
 const manual={...manualDeclaration(selected),card_name:'My declaration',language:'JP'};
 assert.deepEqual(restoreDeclaration(manual),manual);
 assert.equal(manual.catalog_card_id,'');
});
