"""Versioned scanner payloads contain only the complete opaque physical identity."""
import re

QR_PREFIX = 'SP:PC:1:'


def normalize_reference(value):
    value = value.strip(' \r\n\t').upper()
    if not re.fullmatch(r'PC-[0-9A-F]{32}', value):
        raise ValueError('invalid_card_reference')
    return value


def qr_payload(reference):
    return QR_PREFIX + normalize_reference(reference)


def parse_scan(value):
    value = value.strip(' \r\n\t').upper()
    value = value.removeprefix(QR_PREFIX)
    return normalize_reference(value)


def encode_label(kind, reference):
    prefix = {'order': 'SP-', 'physical_card': 'PC-'}.get(kind)
    if prefix is None or not re.fullmatch(prefix + r'[0-9A-F]{32}', reference):
        raise ValueError('invalid_label_identity')
    return ('SP:ORDER:1:' if kind == 'order' else QR_PREFIX) + reference


def decode_label(payload):
    for kind, prefix in (('order', 'SP:ORDER:1:'), ('physical_card', QR_PREFIX)):
        if payload.startswith(prefix):
            reference = payload[len(prefix):]
            if encode_label(kind, reference) == payload:
                return kind, reference
    raise ValueError('unsupported_label_payload')
