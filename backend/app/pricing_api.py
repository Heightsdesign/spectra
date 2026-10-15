from datetime import timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import select

from app.auth import now, write_guard
from app.checkout import context as checkout_context, summary as checkout_summary
from app.cards import Db, Config
from app.pricing import calculate, current_catalog, validate_selection
from app.pricing_models import PricingState, QuoteAcceptance, SubmissionQuote
from app.pricing_schemas import Configuration
from app.submission_schemas import Version
from app.submissions import editable, entries, entry_for, owned, owner, save

router = APIRouter(prefix="/api/submissions", dependencies=[Depends(write_guard)])


class Acceptance(Version):
    accept_terms: bool = Field(strict=True)

    @model_validator(mode="after")
    def explicit_consent(self):
        if not self.accept_terms:
            raise ValueError("Explicit acceptance is required")
        return self


@router.get("/catalog")
def catalog(request: Request, db: Db, settings: Config):
    owner(request, db, settings)
    record, config = current_catalog(db, settings)
    document = config.model_dump(exclude={"approval_reference"})
    document["tiers"] = dict(sorted(document["tiers"].items(), key=lambda pair: (pair[1]["display_order"], pair[0])))
    document["upgrades"] = dict(sorted(document["upgrades"].items(), key=lambda pair: (pair[1]["display_order"], pair[0])))
    return {"version": record.version, **document}


@router.patch("/{identifier}/configuration")
def apply_all(identifier: UUID, payload: Configuration, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    validate_selection(db, settings, payload.processing_tier, payload.upgrade_ids)
    cards = entries(item, db)
    if not cards:
        raise HTTPException(422, "submission_empty")
    for card in cards:
        card.processing_tier = payload.processing_tier
        card.upgrade_ids = sorted(payload.upgrade_ids)
    return save(item, db)


@router.patch("/{identifier}/entries/{entry_id}/configuration")
def configure_entry(identifier: UUID, entry_id: UUID, payload: Configuration, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    card = entry_for(item, entry_id, db)
    validate_selection(db, settings, payload.processing_tier, payload.upgrade_ids)
    card.processing_tier = payload.processing_tier
    card.upgrade_ids = sorted(payload.upgrade_ids)
    return save(item, db)


def acceptance_for(item, db):
    return db.get(QuoteAcceptance, item.id)


def quote_status(quote, item, db, settings):
    accepted = acceptance_for(item, db)
    if accepted and accepted.quote_id == quote.id:
        return "accepted"
    if accepted:
        return "superseded"
    if quote.pricing_revision != item.pricing_revision:
        return "invalidated"
    if quote.expires_at <= now():
        return "expired"
    state = db.get(PricingState, 1, populate_existing=True)
    if not state or state.current_version != quote.catalog_version:
        return "catalog_changed"
    if settings.auth_environment == "production" and quote.snapshot["development_only"]:
        return "unavailable"
    if quote.snapshot.get("checkout", {}).get("context") != checkout_context(item, db):
        return "invalidated"
    return "valid"


def public_quote(quote, item, db, settings):
    accepted = acceptance_for(item, db)
    return {"id": quote.id, "submission_id": item.id,
            "pricing_revision": quote.pricing_revision, "pricing_configuration_version": quote.catalog_version,
            "created_at": quote.created_at.astimezone(timezone.utc), "expires_at": quote.expires_at.astimezone(timezone.utc),
            "status": quote_status(quote, item, db, settings),
            "accepted_at": accepted.accepted_at.astimezone(timezone.utc) if accepted and accepted.quote_id == quote.id else None,
            "snapshot": quote.snapshot}


def owned_quote(item, quote_id, db):
    quote = db.scalar(select(SubmissionQuote).where(SubmissionQuote.id == quote_id, SubmissionQuote.submission_id == item.id))
    if quote is None:
        raise HTTPException(404, "quote_not_found")
    return quote


@router.post("/{identifier}/quotes", status_code=201)
def create_quote(identifier: UUID, payload: Version, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    if item.version != payload.version:
        raise HTTPException(409, "submission_conflict")
    if acceptance_for(item, db):
        raise HTTPException(409, "terms_already_accepted")
    record, config = current_catalog(db, settings)
    cards = entries(item, db)
    if not cards:
        raise HTTPException(422, "submission_empty")
    # Simultaneous requests return the same unexpired quote for this revision.
    existing = db.scalar(select(SubmissionQuote).where(SubmissionQuote.submission_id == item.id,
                         SubmissionQuote.pricing_revision == item.pricing_revision,
                         SubmissionQuote.catalog_version == record.version,
                         SubmissionQuote.expires_at > now()).order_by(SubmissionQuote.created_at.desc()).limit(1))
    if existing and quote_status(existing, item, db, settings) == "valid":
        return public_quote(existing, item, db, settings)
    timestamp = now()
    snapshot = calculate(config, cards)
    snapshot["submission_notes"] = item.notes
    snapshot["checkout"] = checkout_summary(item, db, settings, (record, config))
    quote = SubmissionQuote(submission_id=item.id, pricing_revision=item.pricing_revision,
                            catalog_version=record.version, snapshot=snapshot, created_at=timestamp,
                            expires_at=timestamp + timedelta(seconds=config.quote_lifetime_seconds))
    db.add(quote)
    db.flush()
    result = public_quote(quote, item, db, settings)
    db.commit()
    return result


@router.get("/{identifier}/quotes")
def list_quotes(identifier: UUID, request: Request, db: Db, settings: Config, offset: int = 0, limit: int = 50):
    item = owned(identifier, request, db, settings)
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "invalid_input")
    quotes = db.scalars(select(SubmissionQuote).where(SubmissionQuote.submission_id == item.id).order_by(SubmissionQuote.created_at.desc(), SubmissionQuote.id).offset(offset).limit(limit)).all()
    return [public_quote(q, item, db, settings) for q in quotes]


@router.get("/{identifier}/quotes/{quote_id}")
def retrieve_quote(identifier: UUID, quote_id: UUID, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    return public_quote(owned_quote(item, quote_id, db), item, db, settings)


@router.post("/{identifier}/quotes/{quote_id}/accept")
def accept_quote(identifier: UUID, quote_id: UUID, payload: Acceptance, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    quote = owned_quote(item, quote_id, db)
    accepted = acceptance_for(item, db)
    if accepted:
        if accepted.quote_id != quote.id:
            raise HTTPException(409, "terms_already_accepted")
        return public_quote(quote, item, db, settings)
    if item.version != payload.version:
        raise HTTPException(409, "submission_conflict")
    if item.status != "submitted":
        raise HTTPException(409, "confirm_before_acceptance")
    current_catalog(db, settings)  # Shared lock against publication until commit.
    if quote_status(quote, item, db, settings) != "valid":
        raise HTTPException(409, "quote_stale")
    if quote.snapshot["development_only"]:
        raise HTTPException(409, "example_terms_not_acceptable")
    if not quote.snapshot.get("checkout", {}).get("readiness", {}).get("ready"):
        raise HTTPException(409, "checkout_not_ready")
    accepted_at = now()
    if quote.expires_at <= accepted_at:
        raise HTTPException(409, "quote_stale")
    db.add(QuoteAcceptance(submission_id=item.id, quote_id=quote.id, accepted_at=accepted_at))
    db.flush()
    result = public_quote(quote, item, db, settings)
    db.commit()
    return result
