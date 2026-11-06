"""Allowlisted custody writes using existing session and CSRF contracts."""

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from .desktop_auth import AuthTransport
from .incoming import NoRedirect, PreviewClient, PreviewError


class IntakeClient:
    def __init__(self, connection, credential, timeout=12):
        self.connection, self.credential, self.timeout = connection, credential, timeout
        self.reader = PreviewClient(
            connection.backend_origin, credential.token, credential.cookie_name, timeout
        )

    def load(self, sid):
        return self.reader.staff(), self.reader.submission(sid)

    def production(self, sid):
        return self.reader._get(f"/internal/intake/submissions/{UUID(sid)}/production")

    def labels(self, sid):
        return self.reader._get(f"/internal/intake/submissions/{UUID(sid)}/labels")

    @staticmethod
    def route(operation):
        kind = operation["kind"]
        sid = str(UUID(operation["sid"]))
        suffix = {
            "parcel": "parcels",
            "card": "cards",
            "transition": "transition",
            "issue": "discrepancies",
            "production_reserve": "production/reserve",
            "production_confirm": "production/confirm",
            "label_event": "labels/events",
        }.get(kind)
        if kind in ("match", "resolve", "void"):
            target = str(UUID(operation["target"]))
            suffix = (
                f"cards/{target}/{kind}"
                if kind in ("match", "void")
                else f"discrepancies/{target}/resolve"
            )
        if suffix is None:
            raise PreviewError("Unsupported physical intake operation.")
        return f"/internal/intake/submissions/{sid}/{suffix}"

    def execute(self, operation):
        path = self.route(operation)
        credential = self.credential
        if credential.pending_revocation or credential.expires_at <= time.time():
            raise PreviewError(
                "Session expired. Sign in again; pending intake request was preserved.",
                disconnect=True,
                kind="expired",
            )
        csrf = (
            AuthTransport(self.connection, self.timeout)
            .request("/api/auth/csrf", credential=credential)
            .get("csrf_token")
        )
        if not isinstance(csrf, str) or not re.fullmatch("[a-f0-9]{64}", csrf):
            raise PreviewError("Invalid CSRF response. No intake request sent.")
        request = Request(
            self.connection.backend_origin + path,
            method="POST",
            data=json.dumps(operation["payload"], allow_nan=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "Origin": self.connection.auth_origin,
                "X-Spectra-Client": "1",
                "X-CSRF-Token": csrf,
                "Cookie": f"{credential.cookie_name}={credential.token}",
            },
        )
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                request, timeout=self.timeout
            ) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if response.status not in (200, 201) or len(raw) > 8 * 1024 * 1024:
                    raise ValueError()
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
            # Creations return identity only; use the same key again if this read fails.
            if operation["kind"] == "label_event":
                return result
            if operation["kind"].startswith("production_"):
                return self.production(operation["sid"])
            return self.reader.submission(operation["sid"])
        except HTTPError as exc:
            messages = {
                401: "Session expired. Sign in again.",
                403: "Permission denied or security check failed.",
                404: "Submission or selected intake record is unavailable.",
                422: "Invalid intake fields. Review the selected records and required observations.",
            }
            if operation['kind'] == 'label_event':
                messages[422] = 'Invalid label request. Verify dimensions, selected references and the mandatory reprint reason.'
            if exc.code == 409:
                # Only display known server codes, never arbitrary response bodies/PII.
                try:
                    code = json.loads(exc.read(65536)).get("detail")
                except (ValueError, AttributeError):
                    code = None
                if isinstance(code, dict) and code.get("code") == "void_not_permitted":
                    code = "void_not_permitted"
                messages[409] = {
                    "operational_override_required": "Administrator custody authorization required before beginning reconciliation. This is not payment clearance.",
                    "begin_reconciliation_required": "Begin reconciliation before registering or matching physical cards.",
                    "declared_quantity_exceeded": "Declared quantity already matched. Register extra cards as discrepancies.",
                    "open_discrepancies": "Resolve or explicitly acknowledge all open discrepancies before completion.",
                    "quantity_unreconciled": "Missing quantities remain. Verify physical cards and documented missing exceptions.",
                    "unidentified_card": "Unidentified cards require explicit matching or an acknowledged discrepancy.",
                    "invalid_transition": "The backend state does not permit this action. Refresh the intake.",
                    "idempotency_conflict": "Request key conflict. Review backend records; do not create another receipt.",
                    "discrepancy_closed": "This discrepancy has already been closed. Refresh the intake.",
                    "card_voided": "This PC is VOIDED and cannot be used as an active physical card.",
                    "void_not_permitted": "Void rejected: the PC must be unidentified during reconciliation, with no match/custody history, discrepancies, production reservation, inspection or grading link. Refresh and review its history.",
                    "production_owned_by_other_registry": "Submission belongs to another registry. Reopen the original registry; do not allocate new IDs.",
                    "production_mode_conflict": "A different preparation mode is reserved. Review the existing reservation.",
                    "production_mapping_conflict": "Production identities conflict. Restore or review the recorded mapping; no links were replaced.",
                    "production_not_eligible": "Production preparation is blocked. Refresh and review reconciliation and card eligibility.",
                    "production_manifest_changed": "Physical inventory changed. Review the pending mapping; no replacement IDs were allocated.",
                    "production_reservation_required": "Production reservation is missing. Retry preparation with the original registry.",
                    "label_not_eligible": "Printing blocked by current backend reconciliation, payment or inspection eligibility. Refresh and review the blockers.",
                    "label_selection_stale": "Label selection is stale or belongs to another order. Refresh and select the exact active identities.",
                    "label_content_stale": "Label text or active-card count changed. Refresh and preview the current label before printing.",
                    "label_job_conflict": "The recorded print job has different details. Inspect its history and the Windows queue; do not resubmit it.",
                    "label_phase_conflict": "Print history does not permit this transition. Inspect the recorded job and queue.",
                    "label_job_terminal": "This print attempt is closed. Inspect its history before an explicit reprint with a reason.",
                }.get(
                    code if isinstance(code, str) else "",
                    "Intake state conflict. Refresh and review the backend audit.",
                )
            raise PreviewError(
                messages.get(
                    exc.code,
                    "Intake service failed. The outcome may be unknown; pending request was preserved.",
                ),
                disconnect=exc.code in (401, 403),
                kind="expired"
                if exc.code == 401
                else "permission"
                if exc.code == 403
                else "server",
            ) from None
        except (URLError, OSError, TimeoutError):
            if operation['kind'] == 'label_event':
                raise PreviewError('Label audit response is uncertain. Refresh history and inspect the Windows queue before any reprint. Never automatically resubmit.', kind='offline') from None
            raise PreviewError(
                "Offline or TLS failure. Receipt outcome may be unknown. Refresh and use the preserved request; do not register the same object again.",
                kind="offline",
            ) from None
        except (ValueError, UnicodeError):
            raise PreviewError(
                "Invalid intake response. Outcome may be unknown; pending request was preserved."
            ) from None
