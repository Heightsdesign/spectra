import type { Entry } from './submissions.ts';
export type CatalogFieldsValue = {game:string;card_name:string;expansion:string;card_number:string;language:string;catalog_card_id:string};
export function restoreDeclaration(entry:Entry|null):CatalogFieldsValue {
 return {game:entry?.game??'pokemon',card_name:entry?.card_name??'',expansion:entry?.expansion??'',card_number:entry?.card_number??'',language:entry?.language??'',catalog_card_id:entry?.catalog_card_id??''};
}
export function resetDeclaration(game:string):CatalogFieldsValue {
 return {...restoreDeclaration(null),game};
}
export function selectExpansion(values:CatalogFieldsValue,name:string):CatalogFieldsValue {
 return {...resetDeclaration(values.game),expansion:name};
}
export function selectCard(values:CatalogFieldsValue,card:{id:string;name:string;collector_number:string;language:string;expansion_name?:string}):CatalogFieldsValue {
 return {...values,expansion:card.expansion_name??values.expansion,card_name:card.name,card_number:card.collector_number,language:card.language,catalog_card_id:card.id};
}
export function manualDeclaration(values:CatalogFieldsValue):CatalogFieldsValue {
 return {...values,catalog_card_id:''};
}
