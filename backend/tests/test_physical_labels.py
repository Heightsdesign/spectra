from io import BytesIO
import copy
from uuid import uuid4

import cv2
import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader
import pytest
from sqlalchemy import select, text

from app.auth import csrf_value, now
from app.customer_models import CustomerSession
from app.intake_models import StaffMembership
from app.physical_identity import parse_scan, qr_payload
from app.physical_labels import LabelRecord, MAX_BATCH, PROFILE_SIZES, generate_pdf, qr_symbol, fit_text, printable
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from test_customer_operations import operations, login  # noqa: F401

BASE='/internal/labels'
REFERENCE='PC-'+'A'*32


def decode_page(data, page=0, dpi=203):
    with pdfium.PdfDocument(data) as document:
        rendered=document[page]
        bitmap=rendered.render(scale=dpi/72, grayscale=True)
        try:
            image=np.array(bitmap.to_pil())
        finally:
            bitmap.close();rendered.close()
    return cv2.QRCodeDetector().detectAndDecode(image)[0]


@pytest.mark.parametrize('profile', list(PROFILE_SIZES))
@pytest.mark.parametrize('dpi',[203,300])
def test_exact_dimensions_full_identity_and_pdf_qr_roundtrip(profile,dpi):
    data=generate_pdf([LabelRecord(REFERENCE,'SP-'+'B'*32,'Pokémon Évoli Ω','1/102','FR')],profile)
    reader=PdfReader(BytesIO(data))
    assert len(reader.pages)==1
    page=reader.pages[0]
    width,height=PROFILE_SIZES[profile]
    assert float(page.mediabox.width)==pytest.approx(width*mm,abs=.0001)
    assert float(page.mediabox.height)==pytest.approx(height*mm,abs=.0001)
    assert reader.trailer['/Root']['/ViewerPreferences']['/PrintScaling']=='/None'
    assert REFERENCE in page.extract_text()
    assert 'SP-'+'B'*32 in page.extract_text()
    assert decode_page(data,dpi=dpi)==qr_payload(REFERENCE)


def test_qr_quiet_zone_determinism_and_unique_cards():
    a=qr_symbol(REFERENCE)
    assert a.designator=='3-Q' and not a.is_micro
    matrix=list(a.matrix_iter(border=4))
    assert len(matrix)==37
    assert all(not value for row in matrix[:4]+matrix[-4:] for value in row)
    assert all(not value for row in matrix for value in row[:4]+row[-4:])
    png=BytesIO();a.save(png,kind='png',scale=5,border=4)
    image=cv2.imdecode(np.frombuffer(png.getvalue(),np.uint8),cv2.IMREAD_GRAYSCALE)
    assert cv2.QRCodeDetector().detectAndDecode(image)[0]==qr_payload(REFERENCE)
    records=[LabelRecord(REFERENCE,'SP-'+'B'*32,'Identical card'),LabelRecord('PC-'+'C'*32,'SP-'+'D'*32,'Identical card')]
    first=generate_pdf(records)
    assert first==generate_pdf(records)
    assert decode_page(first,0)!=decode_page(first,1)


@pytest.mark.parametrize('count',[20,50,100,250])
def test_large_batch_one_page_per_card_sorted_and_deduplicated(count):
    records=[LabelRecord('PC-'+f'{i:032X}','SP-'+'B'*32,'Example') for i in range(1,count+1)]
    data=generate_pdf(list(reversed(records)))
    reader=PdfReader(BytesIO(data))
    assert len(reader.pages)==count
    assert len(data)<8*1024*1024
    assert [r.reference for r in records]==[next(line for line in page.extract_text().splitlines() if line.startswith('PC-')) for page in reader.pages]
    assert decode_page(data,0)==qr_payload(records[0].reference)
    assert decode_page(data,count-1)==qr_payload(records[-1].reference)
    duplicate=generate_pdf([records[0],records[0]])
    assert len(PdfReader(BytesIO(duplicate)).pages)==1
    assert duplicate==generate_pdf([records[0]])


def test_unicode_long_names_are_bounded_and_visible_without_clipping():
    for name in ['Pokémon Évoli Ω','漢字 カード Ж','é'*200,'W'*200,'<script>long</script>\nname']:
        fitted=fit_text(name,25*mm,6.5)
        assert pdfmetrics.stringWidth(fitted,'SpectraLabel',6.5)<=25*mm
        assert '\n' not in fitted
        if len(name)>100:
            assert fitted.endswith('...')
        data=generate_pdf([LabelRecord(REFERENCE,'SP-'+'B'*32,name,'1/102','JP')])
        assert decode_page(data)==qr_payload(REFERENCE)
    assert printable('漢字')=='??'
    assert printable('Pokémon')=='Pokémon'


@pytest.mark.parametrize('value',[REFERENCE.lower()+'\r\n',qr_payload(REFERENCE)+'\r\n','\t'+qr_payload(REFERENCE.lower())+'\n'])
def test_scanner_payload_and_suffix(value):
    assert parse_scan(value)==REFERENCE


@pytest.mark.parametrize('value',['PC-123','SP:PC:2:'+REFERENCE,'https://example.invalid/'+REFERENCE,'PC-'+'Z'*32,REFERENCE[:8]+'\n'+REFERENCE[8:]])
def test_malformed_ambiguous_scans_rejected(value):
    with pytest.raises(ValueError):parse_scan(value)


def headers(operations):
    return {'Origin':operations[2].auth_origin,'X-Spectra-Client':'1','X-CSRF-Token':csrf_value(operations[-1])}


def check_pdf(response,count=1):
    assert response.status_code==200,response.text[:100] if response.status_code!=200 else ''
    assert response.headers['content-type']=='application/pdf'
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['referrer-policy']=='no-referrer'
    assert response.headers['x-label-count']==str(count)
    assert len(PdfReader(BytesIO(response.content)).pages)==count
    return response.content


