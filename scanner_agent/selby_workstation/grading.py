"""Draft deterministic grading; operator decisions never grant production acceptance."""

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from spectra_scanner.common import utc_now
from spectra_scanner.storage import sha256_file

from .condition import CATEGORIES, category_status, current_findings
from .inspection import measure

POLICY_PATH = Path(__file__).parent / "policies/selby-draft-0.4.0.json"
AUTHORIZATION_PATH = Path(__file__).parent / "override_authorization.json"
FACES = ("front", "back")
SUBGRADES = ("centering", *CATEGORIES)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def half(value, low=1, high=10):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("A numeric half-point value is required")
    if not math.isfinite(value) or not low <= value <= high or value * 2 != int(value * 2):
        raise ValueError(f"Value must be {low}–{high} in half points")
    return float(value)


def validate_policy(policy):
    if not policy.get("id") or not policy.get("version") or policy.get("draft") is not True:
        raise ValueError("A versioned draft policy is required")
    if (
        policy.get("back_centering_thresholds") is not None
        or policy.get("centering_consolidation") != "minimum"
        or policy.get("condition_consolidation") != "sum_penalties_across_faces"
    ):
        raise ValueError("Unsupported consolidation/back centering rules")
    half(policy["condition_baseline"])
    half(policy["weakest_plus"], 0, 9)
    previous_score, previous_limit = 11, 49
    for score, limit in policy["front_centering_thresholds"]:
        half(score)
        if not previous_score > score or not previous_limit < limit <= 100:
            raise ValueError("Centering thresholds must descend in score and ascend in imbalance")
        previous_score, previous_limit = score, limit
    if not policy["front_centering_thresholds"]:
        raise ValueError("Missing front centering rules")
    for cap in policy["structural_caps"].values():
        if type(cap) is not int or not 1 <= cap <= 10:
            raise ValueError("Structural caps must be integer grades")


def actor(session, notes):
    if not session.data["operator"].strip() or not notes.strip():
        raise ValueError("Operator identity and a specific explanation are required")
    return session.data["operator"]


def initialize(session, card_id, policy=None):
    actor(session, card_id)
    if "grading" in session.data:
        existing = session.data["grading"]
        if existing["working"]:
            raise ValueError("A grading dossier already exists in this session")
        existing["working"] = dict(card_id=card_id, faces={}, penalties={}, centering_reviews={})
        audit(session, "restart_after_undo", card_id)
        return
    policy = deepcopy(policy or json.loads(POLICY_PATH.read_text(encoding="utf-8")))
    validate_policy(policy)
    session.data["grading"] = dict(
        schema_version=1,
        policy=policy,
        policy_sha256=digest(policy),
        working=dict(card_id=card_id, faces={}, penalties={}, centering_reviews={}),
        events=[],
        overrides=[],
        decisions=[],
    )
    audit(session, "initialize", card_id)


def audit(session, action, notes):
    g = session.data["grading"]
    record = dict(
        id=str(uuid4()),
        action=action,
        notes=notes,
        operator=actor(session, notes),
        at_utc=utc_now(),
        policy_version=g["policy"]["version"],
        working=deepcopy(g["working"]),
        overrides=deepcopy(g["overrides"]),
        decisions=deepcopy(g["decisions"]),
        previous=g["events"][-1]["sha256"] if g["events"] else None,
    )
    record["sha256"] = digest(record)
    g["events"].append(record)


def inspection_snapshot(session):
    keys = (
        "session_id",
        "coordinate_system",
        "image",
        "image_encoding",
        "sources",
        "prediction_exposure",
        "operator",
        "inspection_face",
        "physical",
        "printed",
        "boundary_validation",
        "condition",
        "review_status",
        "automatic_acceptance",
    )
    return {k: deepcopy(session.data[k]) for k in keys if k in session.data}


def view(snapshot):
    return SimpleNamespace(
        data=snapshot, identity={k: snapshot["image"][k] for k in ("sha256", "dimensions", "mode")}
    )


def decision_digest(snapshot):
    # Viewer exposure is retained as provenance but is not an edited inspection decision.
    return digest({k: v for k, v in snapshot.items() if k != "prediction_exposure"})


def attach_face(session, source, notes):
    actor(session, notes)
    source.validate()
    face = source.data.get("inspection_face")
    if face not in FACES:
        raise ValueError("Label the inspection front or back before attaching it")
    g = session.data["grading"]
    snapshot = inspection_snapshot(source)
    other = g["working"].get("faces", {}).get("back" if face == "front" else "front")
    if other and other["inspection"]["image"]["sha256"] == snapshot["image"]["sha256"]:
        raise ValueError("Front and back must be different original images")
    record = dict(
        inspection=snapshot,
        inspection_sha256=digest(snapshot),
        saved_path=str(source.saved_path) if source.saved_path else None,
        saved_sha256=source.saved_sha,
    )
    g["working"].setdefault("faces", {})[face] = record
    audit(session, "attach_" + face, notes)


