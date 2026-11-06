"""Operator-only, atomic one-set TCGdex import. No runtime provider dependency."""
import argparse
import json
import re
from urllib.request import urlopen
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_engine
from app.tcg_models import Expansion, CatalogCard


def import_set(db, language, document):
    from datetime import date
    from app.submission_schemas import Text, ShortText
    from pydantic import TypeAdapter
    text, short = TypeAdapter(Text), TypeAdapter(ShortText)
    external_id = text.validate_python(document['id'])
    name = text.validate_python(document['name'])
    year = date.fromisoformat(document['releaseDate']).year if document.get('releaseDate') else None
    cards = [(text.validate_python(c['id']), text.validate_python(c['name']), short.validate_python(c['localId'])) for c in document['cards']]
    expansion = db.scalar(select(Expansion).where(Expansion.provider == 'tcgdex', Expansion.external_id == external_id, Expansion.language == language))
    if expansion is None:
        expansion = Expansion(game='pokemon', provider='tcgdex', external_id=external_id, language=language)
        db.add(expansion)
    expansion.name, expansion.code, expansion.release_year = name, external_id, year
    db.flush()
    for identifier, card_name, number in cards:
        row = db.scalar(select(CatalogCard).where(CatalogCard.provider == 'tcgdex', CatalogCard.external_id == identifier, CatalogCard.language == language))
        if row is None:
            row = CatalogCard(provider='tcgdex', external_id=identifier, language=language)
            db.add(row)
        row.expansion_id, row.name, row.collector_number = expansion.id, card_name, number
    db.flush()
    return len(cards)


def fetch_set(language, identifier):
    if language not in ('fr', 'en') or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', identifier):
        raise ValueError('Unsupported language or invalid set ID')
    # One request per explicit operator invocation; timeout/429 fail without retries.
    with urlopen(f'https://api.tcgdex.net/v2/{language}/sets/{identifier}', timeout=20) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError('Provider response too large')
    result = json.loads(raw)
    if result['id'] != identifier:
        raise ValueError('Provider set mismatch')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=['fr', 'en'], required=True)
    parser.add_argument('--set', required=True)
    args = parser.parse_args()
    document = fetch_set(args.language, args.set)
    with Session(get_engine()) as db, db.begin():
        count = import_set(db, args.language, document)
    print(f'Imported {count} cards; existing submission snapshots unchanged.')


if __name__ == '__main__':
    main()