@pytest.mark.parametrize('access',['anonymous','customer','revoked','disabled','unverified','removed_staff'])
def test_staff_authorization_on_every_pdf_route(operations,access):
    client,db,_,actor,customer,_,items,_,card,*_=operations
    if access=='anonymous':client.cookies.clear()
    elif access=='customer':login(client,db,customer)
    elif access=='removed_staff':db.delete(db.get(StaffMembership,actor.id))
    elif access=='disabled':actor.status='disabled'
    elif access=='unverified':actor.email_verified=False
    else:
        db.scalar(select(CustomerSession).where(CustomerSession.customer_id==actor.id)).revoked_at=now()
    db.commit()
    status=403 if access in {'customer','removed_staff'} else 401
    for path in ['/cards/not-valid/pdf','/calibration/pdf']:
        response=client.get(BASE+path)
        assert response.status_code==status and response.headers['cache-control']=='private, no-store'
    response=client.post(BASE+'/submissions/'+str(items[0][0].id)+'/pdf',json={'references':[card.reference]},headers=headers(operations))
    assert response.status_code==status


def test_frozen_compatibility_privacy_reprinting_no_mutation(operations):
    client,db,_,actor,customer,_,items,parcel,card,*_=operations
    tables=['physical_cards','intake_parcels','submission_intakes','intake_audit_events','customer_submissions','customer_submission_entries','quote_acceptances','submission_quotes']
    def state():return {t:copy.deepcopy([dict(r) for r in db.execute(text(f'SELECT * FROM {t}')).mappings()]) for t in tables}
    before=state()
    first=check_pdf(client.get(BASE+'/cards/'+card.reference+'/pdf'))
    assert first==check_pdf(client.get(BASE+'/cards/'+card.reference+'/pdf'))
    batch=check_pdf(client.post(BASE+'/submissions/'+str(items[0][0].id)+'/pdf',json={'references':[card.reference,card.reference]},headers=headers(operations)))
    assert batch==first
    text_content=PdfReader(BytesIO(first)).pages[0].extract_text()+str(PdfReader(BytesIO(first)).metadata)
    for secret in [customer.email,str(customer.id),customer.first_name,customer.last_name,'Shipment recipient','Historical recipient','+33123456789',actor.email,'PASSWORD-HASH-MUST-NOT-LEAK']:
        assert secret not in text_content
    assert decode_page(first)==qr_payload(card.reference)
    assert state()==before
    assert client.get('/internal/customer-operations/cards/'+qr_payload(card.reference)+'%0D%0A').json()['customer']['id']==str(customer.id)


def test_batch_scope_missing_invalid_and_csrf_origin(operations):
    client,db,_,_,_,_,items,_,card,*_=operations
    path=BASE+'/submissions/'+str(items[0][0].id)+'/pdf'
    payload={'references':[card.reference]}
    assert client.post(path,json=payload).status_code==403
    for modified in [{'Origin':'https://evil.invalid'},{'X-CSRF-Token':'bad'},{'X-Spectra-Client':''}]:
        assert client.post(path,json=payload,headers={**headers(operations),**modified}).status_code==403
    for payload in [{'references':[]},{'references':[card.reference]*(MAX_BATCH+1)},{'references':['invalid']},{'references':[card.reference],'profile':'../../file'},{'references':[card.reference],'path':'C:/secret'},{'references':['x'*1000]}]:
        response=client.post(path,json=payload,headers=headers(operations))
        assert response.status_code==422
        assert response.json()=={'detail':'invalid_input'}
    response=client.post(BASE+'/submissions/'+str(items[2][0].id)+'/pdf',json={'references':[card.reference]},headers=headers(operations))
    assert response.status_code==404 and response.json()['detail']=='card_not_in_submission'
    assert client.get(BASE+'/cards/PC-'+uuid4().hex.upper()+'/pdf').status_code==404
    assert client.get(BASE+'/cards/PC-bad/pdf').status_code==422
    assert client.get(BASE+'/cards/'+card.reference+'/pdf?profile=999x999').status_code==422


def test_pdf_generation_rejects_inconsistent_card_relationships(operations):
    client,db,_,_,_,_,items,_,card,*_=operations
    card.entry_id=items[2][1].id;db.commit()
    assert client.get(BASE+'/cards/'+card.reference+'/pdf').status_code==409


@pytest.mark.parametrize('profile',list(PROFILE_SIZES))
def test_calibration_sheet_and_safe_filenames(operations,profile):
    response=operations[0].get(BASE+'/calibration/pdf',params={'profile':profile})
    data=check_pdf(response)
    assert 'CALIBRATION' in PdfReader(BytesIO(data)).pages[0].extract_text()
    assert decode_page(data)==qr_payload('PC-'+'0'*32)
    assert response.headers['content-disposition']==f'inline; filename="spectra-calibration-{profile}.pdf"'


def test_generation_resource_bounds(monkeypatch):
    from app import physical_labels
    from fastapi import HTTPException
    records=[LabelRecord(REFERENCE,'SP-'+'B'*32)]
    with pytest.raises(ValueError):generate_pdf(records*(MAX_BATCH+1))
    with pytest.raises(ValueError):generate_pdf([])
    monkeypatch.setattr(physical_labels,'MAX_PDF_BYTES',1)
    with pytest.raises(HTTPException) as failure:generate_pdf(records)
    assert failure.value.status_code==413
    monkeypatch.setattr(physical_labels,'GENERATION_SECONDS',-1)
    with pytest.raises(HTTPException) as failure:generate_pdf(records)
    assert failure.value.status_code==503
