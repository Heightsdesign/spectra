"""Deterministic, read-only thermal PDFs. A PDF is not evidence of a physical print."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import threading
import time
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
import reportlab
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
import segno
from sqlalchemy import select

from app.auth import write_guard
from app.cards import Db
from app.customer_operations import require_staff
from app.intake_models import Parcel, PhysicalCard
from app.submission_models import Submission, SubmissionEntry
from app.physical_identity import normalize_reference, qr_payload

MAX_BATCH = 250
MAX_PDF_BYTES = 8 * 1024 * 1024
GENERATION_SECONDS = 15
PROFILE_SIZES = {'50x30': (50, 30), '70x40': (70, 40)}
Profile = Literal['50x30', '70x40']
_slots = threading.BoundedSemaphore(2)
# Bundled, licensed font: no system font discovery or user-supplied paths.
_font = TTFont('SpectraLabel', str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'))
pdfmetrics.registerFont(_font)


def qr_symbol(reference):
    return segno.make_qr(qr_payload(reference), version=3, error='q', mode='alphanumeric', boost_error=False)


@dataclass(frozen=True)
class LabelRecord:
    reference: str
    submission_reference: str
    card_name: str = ''
    card_number: str = ''
    language: str = ''


def printable(value):
    text = ' '.join(unicodedata.normalize('NFC', value).split())
    # Unsupported glyphs are explicit, not invisible .notdef boxes. Full identity is in QR/lookup.
    return ''.join(c if ord(c) in _font.face.charToGlyph else '?' for c in text if unicodedata.category(c) != 'Cf')


def fit_text(value, width, size, font='SpectraLabel'):
    value = printable(value)
    if pdfmetrics.stringWidth(value, font, size) <= width:
        return value
    while value and pdfmetrics.stringWidth(value + '...', font, size) > width:
        value = value[:-1]
    return value + '...'


def draw_qr(pdf, reference, x, y, module_mm):
    matrix = list(qr_symbol(reference).matrix_iter(border=4))
    unit = module_mm * mm
    # Horizontal runs reduce PDF commands. Four white modules surround all dark pixels.
    pdf.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(matrix):
        start = None
        for index in range(len(row) + 1):
            dark = index < len(row) and row[index]
            if dark and start is None:
                start = index
            elif not dark and start is not None:
                pdf.rect(x + start * unit, y + (len(matrix) - row_index - 1) * unit,
                         (index - start) * unit, unit, fill=1, stroke=0)
                start = None


def new_pdf(buffer, size):
    pdf = canvas.Canvas(buffer, pagesize=tuple(v * mm for v in size), pageCompression=1, invariant=1)
    pdf.setTitle('SPECTRA physical card labels')
    pdf.setAuthor('SPECTRA')
    pdf.setSubject('Internal physical-card identification')
    pdf.setCreator('SPECTRA')
    pdf.setKeywords('')
    pdf.setViewerPreference('PrintScaling', 'None')
    return pdf


def draw_label(pdf, record, profile):
    width, height = PROFILE_SIZES[profile]
    # Four dots/module at the target's documented 203 DPI, vector output at exact physical size.
    module = 4 * 25.4 / 203 if profile == '50x30' else 5 * 25.4 / 203
    qr_size = 37 * module
    draw_qr(pdf, record.reference, 2 * mm, 8 * mm, module)
    right = (3 + qr_size) * mm
    available = (width - 2) * mm - right
    pdf.setFont('Helvetica-Bold', 9)
    pdf.drawString(right, (height - 5) * mm, 'SPECTRA')
    pdf.setFont('SpectraLabel', 6.5)
    name = printable(record.card_name) or 'Unidentified'
    # Fixed, independently bounded lines; names never enter the QR quiet zone.
    first = fit_text(name, available, 6.5)
    pdf.drawString(right, (height - 9) * mm, first)
    identification = ' / '.join(value for value in (record.card_number, record.language) if value)
    pdf.drawString(right, (height - 13) * mm, fit_text(identification, available, 6.5))
    # Full 35-character PC/SP references fit at 6pt in 46mm, without UUID shortening.
    pdf.setFont('Courier', 6)
    pdf.drawString(2 * mm, 5 * mm, record.reference)
    pdf.drawString(2 * mm, 2 * mm, fit_text(record.submission_reference, (width - 4) * mm, 6, 'Courier'))


def generate_pdf(records, profile='50x30', calibration=False):
    if profile not in PROFILE_SIZES or not 1 <= len(records) <= MAX_BATCH:
        raise ValueError('invalid_input')
    # Canonical ordering and deduplication independent of selection order.
    ordered = {normalize_reference(r.reference): r for r in records}
    buffer = BytesIO()
    pdf = new_pdf(buffer, PROFILE_SIZES[profile])
    started = time.monotonic()
    for reference in sorted(ordered):
        if time.monotonic() - started > GENERATION_SECONDS:
            raise HTTPException(503, 'labels_busy')
        record = ordered[reference]
        draw_label(pdf, record, profile)
        if calibration:
            pdf.setLineWidth(.3)
            pdf.rect(1 * mm, 1 * mm, (PROFILE_SIZES[profile][0]-2)*mm, (PROFILE_SIZES[profile][1]-2)*mm)
            # Ten-millimetre ruler, away from the QR and identity lines.
            x, y = 2 * mm, (PROFILE_SIZES[profile][1]-2)*mm
            pdf.line(x, y, x+10*mm, y)
            for i in range(11):
                pdf.line(x+i*mm, y, x+i*mm, y-.6*mm)
        pdf.showPage()
    pdf.save()
    data = buffer.getvalue()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, 'label_output_limit')
    return data


def records_for(db, references, submission_id=None):
    refs = sorted({normalize_reference(r) for r in references})
    query = (select(PhysicalCard.reference, PhysicalCard.submission_id, PhysicalCard.entry_id,
                    Parcel.submission_id.label('parcel_submission'), Submission.reference.label('submission_reference'),
                    SubmissionEntry.submission_id.label('entry_submission'), SubmissionEntry.card_name,
                    SubmissionEntry.card_number, SubmissionEntry.language)
             .join(Submission, Submission.id == PhysicalCard.submission_id)
             .join(Parcel, Parcel.id == PhysicalCard.parcel_id)
             .outerjoin(SubmissionEntry, SubmissionEntry.id == PhysicalCard.entry_id)
             .where(PhysicalCard.reference.in_(refs)))
    if submission_id:
        query = query.where(PhysicalCard.submission_id == submission_id)
    rows = list(db.execute(query))
    if len(rows) != len(refs):
        raise HTTPException(404, 'card_not_in_submission' if submission_id else 'card_not_found')
    if any(r.parcel_submission != r.submission_id or (r.entry_id and r.entry_submission != r.submission_id) for r in rows):
        raise HTTPException(409, 'trace_inconsistent')
    return [LabelRecord(r.reference, r.submission_reference, r.card_name or '', r.card_number or '', r.language or '') for r in rows]


router = APIRouter(prefix='/internal/labels', dependencies=[Depends(require_staff), Depends(write_guard)], include_in_schema=False)


def pdf_response(records, profile, filename, calibration=False):
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, 'labels_busy')
    try:
        data = generate_pdf(records, profile, calibration)
    finally:
        _slots.release()
    return Response(data, media_type='application/pdf', headers={
        'Cache-Control': 'private, no-store', 'Content-Disposition': f'inline; filename="{filename}"',
        'X-Label-Count': str(len({r.reference for r in records})),
    })


@router.get('/cards/{reference}/pdf')
def individual(reference: str, db: Db, profile: Profile = '50x30'):
    try:
        reference = normalize_reference(reference)
    except ValueError:
        raise HTTPException(422, 'invalid_card_reference') from None
    return pdf_response(records_for(db, [reference]), profile, f'spectra-{reference}-{profile}.pdf')


class Batch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    references: list[Annotated[str, Field(min_length=35, max_length=64)]] = Field(min_length=1, max_length=MAX_BATCH)
    profile: Profile = '50x30'

    @field_validator('references')
    @classmethod
    def canonical(cls, values):
        return [normalize_reference(v) for v in values]


@router.post('/submissions/{sid}/pdf')
def batch(sid: UUID, payload: Batch, db: Db):
    return pdf_response(records_for(db, payload.references, sid), payload.profile,
                        f'spectra-labels-{sid.hex}-{payload.profile}.pdf')


@router.get('/calibration/pdf')
def calibration(profile: Profile = '50x30'):
    # Reserved synthetic identity; not inserted into the DB or resolvable as a real card.
    record = LabelRecord('PC-'+'0'*32, 'CALIBRATION - NOT A CARD', 'CALIBRATION', '10 mm ruler', 'TEST')
    return pdf_response([record], profile, f'spectra-calibration-{profile}.pdf', calibration=True)
