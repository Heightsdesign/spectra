"""Local C1 storage and preview integration. Logistics Checkout stays disabled."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import inspect, select

from app.auth import now
from app.logistics_calculator import calculate_logistics, catalog_issues, commercial_preview
from app.logistics_models import (
    LogisticsCatalog, LogisticsPublication, LogisticsState, SubmissionLogisticsSelection,
)
from app.logistics_schemas import ColissimoCatalog, LogisticsSelection
from app.pricing_models import QuoteAcceptance
from app.submission_models import Submission


def document_hash(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def store_catalog(db, document):
    config = ColissimoCatalog.model_validate(document)
    canonical = config.model_dump(mode='json')
    record = LogisticsCatalog(document=canonical, sha256=document_hash(canonical))
    db.add(record)
    db.flush()
    return record


def catalog_document(record):
    if document_hash(record.document) != record.sha256:
        raise HTTPException(503, 'logistics_catalog_integrity_error')
    return ColissimoCatalog.model_validate(record.document)


def transition_catalog(db, version, status, *, actor_reference, reason, settings):
    """Trusted operator operation; no production publication exists in C1-B."""
    if status not in {'validated', 'published_test', 'withdrawn'}:
        raise ValueError('Production publication is disabled in C1-B')
    if not actor_reference.strip() or not reason.strip() or len(actor_reference) > 500 or len(reason) > 1000:
        raise ValueError('Actor and reason required')
    state = db.scalar(select(LogisticsState).where(LogisticsState.id == 1).with_for_update())
    if state is None:
        raise ValueError('Apply migration 0016 before using C1')
    record = db.get(LogisticsCatalog, version)
    if record is None:
        raise ValueError('Unknown logistics catalog')
    config = catalog_document(record)
    previous = db.scalar(select(LogisticsPublication).where(LogisticsPublication.catalog_version == version)
                         .order_by(LogisticsPublication.sequence.desc()).limit(1))
    if status != 'withdrawn':
        if catalog_issues(config):
            raise ValueError('Contractual data incomplete')
        if config.provenance == 'provisional':
            raise ValueError('Provisional catalogs cannot be validated or published')
    if status == 'published_test':
        if settings.auth_environment != 'development' or settings.stripe_mode != 'test':
            raise ValueError('Test publication is development-only')
        if not previous or previous.status != 'validated':
            raise ValueError('Catalog must be validated before publication')
        if not config.period.start <= now() < config.period.end:
            raise ValueError('Catalog outside validity')
        state.current_version = version
    elif status == 'withdrawn' and state.current_version == version:
        state.current_version = None
    event = LogisticsPublication(catalog_version=version,
                                 sequence=previous.sequence + 1 if previous else 1,
                                 status=status, actor_reference=actor_reference, reason=reason)
    db.add(event)
    db.flush()
    return event


def latest_selection(db, sid):
    return db.scalar(select(SubmissionLogisticsSelection)
                     .where(SubmissionLogisticsSelection.submission_id == sid)
                     .order_by(SubmissionLogisticsSelection.version.desc()).limit(1))


def uses_logistics(item, db, settings):
    """Opt-in for new drafts; an existing C1 choice can never downgrade to legacy.

    The existence check also permits old installations to keep serving historical
    shipping before additive migration 0016 is deployed. No schema is created here.
    Do not cache this across transactions or migrations.
    """
    if settings is not None and settings.logistics_enabled:
        return True
    return bool(inspect(db.connection()).has_table('submission_logistics_selections')
                and latest_selection(db, item.id))


def save_selection(db, sid, version, selection: LogisticsSelection):
    # Same order lock as quote acceptance and Stripe. Append versions, never edit.
    item = db.scalar(select(Submission).where(Submission.id == sid).with_for_update())
    if item is None:
        raise HTTPException(404, 'submission_not_found')
    if db.get(QuoteAcceptance, sid):
        raise HTTPException(409, 'terms_already_accepted')
    old = latest_selection(db, sid)
    if version != (old.version if old else 0):
        raise HTTPException(409, 'logistics_selection_conflict')
    if selection.catalog_version and not db.get(LogisticsCatalog, selection.catalog_version):
        raise HTTPException(422, 'logistics_catalog_unknown')
    document = selection.model_dump(mode='json')
    record = SubmissionLogisticsSelection(submission_id=sid, version=version + 1,
                                         catalog_version=selection.catalog_version,
                                         document=document, sha256=document_hash(document))
    db.add(record)
    db.flush()
    return record


def selection_document(record):
    if document_hash(record.document) != record.sha256:
        raise HTTPException(503, 'logistics_selection_integrity_error')
    selection = LogisticsSelection.model_validate(record.document)
    if selection.catalog_version != record.catalog_version:
        raise HTTPException(503, 'logistics_selection_catalog_mismatch')
    return selection


def logistics_context(item, db):
    state = db.scalar(select(LogisticsState).where(LogisticsState.id == 1)
                      .with_for_update(read=True).execution_options(populate_existing=True))
    if state is None:
        raise HTTPException(503, 'logistics_foundation_unavailable')
    selection = latest_selection(db, item.id)
    return {'logistics_schema_version': 1,
            'logistics_selection_version': selection.version if selection else 0,
            'logistics_selection_sha256': selection.sha256 if selection else None,
            'logistics_catalog_version': str(state.current_version) if state.current_version else None}


def checkout_summary(item, db, settings, grading, configured, pricing_problem=None):
    """Preview in the existing snapshot; a constant gate prevents all C1 payments.

    Legacy submissions use the old summary when logistics_enabled is false.
    Accepted quotes are served by the existing immutable snapshot reader.
    """
    context = logistics_context(item, db)
    record = latest_selection(db, item.id)
    selection = selection_document(record) if record else LogisticsSelection()
    catalog_record = db.get(LogisticsCatalog, selection.catalog_version) if selection.catalog_version else None
    from app.submissions import entries
    keys = [f'{c.id}:{n}' for c in entries(item, db) for n in range(1, c.quantity + 1)]
    result = None
    if catalog_record:
        result = calculate_logistics(catalog_document(catalog_record), selection, at=now(), expected_card_keys=keys)
    states = ['logistics_checkout_disabled_c1b']
    if not record:
        states.append('logistics_selection_required')
    if not catalog_record:
        states.append('logistics_catalog_required')
    if not selection.catalog_version or str(selection.catalog_version) != context['logistics_catalog_version']:
        states.append('logistics_catalog_not_published')
    if result:
        states.extend(result['issues'])
    if pricing_problem:
        states.append(pricing_problem)
    if not configured or not configured[1].commercial_terms_version:
        states.append('commercial_terms_pending')
    preview = commercial_preview(grading, result) if result else None
    if grading and any(x['tax_mode'] == 'pending' or not x['tax_validation_reference'] for x in grading['lines']):
        states.append('tax_configuration_pending')
    return {'logistics_schema_version': 1, 'context': context,
            'stripe_test_only': True, 'commercial_terms_version': configured[1].commercial_terms_version if configured else None,
            'payment': {'status': 'unavailable', 'charging_enabled': False},
            'dispatch_policy': {'calendar_days_after_verified_payment': 30, 'timezone': 'UTC', 'automatic_forfeiture': False},
            'submission_reference': item.reference, 'currency': 'EUR', 'quantity': len(keys),
            'grading': grading, 'pricing_revision': str(configured[0].version) if configured else None,
            'return_address': selection.customer_return.model_dump() if selection.customer_return else None,
            'inbound_receiving_address': None,
            'delivery': {'version': record.version if record else 0, 'address_id': None,
                         'declared_value_minor': sum(i.return_value_minor for i in selection.items),
                         'service_id': selection.return_leg.product_id, 'parcel': selection.return_leg.parcel.model_dump()},
            # Compatibility fields are explicitly unavailable, never a partial payable total.
            'shipping': {'status': 'pending', 'charge_minor': None, 'service': None, 'tax_minor': None, 'net_minor': None},
            'available_services': [], 'shipping_configuration_version': None,
            'adjustments_minor': 0, 'final_payable_minor': None, 'tax_total_minor': None, 'net_total_minor': None,
            'line_items': ([{'kind': 'grading', **x} for x in grading['lines']] if grading else []) + (result['line_items'] if result else []),
            'logistics': {'selection_version': record.version if record else 0,
                          'selection': selection.model_dump(mode='json'),
                          'catalog_version': str(catalog_record.version) if catalog_record else None,
                          'catalog_sha256': catalog_record.sha256 if catalog_record else None,
                          'catalog_document': catalog_record.document if catalog_record else None,
                          'calculation': result, 'commercial_preview': preview},
            'readiness': {'ready': False, 'states': sorted(set(states))}}