def findings(grading):
    output = {}
    for face, record in grading["working"].get("faces", {}).items():
        s = view(record["inspection"])
        for category in CATEGORIES:
            for finding in current_findings(s, category):
                output[face + ":" + finding["id"]] = dict(face=face, **finding)
    return output


def set_penalty(session, key, severity, warranted, penalty, notes, damage_id, structural_type=None):
    actor(session, notes)
    g = session.data["grading"]
    finding = findings(g)[key]
    half(penalty, 0, 9)
    if type(severity) is not int or not 0 <= severity <= 5 or type(warranted) is not bool:
        raise ValueError("Severity must be an integer 0–5; penalty decision must be explicit")
    if not damage_id.strip():
        raise ValueError("A physical damage group is required to prevent double counting")
    if structural_type is not None and structural_type not in g["policy"]["structural_caps"]:
        raise ValueError("Unknown structural damage type")
    if (penalty and not warranted) or (
        finding["decision"] != "confirmed" and (penalty or structural_type)
    ):
        raise ValueError("Only confirmed findings can carry penalties or structural caps")
    if finding["decision"] == "unreviewed":
        raise ValueError("Review the finding in Condition inspection first")
    g["working"].setdefault("penalties", {})[key] = dict(
        finding_sha256=digest(finding),
        severity=severity,
        warranted=warranted,
        penalty=float(penalty),
        notes=notes,
        damage_id=damage_id.strip(),
        structural_type=structural_type,
        operator=session.data["operator"],
        at_utc=utc_now(),
    )
    audit(session, "penalty_decision", notes)


def set_centering_review(session, face, score, notes):
    actor(session, notes)
    half(score)
    record = session.data["grading"]["working"]["faces"][face]
    proposed, _, _ = centering_proposal(record["inspection"], session.data["grading"]["policy"])
    if proposed is not None and score != proposed:
        raise ValueError("Validated front geometry resolves the draft score; use an authorized grade override for exceptions")
    session.data["grading"]["working"].setdefault("centering_reviews", {})[face] = dict(
        score=float(score),
        notes=notes,
        operator=session.data["operator"],
        at_utc=utc_now(),
        inspection_sha256=record["inspection_sha256"],
    )
    audit(session, "centering_review_" + face, notes)


def centering_proposal(snapshot, policy):
    measurements = measure(view(snapshot))
    if measurements["status"] != "human_geometry_validated":
        return None, measurements, "Centering geometry is incomplete, uncertain or unvalidated"
    if snapshot["inspection_face"] != "front":
        return None, measurements, "No back-side thresholds: explicit operator score required"
    c = measurements["centering_percent"]
    values = [c[k] for k in ("left", "right", "top", "bottom")]
    if (
        not all(math.isfinite(v) and 0 <= v <= 100 for v in values)
        or abs(c["left"] + c["right"] - 100) > 1e-6
        or abs(c["top"] + c["bottom"] - 100) > 1e-6
    ):
        return None, measurements, "Measurements incompatible with draft thresholds"
    worst = max(values)
    for score, limit in policy["front_centering_thresholds"]:
        if worst <= limit + 1e-9:
            return float(score), measurements, None
    return None, measurements, "Outside front draft threshold coverage; operator review required"


def calculate(subgrades, caps, policy):
    for name in SUBGRADES:
        half(subgrades[name])
    mean = sum(subgrades.values()) / 4
    ceiling = min(subgrades.values()) + policy["weakest_plus"]
    cap = min((c["maximum"] for c in caps), default=10)
    grade = max(1, min(10, math.floor(min(mean, ceiling, cap))))
    explanation = (
        f"Mean {mean:g}; weakest + {policy['weakest_plus']:g} ceiling {ceiling:g}; "
        f"structural ceiling {cap}; floor(min(...)) bounded 1–10 = {grade}."
    )
    return dict(
        subgrades=subgrades,
        mean=mean,
        weakest_ceiling=ceiling,
        applicable_caps=caps,
        calculated_grade=grade,
        explanation=explanation,
    )


