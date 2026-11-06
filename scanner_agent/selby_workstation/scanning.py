"""Read-only scan resolution against the existing immutable production bridge."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .calibration import DIAGNOSTIC_PAYLOAD, decode_diagnostic
from .incoming import PreviewError
from .label_mapping import mapped_orders

# Load the existing dependency-free contract, without importing the backend app.
_spec = spec_from_file_location(
    "selby_label_contract", Path(__file__).resolve().parents[2] / "backend/app/physical_identity.py"
)
_codec = module_from_spec(_spec)
_spec.loader.exec_module(_codec)
decode_label = _codec.decode_label


def identify(payload):
    if payload == DIAGNOSTIC_PAYLOAD:
        return "diagnostic", decode_diagnostic(payload)
    try:
        return decode_label(payload)
    except (ValueError, TypeError, AttributeError):
        raise PreviewError(
            "Invalid, truncated or unsupported QR payload. Scan the complete SELBY label."
        ) from None


def resolve(path, payload, client):
    kind, reference = identify(payload)
    if kind == "diagnostic":
        return dict(kind=kind, reference=reference)
    matches = []
    for context in mapped_orders(path):
        if kind == "order" and context["sp"] == reference:
            matches.append((context, None))
        elif kind == "physical_card":
            matches.extend((context, c) for c in context["cards"] if c["pc"] == reference)
    if len(matches) != 1:
        raise PreviewError(
            "Unknown, unmapped or conflicting identity in this registry. No identities were created."
        )
    context, card = matches[0]
    if not context["confirmed"] or context["scope"] != client.connection.backend_origin:
        raise PreviewError(
            "Unconfirmed mapping or wrong backend origin. Open the original registry and connection."
        )
    snapshot = client.production(context["sid"])
    data, binding = snapshot["submission"], snapshot["binding"]
    pairs = {c["pc_id"]: c["card_id"] for c in context["cards"]}
    refs = {c["pc_id"]: c["pc"] for c in context["cards"]}
    active = {str(c["id"]): c["reference"] for c in data["cards"] if c["status"] != "voided"}
    if (
        snapshot["actor"]["role"] not in ("operator", "admin")
        or str(data["id"]) != context["sid"]
        or data["reference"] != context["sp"]
        or not binding
        or str(binding["registry_id"]) != context["registry_id"]
        or binding["local_order_id"] != context["order_id"]
        or binding["cards"] != pairs
        or active != refs
    ):
        raise PreviewError(
            "Voided card or local/backend mapping conflict. Restore or review the original registry."
        )
    if context not in mapped_orders(path):
        raise PreviewError("Registry mapping changed during lookup. Scan again.")
    result = dict(kind=kind, reference=reference, context=context, card=card)
    if card:
        result["eligibility"] = snapshot["inspection"][card["pc_id"]]
    return result
