"""One eligibility policy for lookup and every inspection mutation.

Authentication and membership are enforced before calling this policy. All writes
hold the submission lock, shared with intake and quote acceptance commands.
"""
from sqlalchemy import select, or_
from app.intake_models import Intake, Parcel, Discrepancy
from app.submission_models import SubmissionEntry
from app.pricing_models import QuoteAcceptance, SubmissionQuote

REASONS = {
 'card_voided': ('This identity is a voided registration, not an active physical card.', 'Cette identité est une inscription annulée, pas une carte physique active.'),
 'customer_copy_returned': ('This physical copy was recorded as returned to the customer.', 'Cette copie physique a été déclarée restituée au client.'),
 'intake_not_reconciled': ('Intake must be reconciled.', 'Le rapprochement doit être terminé.'),
 'association_invalid': ('Verify the declared card and parcel association.', 'Vérifiez la déclaration et le colis associés.'),
 'discrepancy_block': ('An unresolved or acknowledged concern blocks inspection.', 'Un écart ouvert ou reconnu bloque l’inspection.'),
 'quote_not_accepted': ('Commercial quote acceptance is required.', 'Le devis doit être accepté.'),
 'payment_unverified': ('Independent payment confirmation is unavailable (W4).', 'Confirmation indépendante du paiement indisponible (W4).'),
 'commercial_restriction': ('Commercial clearance is not proven.', 'La levée des restrictions commerciales n’est pas établie.'),
 'operation_conflict': ('Inspection or custody state prevents this action.', 'L’état de l’inspection ou de garde bloque cette action.')}

def eligibility(db, card, provider, operation='start', dossier=None):
    reasons = []
    from app.intake_voids import PhysicalCardVoid
    if db.get(PhysicalCardVoid, card.id): reasons.append('card_voided')
    from app.library_models import CopyAssignment
    if card.entry_id and db.scalar(select(CopyAssignment.id).where(CopyAssignment.entry_id==card.entry_id,CopyAssignment.released_at.is_not(None))):
        reasons.append('customer_copy_returned')
    intake = db.get(Intake, card.submission_id)
    if not intake or intake.status != 'reconciled': reasons.append('intake_not_reconciled')
    entry = db.get(SubmissionEntry, card.entry_id) if card.entry_id else None
    parcel = db.get(Parcel, card.parcel_id)
    if not entry or entry.submission_id != card.submission_id or not parcel or parcel.submission_id != card.submission_id or card.status != 'matched': reasons.append('association_invalid')
    issues = db.scalars(select(Discrepancy).where(Discrepancy.submission_id == card.submission_id, Discrepancy.status != 'resolved', or_(Discrepancy.card_id == card.id, Discrepancy.card_id.is_(None))))
    # Acknowledged missing quantities concern absent objects, not correctly matched cards.
    if any(i.status == 'open' or i.kind != 'missing' for i in issues): reasons.append('discrepancy_block')
    acceptance = db.get(QuoteAcceptance, card.submission_id)
    quote = db.get(SubmissionQuote, acceptance.quote_id) if acceptance else None
    if not quote or quote.submission_id != card.submission_id:
        reasons.append('quote_not_accepted')
        acceptance = None
    evidence = provider(db, acceptance)
    if not evidence.payment_verified: reasons.append('payment_unverified')
    if not evidence.unrestricted: reasons.append('commercial_restriction')
    expected = {'start': None, 'pause': 'in_progress', 'resume': 'paused', 'image': 'in_progress'}[operation]
    if (expected is None and dossier) or (expected is not None and (not dossier or dossier.status != expected or dossier.location != ('inspection_hold_storage' if expected == 'paused' else 'inspection_workstation'))): reasons.append('operation_conflict')
    return {'eligible': not reasons, 'reasons': [{'code': r, 'en': REASONS[r][0], 'fr': REASONS[r][1]} for r in reasons]}