def evaluate(session):
    g = session.data.get("grading")
    if not g:
        return dict(state="Draft", calculated_grade=None, warnings=["Create a card dossier"])
    w, policy = g["working"], g["policy"]
    token = digest(dict(working=w, policy_sha256=g["policy_sha256"]))
    warnings, unresolved, completion, centering, sources = [], [], {}, {}, {}
    if not w.get("card_id", "").strip():
        unresolved.append("Card identity missing")
    for face in FACES:
        record = w.get("faces", {}).get(face)
        if not record:
            unresolved.append(face + " inspection missing")
            completion[face] = "missing"
            continue
        s = record["inspection"]
        sources[face] = deepcopy(s["sources"])
        warnings.extend(
            f"{face} upstream {item['kind']}: {item['status']} (unchanged)" for item in s["sources"]
        )
        statuses = {c: category_status(view(s), c) for c in CATEGORIES}
        completion[face] = statuses
        if any(status != "operator_reviewed" for status in statuses.values()):
            unresolved.append(face + " condition review incomplete")
        if (
            s["session_id"] == session.data["session_id"]
            and decision_digest(inspection_snapshot(session)) != decision_digest(s)
        ):
            unresolved.append(face + " inspection changed: attach current revision again")
        score, measurement, warning = centering_proposal(s, policy)
        rule_proposal = score
        review = w.get("centering_reviews", {}).get(face)
        if review and review["inspection_sha256"] == record["inspection_sha256"]:
            score = review["score"]
            warnings.append(face + " centering explicitly assigned by operator: " + review["notes"])
        if warning:
            warnings.append(face + ": " + warning)
        if score is None:
            unresolved.append(face + " centering unresolved")
        centering[face] = dict(rule_proposal=rule_proposal, score=score,
                               measurements=measurement, operator_review=review)
    current = findings(g)
    penalties = w.get("penalties", {})
    totals = dict.fromkeys(CATEGORIES, 0.0)
    groups, caps = {}, []
    for key, finding in current.items():
        entry = penalties.get(key)
        if finding["decision"] == "unreviewed":
            unresolved.append(key + " finding unreviewed")
        if finding["decision"] == "confirmed" and not entry:
            unresolved.append(
                key + " confirmed finding requires an explicit penalty/cap decision (default zero)"
            )
        if not entry:
            continue
        if entry["finding_sha256"] != digest(finding):
            unresolved.append(key + " finding changed: revise penalty decision")
            continue
        if finding["decision"] != "confirmed":
            continue
        if entry["penalty"] or entry["structural_type"]:
            group = entry["damage_id"]
            if group in groups:
                unresolved.append(
                    "Double counting physical damage " + group + ": choose one primary finding"
                )
                continue
            groups[group] = key
        totals[finding["category"]] += entry["penalty"]
        kind = entry["structural_type"]
        if kind:
            caps.append(
                dict(
                    type=kind,
                    maximum=policy["structural_caps"][kind],
                    finding=key,
                    damage_id=entry["damage_id"],
                )
            )
    warnings += [
        "Draft policy; human validation is not commercial certification.",
        "Upstream review/blocked statuses remain unchanged; no release authorization.",
    ]
    result = dict(
        state="Incomplete" if w.get("faces") else "Draft",
        input_sha256=token,
        policy_id=policy["id"],
        policy_version=policy["version"],
        completion=completion,
        centering=centering,
        penalty_totals=totals,
        calculated_grade=None,
        final_grade=None,
        warnings=warnings,
        unresolved=unresolved,
        applicable_caps=caps,
        subgrades=dict.fromkeys(SUBGRADES),
        source_provenance=sources,
        commercial_release_authorized=False,
        automatic_acceptance=False,
    )
    if unresolved:
        return result
    subgrades = dict(
        centering=min(v["score"] for v in centering.values()),
        **{c: max(1.0, policy["condition_baseline"] - totals[c]) for c in CATEGORIES},
    )
    result.update(calculate(subgrades, caps, policy), state="Ready for operator review")
    applicable = [o for o in g["overrides"] if o["input_sha256"] == token]
    result["override"] = deepcopy(applicable[-1]) if applicable else None
    result["proposed_grade"] = (
        applicable[-1]["new_grade"] if applicable else result["calculated_grade"]
    )
    valid = [
        d
        for d in g["decisions"]
        if d["input_sha256"] == token
        and d["override_id"] == (applicable[-1]["id"] if applicable else None)
    ]
    if not g["events"] or g["events"][-1]["action"] != "human_validate":
        valid = []
    if valid:
        result.update(
            state="Human validated",
            final_grade=valid[-1]["final_grade"],
            operator_decision=deepcopy(valid[-1]),
        )
    return result


