"""Trusted local catalogue tooling. C1-B deliberately has no production publish."""
import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.logistics import store_catalog, transition_catalog
from app.logistics_calculator import catalog_issues
from app.logistics_schemas import ColissimoCatalog


def main():
    parser = argparse.ArgumentParser(description='Colissimo foundation; no real tariffs supplied')
    parser.add_argument('action', choices=['validate', 'store', 'validated', 'published_test', 'withdrawn'])
    parser.add_argument('document_or_version')
    parser.add_argument('--actor', default='')
    parser.add_argument('--reason', default='')
    args = parser.parse_args()
    if args.action in {'validate', 'store'}:
        path = Path(args.document_or_version)
        if path.stat().st_size > 2_000_000:
            parser.error('Document exceeds 2 MB')
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        config = ColissimoCatalog.model_validate(document)
        if args.action == 'validate':
            print(json.dumps({'issues': catalog_issues(config), 'production_publish_available': False}))
            return
        with Session(get_engine()) as db:
            record = store_catalog(db, document)
            db.commit()
            print(f'Stored immutable draft {record.version}; no publication')
        return
    with Session(get_engine()) as db:
        transition_catalog(db, UUID(args.document_or_version), args.action,
                           actor_reference=args.actor, reason=args.reason, settings=get_settings())
        db.commit()
        print('Recorded catalog transition; logistics Checkout remains disabled')


if __name__ == '__main__':
    main()
