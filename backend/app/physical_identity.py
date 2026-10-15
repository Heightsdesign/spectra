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
    if value.startswith(QR_PREFIX):
        value = value[len(QR_PREFIX):]
    return normalize_reference(value)
