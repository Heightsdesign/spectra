"""Authenticated local catalog reads; no upstream requests on the customer path."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from app.cards import Db, Config
from app.submissions import owner
from app.tcg_models import Game, Expansion, CatalogCard

router = APIRouter(prefix='/api/catalog')


def public(record):
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


@router.get('/games')
def games(request: Request, db: Db, settings: Config):
    owner(request, db, settings)
    return [public(row) for row in db.scalars(select(Game).order_by(Game.id))]


@router.get('/expansions')
def expansions(request: Request, db: Db, settings: Config, game: str,
               language: str = 'fr', q: str = Query('', max_length=200),
               offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    owner(request, db, settings)
    query = select(Expansion).where(Expansion.game == game, Expansion.language == language)
    if q.strip():
        query = query.where(Expansion.name.icontains(q.strip(), autoescape=True) | Expansion.code.icontains(q.strip(), autoescape=True))
    return [public(row) for row in db.scalars(query.order_by(Expansion.name, Expansion.id).offset(offset).limit(limit))]


@router.get('/cards')
def cards(request: Request, db: Db, settings: Config, expansion_id: UUID | None = None,
          game: str | None = Query(None, max_length=64), language: str | None = Query(None, max_length=64),
          q: str = Query('', max_length=200), offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    owner(request, db, settings)
    if expansion_id is None and (not game or not language):
        raise HTTPException(422, 'catalog_scope_required')
    query = select(CatalogCard, Expansion).join(Expansion, CatalogCard.expansion_id == Expansion.id)
    if expansion_id is not None:
        query = query.where(CatalogCard.expansion_id == expansion_id)
    if game is not None:
        query = query.where(Expansion.game == game)
    if language is not None:
        query = query.where(CatalogCard.language == language, Expansion.language == language)
    if q.strip():
        query = query.where(CatalogCard.name.icontains(q.strip(), autoescape=True) | CatalogCard.collector_number.icontains(q.strip(), autoescape=True))
    return [card_public(row, expansion) for row, expansion in db.execute(
        query.order_by(CatalogCard.name, CatalogCard.collector_number, CatalogCard.id).offset(offset).limit(limit))]


def card_public(row, expansion):
    return {**public(row), 'game': expansion.game,
            'expansion_name': expansion.name, 'expansion_code': expansion.code}


@router.get('/cards/{identifier}')
def card(identifier: UUID, request: Request, db: Db, settings: Config):
    owner(request, db, settings)
    row = db.get(CatalogCard, identifier)
    if row is None:
        raise HTTPException(404, 'catalog_card_not_found')
    return card_public(row, db.get(Expansion, row.expansion_id))


def validate_catalog_entry(db, values):
    identifier = values.get('catalog_card_id')
    if identifier is None:
        return
    row = db.get(CatalogCard, identifier)
    expansion = db.get(Expansion, row.expansion_id) if row else None
    if not expansion or any(values[key] != expected for key, expected in {
        'game': expansion.game, 'card_name': row.name, 'expansion': expansion.name,
        'card_number': row.collector_number, 'language': row.language}.items()):
        raise HTTPException(422, 'catalog_selection_invalid')
