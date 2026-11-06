# SELBY identification QR contract — version 1

The reserved `SP` namespace is SELBY's existing historical SPECTRA physical-identification namespace. Retain it for scanner compatibility; branding on these labels is SELBY. Do not introduce a competing QR identity or replace existing PC payloads.

| Entity | Exact payload | Canonical reference |
| --- | --- | --- |
| Order bag | `SP:ORDER:1:SP-<32 uppercase hexadecimal digits>` | Existing submission SP reference |
| Physical card | `SP:PC:1:PC-<32 uppercase hexadecimal digits>` | Existing physical-card PC reference |

Example: `SP:PC:1:PC-22222222222222222222222222222222` identifies that exact physical copy, even if another card has identical metadata. `SP:ORDER:1:SP-11111111111111111111111111111111` identifies the existing order. The complete payload contains only namespace, entity type, explicit version and canonical identity. It contains no customer PII, credentials, URL, grading result, certification number, local ORD/SLB-C or mutable display text. The hexadecimal portion is the existing opaque reference; the printer allocates nothing.

`encode_label(kind, reference)` and `decode_label(payload)` in `backend/app/physical_identity.py` are the shared order/card codec. Accepted kinds: `order`, `physical_card`. The decoder returns `(kind, reference)` and strictly rejects unsupported versions/namespaces, lowercase, whitespace, extra delimiters, invalid lengths and trailing data. Legacy `qr_payload` and `parse_scan` remain unchanged for existing PC integrations; the latter still accepts its documented raw-reference/normalized input behavior. Scanner adapters may remove a configured transport line terminator before passing the exact payload to the strict decoder. Do not silently accept arbitrary URLs or infer entity type from a label's card name.

For TD-W6 integration, decode first, then perform authenticated authoritative lookup of the complete reference. The QR is an identifier, never authorization or proof of active lifecycle. A previously issued physical label may outlive a void or custody change; scanner workflows must recheck current backend state and parent order. Unknown versions must produce an explicit unsupported-payload result rather than guessing. QR generation uses standard QR Model 2, error correction Q and at least four white quiet-zone modules; thermal rendering uses integer modules (four dots at 203 DPI for these v1 payloads).

Automated tests roundtrip both kinds, preserve legacy PC compatibility, and independently decode the rendered bitmaps using OpenCV. A printed-label scan is still required for hardware acceptance.