def record_override(session, grade, scope, notes):
    operator = actor(session, notes)
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    if operator not in authorization["authorized_operators"]:
        raise ValueError("Operator is not in the local override authorization allowlist")
    result = evaluate(session)
    if result["calculated_grade"] is None:
        raise ValueError("Incomplete grading cannot be overridden")
    if type(grade) is not int or not 1 <= grade <= 10 or scope not in ("grade", "structural_caps"):
        raise ValueError("Override requires integer 1–10 and explicit scope")
    if scope == "structural_caps" and (
        not result["applicable_caps"]
        or grade > math.floor(min(result["mean"], result["weakest_ceiling"], 10))
    ):
        raise ValueError("Cap-only override cannot bypass the mean/weakest ceiling")
    g = session.data["grading"]
    g["overrides"].append(
        dict(
            id=str(uuid4()),
            operator=operator,
            at_utc=utc_now(),
            original_calculated_grade=result["calculated_grade"],
            new_grade=grade,
            scope=scope,
            justification=notes,
            policy_id=g["policy"]["id"],
            policy_version=g["policy"]["version"],
            input_sha256=result["input_sha256"],
            applicable_caps=result["applicable_caps"],
            authorization_sha256=digest(authorization),
        )
    )
    audit(session, "override", notes)


def human_validate(session, notes, same_card_and_no_double_count=False):
    actor(session, notes)
    if not same_card_and_no_double_count:
        raise ValueError("Explicitly attest same-card pairing and physical damage deduplication")
    validate_grading(session, verify_evidence=True)
    result = evaluate(session)
    if result["calculated_grade"] is None:
        raise ValueError("Resolve missing inspections and decisions before validation")
    g = session.data["grading"]
    g["decisions"].append(
        dict(
            id=str(uuid4()),
            operator=session.data["operator"],
            at_utc=utc_now(),
            notes=notes,
            same_card_and_no_double_count=True,
            input_sha256=result["input_sha256"],
            original_calculated_grade=result["calculated_grade"],
            final_grade=result["proposed_grade"],
            override_id=result["override"]["id"] if result["override"] else None,
            policy_id=g["policy"]["id"],
            policy_version=g["policy"]["version"],
            result=deepcopy(result),
        )
    )
    audit(session, "human_validate", notes)


def validate_grading(session, verify_evidence=True):
    g = session.data.get("grading")
    if g is None:
        return
    if g.get("schema_version") != 1 or digest(g["policy"]) != g["policy_sha256"]:
        raise ValueError("Invalid grading schema/policy provenance")
    validate_policy(g["policy"])
    previous = None
    for event in g["events"]:
        value = {k: v for k, v in event.items() if k != "sha256"}
        if (
            digest(value) != event["sha256"]
            or event["previous"] != previous
            or not event["operator"].strip()
            or not event["notes"].strip()
        ):
            raise ValueError("Grading action history mismatch")
        previous = event["sha256"]
    if not g["events"] or any(
        g[name] != g["events"][-1][name] for name in ("working", "overrides", "decisions")
    ):
        raise ValueError("Grading state differs from its recorded action history")
    for face, record in g["working"].get("faces", {}).items():
        s = record["inspection"]
        if (
            face not in FACES
            or s["inspection_face"] != face
            or digest(s) != record["inspection_sha256"]
            or s["review_status"] != "review_required"
            or s["automatic_acceptance"] is not False
        ):
            raise ValueError("Grading face provenance/gate mismatch")
        if verify_evidence:
            from .session import Session

            if record["saved_path"]:
                if sha256_file(Path(record["saved_path"])) != record["saved_sha256"]:
                    raise ValueError("Attached session version changed")
            evidence = Session(Path(s["image"]["path"]))
            for source in s["sources"]:
                evidence.load_report(Path(source["path"]))
            if (
                evidence.identity != {k: s["image"][k] for k in evidence.identity}
                or evidence.data["sources"] != s["sources"]
            ):
                raise ValueError("Attached face evidence changed")
            evidence.data.update(deepcopy(s))
            evidence.validate()
    for entry in g["working"].get("penalties", {}).values():
        half(entry["penalty"], 0, 9)
        if (
            type(entry["severity"]) is not int
            or not 0 <= entry["severity"] <= 5
            or not entry["notes"].strip()
            or not entry["operator"].strip()
            or (entry["penalty"] and not entry["warranted"])
        ):
            raise ValueError("Invalid operator penalty decision")
    for review in g["working"].get("centering_reviews", {}).values():
        half(review["score"])
        if not review["notes"].strip() or not review["operator"].strip():
            raise ValueError("Invalid centering review")
