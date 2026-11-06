"""Authenticated selection storage only. No affranchissement/label route."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import write_guard
from app.cards import Config, Db
from app.logistics import latest_selection, save_selection, selection_document
from app.logistics_schemas import SelectionInput
from app.submissions import owned

router = APIRouter(dependencies=[Depends(write_guard)])


def require_foundation(settings):
    if not settings.logistics_enabled:
        raise HTTPException(503, 'logistics_foundation_disabled')


@router.get('/api/submissions/{identifier}/logistics-selection')
def retrieve(identifier: UUID, request: Request, db: Db, settings: Config):
    require_foundation(settings)
    item = owned(identifier, request, db, settings)
    record = latest_selection(db, item.id)
    return {'version': record.version if record else 0,
            'selection': selection_document(record).model_dump(mode='json') if record else None}


@router.put('/api/submissions/{identifier}/logistics-selection')
def update(identifier: UUID, payload: SelectionInput, request: Request, db: Db, settings: Config):
    require_foundation(settings)
    item = owned(identifier, request, db, settings)
    record = save_selection(db, item.id, payload.version, payload.selection)
    db.commit()
    return {'version': record.version, 'selection': record.document}
