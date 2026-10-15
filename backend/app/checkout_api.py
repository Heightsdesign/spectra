from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.auth import now, write_guard
from app.cards import Config, Db
from app.checkout import address_snapshot, shipping_config, summary
from app.checkout_models import CustomerAddress, SubmissionDelivery
from app.checkout_schemas import Address, AddressUpdate, Delivery
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.submission_schemas import Version
from app.submissions import owned, owner

router = APIRouter(dependencies=[Depends(write_guard)])


def owned_address(identifier, customer, db):
    address = db.scalar(select(CustomerAddress).where(CustomerAddress.id == identifier, CustomerAddress.customer_id == customer.id).with_for_update().execution_options(populate_existing=True))
    if address is None:
        raise HTTPException(404, "address_not_found")
    return address


@router.get("/api/addresses")
def list_addresses(request: Request, db: Db, settings: Config):
    customer = owner(request, db, settings)
    return [address_snapshot(a) for a in db.scalars(select(CustomerAddress).where(CustomerAddress.customer_id == customer.id).order_by(CustomerAddress.created_at, CustomerAddress.id).limit(100))]


@router.post("/api/addresses", status_code=201)
def create_address(payload: Address, request: Request, db: Db, settings: Config):
    customer = owner(request, db, settings)
    if db.scalar(select(func.count()).select_from(CustomerAddress).where(CustomerAddress.customer_id == customer.id)) >= 100:
        raise HTTPException(422, "address_limit")
    address = CustomerAddress(customer_id=customer.id, **payload.model_dump())
    db.add(address)
    db.flush()
    result = address_snapshot(address)
    db.commit()
    return result


@router.put("/api/addresses/{identifier}")
def update_address(identifier: UUID, payload: AddressUpdate, request: Request, db: Db, settings: Config):
    address = owned_address(identifier, owner(request, db, settings), db)
    if address.version != payload.version:
        raise HTTPException(409, "address_conflict")
    for field, value in payload.model_dump(exclude={"version"}).items():
        setattr(address, field, value)
    address.version += 1
    address.updated_at = now()
    db.flush()
    result = address_snapshot(address)
    db.commit()
    return result


@router.delete("/api/addresses/{identifier}")
def delete_address(identifier: UUID, payload: Version, request: Request, db: Db, settings: Config):
    address = owned_address(identifier, owner(request, db, settings), db)
    if address.version != payload.version:
        raise HTTPException(409, "address_conflict")
    if db.scalar(select(SubmissionDelivery.submission_id).where(SubmissionDelivery.address_id == address.id).limit(1)):
        raise HTTPException(409, "address_in_use")
    db.delete(address)
    db.commit()
    return {"deleted": True}


@router.get("/api/submissions/{identifier}/order-summary")
def order_summary(identifier: UUID, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    accepted = db.get(QuoteAcceptance, item.id)
    if accepted:
        quote = db.get(SubmissionQuote, accepted.quote_id)
        if "checkout" in quote.snapshot:
            return {**quote.snapshot["checkout"], "terms_accepted": True}
        result = summary(item, db, settings)
        result.update(grading=None, final_payable_minor=None, readiness={"ready": False, "states": ["legacy_grading_terms"]}, terms_accepted=True,
                      historical_grading_quote_id=str(quote.id))
        return result
    return {**summary(item, db, settings), "terms_accepted": False}


@router.put("/api/submissions/{identifier}/delivery")
def update_delivery(identifier: UUID, payload: Delivery, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    if db.get(QuoteAcceptance, item.id):
        raise HTTPException(409, "terms_already_accepted")
    delivery = db.get(SubmissionDelivery, item.id, populate_existing=True)
    if payload.version != (delivery.version if delivery else 0):
        raise HTTPException(409, "delivery_conflict")
    address = None
    if payload.address_id:
        # Never trust a customer-supplied address identifier.
        address = owned_address(payload.address_id, owner(request, db, settings), db)
    if payload.service_id:
        _, config = shipping_config(db)
        service = config.services.get(payload.service_id)
        if not service or not service.available or not address or address.country not in service.countries:
            raise HTTPException(422, "shipping_service_unavailable")
    if not delivery:
        delivery = SubmissionDelivery(submission_id=item.id, version=0)
        db.add(delivery)
    for field, value in payload.model_dump(exclude={"version"}).items():
        setattr(delivery, field, value)
    delivery.version += 1
    db.flush()
    result = summary(item, db, settings)
    db.commit()
    return result
