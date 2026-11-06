"""Trusted server integration boundary. No request/configuration payment assertions."""
from dataclasses import dataclass
from typing import Protocol
from sqlalchemy.orm import Session
from app.pricing_models import QuoteAcceptance

@dataclass(frozen=True)
class CommercialEvidence:
    payment_verified: bool = False
    unrestricted: bool = False


class CommercialProvider(Protocol):
    def __call__(self, db: Session, acceptance: QuoteAcceptance | None) -> CommercialEvidence:
        """Read trusted evidence for this accepted quote, including current holds.

        W4 must check amount, currency, quote identity, settlement, refunds and
        restrictions. Unknown payment requirements also remain unverified.
        A zero-priced quote alone is never evidence of a payment exemption.
        """
        ...


def unavailable_commercial_evidence(db, acceptance):
    return CommercialEvidence()


def commercial_provider():
    # W4 must replace this provider with independently verified, durable evidence
    # scoped to the immutable accepted quote, including refunds and holds.
    return unavailable_commercial_evidence


def pc_commercial_evidence(db, physical_card):
    """Prepared PC-scoped adapter. Does not authorize receipt/inspection/grading.

    Deliberately NOT installed as the legacy order-acceptance provider.
    """
    from app.commercial import card_commercial_state
    result = card_commercial_state(db, physical_card)
    return CommercialEvidence(payment_verified=result["commercially_eligible"],
                              unrestricted=result["commercially_eligible"])
