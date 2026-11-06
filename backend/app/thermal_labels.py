"""Operator-controlled thermal jobs; immutable intake audit is the issuance ledger."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from app.cards import Config, Db
from app.intake import Payload, audit, router, staff, submission
from app.intake_models import IntakeAudit
from app.physical_identity import encode_label
from app.production import Commerce, snapshot


def manifest(db, item, actor, provider):
    state = snapshot(db, item, actor, provider)
    data = state["submission"]
    entries = {str(e["id"]): e for e in data["entries"]}
    labels = []
    if state["preparation"]["eligible"]:
        labels.append(
            {
                "kind": "order",
                "reference": data["reference"],
                "payload": encode_label("order", data["reference"]),
                "text": f"{len(data['cards'])} active physical cards",
            }
        )
        for card in data["cards"]:
            entry = entries.get(str(card["entry_id"]))
            if not entry:
                raise HTTPException(409, "label_mapping_inconsistent")
            labels.append(
                {
                    "kind": "physical_card",
                    "reference": card["reference"],
                    "payload": encode_label("physical_card", card["reference"]),
                    "text": "\n".join(
                        (
                            str(entry.get("card_name") or ""),
                            str(entry.get("expansion") or ""),
                            " / ".join(
                                str(entry.get(k) or "")
                                for k in ("card_number", "language")
                            ),
                        )
                    ),
                }
            )
    reasons = list(state["preparation"]["reasons"])
    binding = state["binding"]
    if binding:
        if not binding["local_order_id"]:
            reasons.append("production_binding_unconfirmed")
        elif set(binding["cards"]) != {str(card["id"]) for card in data["cards"]}:
            reasons.append("production_mapping_inconsistent")
    for check in state["inspection"].values():
        reasons.extend(r["code"] for r in check["reasons"])
    events = list(
        db.scalars(
            select(IntakeAudit)
            .where(
                IntakeAudit.submission_id == item.id, IntakeAudit.action.like("label_%")
            )
            .order_by(IntakeAudit.created_at, IntakeAudit.id)
        )
    )
    return {
        "reference": data["reference"],
        "actor": str(actor.id),
        "labels": labels,
        "print_eligible": bool(labels) and not reasons,
        "blockers": sorted(set(reasons)),
        "history": [
            {
                "id": str(e.entity_id),
                "action": e.action,
                "actor": str(e.actor_id),
                "timestamp": e.created_at,
                "data": e.data,
                "reason": e.reason,
            }
            for e in events
        ],
    }


@router.get("/submissions/{sid}/labels")
def label_view(
    sid: UUID, request: Request, db: Db, settings: Config, provider: Commerce
):
    actor = staff(request, db, settings)
    return manifest(db, submission(db, sid), actor, provider)


class LabelEvent(Payload):
    job_id: UUID
    phase: Literal["rendered", "claimed", "submitted", "failed", "verified"]
    references: list[
        Annotated[str, Field(pattern=r"^(?:SP|PC)-[0-9A-F]{32}$", max_length=35)]
    ] = Field(min_length=1, max_length=250)
    printer: str = Field(min_length=1, max_length=250)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(default="", max_length=1000)
    error: str = Field(default="", max_length=1000)
    width_mm: Literal[50] = 50
    height_mm: Literal[30] = 30


@router.post("/submissions/{sid}/labels/events")
def label_event(
    sid: UUID,
    payload: LabelEvent,
    request: Request,
    db: Db,
    settings: Config,
    provider: Commerce,
):
    actor = staff(request, db, settings)
    item = submission(
        db, sid
    )  # Shared row lock serializes job claims, void and custody.
    state = manifest(db, item, actor, provider)
    previous = [e for e in state["history"] if e["id"] == str(payload.job_id)]
    data = {
        "references": payload.references,
        "printer": payload.printer,
        "width_mm": 50,
        "height_mm": 30,
        "fingerprint": payload.fingerprint,
    }
    if len(set(payload.references)) != len(payload.references):
        raise HTTPException(422, "duplicate_label_selection")
    if previous:
        first = previous[0]
        if first["actor"] != str(actor.id) or any(
            first["data"].get(k) != v for k, v in data.items()
        ):
            raise HTTPException(409, "label_job_conflict")
    phase = "label_" + payload.phase
    if any(e["action"] == phase for e in previous):
        # A replay NEVER grants a second spooler submission.
        return {"accepted": False, "phase": payload.phase}
    if payload.phase in ("rendered", "claimed") or not previous:
        available = {l["reference"] for l in state["labels"]}
        if not set(payload.references) <= available:
            raise HTTPException(409, "label_selection_stale")
        chosen = {l["reference"]: l for l in state["labels"]}
        current = [chosen[r] for r in payload.references]
        fingerprint = hashlib.sha256(
            json.dumps(current, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        if fingerprint != payload.fingerprint:
            raise HTTPException(409, "label_content_stale")
    if payload.phase == "claimed":
        if not state["print_eligible"]:
            raise HTTPException(409, "label_not_eligible")
        old = [
            e
            for e in state["history"]
            if e["action"] == "label_claimed"
            and e["id"] != str(payload.job_id)
            and set(e["data"]["references"]) & set(payload.references)
        ]
        if old and not payload.reason.strip():
            raise HTTPException(422, "reprint_reason_required")
    allowed = {
        "rendered": set(),
        "claimed": {"label_rendered"},
        "submitted": {"label_claimed"},
        "failed": set(),
        "verified": {"label_submitted"},
    }
    actions = {e["action"] for e in previous}
    if allowed[payload.phase] and not actions & allowed[payload.phase]:
        raise HTTPException(409, "label_phase_conflict")
    if actions & {"label_failed", "label_verified"} or (
        payload.phase == "failed" and "label_submitted" in actions
    ):
        raise HTTPException(409, "label_job_terminal")
    data.update(
        error=payload.error,
        label_types=[
            "order" if r.startswith("SP-") else "physical_card"
            for r in payload.references
        ],
    )
    audit(db, actor, sid, phase, payload.job_id, data, payload.reason or None)
    db.commit()
    return {"accepted": True, "phase": payload.phase}
