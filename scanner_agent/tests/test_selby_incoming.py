"""Real HTTP contract fixture, GET-only security and offscreen Qt preview workflows."""

import json
import hashlib
import base64
import os
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from selby_workstation.incoming import PreviewClient, PreviewError, backend_url
from selby_workstation.connection import DesktopConnection
from selby_workstation.desktop_auth import DesktopAuthService
from incoming_fixtures import MemoryCredentials

TOKEN = 'a' * 43
SID, EID, EID2, PID, CID = (str(uuid4()) for _ in range(5))
SUMMARY = dict(id=SID, reference='SP-' + SID.replace('-', '').upper(), status='reconciliation_pending',
               declared_quantity=3, received_quantity=1, commercially_accepted=False,
               payment_status='not_implemented')
DETAIL = dict(**SUMMARY, entries=[dict(id=EID, card_name='First', game='pokemon', expansion='Set',
                                     card_number='1', language='FR', quantity=2),
                                 dict(id=EID2, card_name='Second', game='one-piece', quantity=1)],
              cards=[dict(id=CID, reference='PC-' + CID.replace('-', '').upper(), parcel_id=PID,
                          entry_id=EID, status='matched', grading_card_id=None)],
              parcels=[dict(id=PID, reference='PI-' + PID.replace('-', '').upper(), status='reconciling')],
              discrepancies=[dict(kind='missing', entry_id=EID2, card_id=None, quantity=1,
                                  status='open', notes='Not received', resolution=None)])


@pytest.fixture
def server():
    state = SimpleNamespace(code=200, rows=[deepcopy(SUMMARY)], detail=deepcopy(DETAIL),
                            requests=[], delay=0, redirect=False, photo=b'fixture-bytes', photo_mime='image/png', role='operator', revoked=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.requests.append((self.command, self.path, self.headers.get('Cookie')))
            time.sleep(state.delay)
            path = urlsplit(self.path).path
            code = state.code if self.headers.get('Cookie') == 'spectra_session=' + TOKEN and not state.revoked else 401
            if path.startswith('/internal/') and state.role is None and code == 200:
                code = 403
            if state.redirect:
                self.send_response(302)
                self.send_header('Location', '/unexpected')
                self.end_headers()
                return
            data = {'role': state.role, 'display_name':'Synthetic Operator'} if path.endswith('/me') else state.rows
            if path == '/api/health':
                code = 200
                data = {'status':'ok', 'application':'SPECTRA'}
            if path == '/api/auth/csrf':
                data = {'csrf_token':'c'*64}
            if path.endswith('/' + SID):
                data = state.detail
            raw = json.dumps(data).encode()
            is_photo = '/pre-shipment-photos/' in path
            if is_photo:
                raw = state.photo
            self.send_response(code)
            self.send_header('Content-Type', state.photo_mime if is_photo else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass

        def do_POST(self):
            state.requests.append(('POST', self.path, None))
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            if state.redirect:
                self.send_response(302);self.send_header('Location','/unexpected-auth-redirect');self.end_headers();return
            if self.headers.get('Origin')!='http://127.0.0.1:3000' or self.headers.get('X-Spectra-Client')!='1':
                self.send_error(403);return
            if self.path=='/api/auth/login':
                if data!={'email':'operator@example.invalid','password':'desktop-test-pass'}:
                    self.send_error(401);return
                state.revoked=False
                self.send_response(200)
                self.send_header('Set-Cookie',f'spectra_session={TOKEN}; Max-Age=3600; Path=/; HttpOnly; SameSite=Lax')
            elif self.path=='/api/auth/logout':
                if self.headers.get('Cookie')!='spectra_session='+TOKEN or self.headers.get('X-CSRF-Token')!='c'*64:
                    self.send_error(403);return
                state.revoked=True
                self.send_response(200)
            else:
                self.send_error(405);return
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(b'{}')

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state.url = f'http://127.0.0.1:{httpd.server_port}'
    yield state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def client(server, token=TOKEN):
    return PreviewClient(server.url, token, 'spectra_session')


def test_authenticated_get_only_contract_search_pagination(server):
    api = client(server)
    assert api.staff()['role'] == 'operator'
    assert api.submissions('SP-ABC', 50) == [SUMMARY]
    assert api.submission(SID) == DETAIL
    assert parse_qs(urlsplit(server.requests[1][1]).query) == {
        'search': ['SP-ABC'], 'offset': ['50'], 'limit': ['50']}
    assert all(method == 'GET' for method, _, _ in server.requests)
    assert all(path.startswith('/internal/intake/') for _, path, _ in server.requests)


def test_customer_photos_are_private_bounded_and_integrity_checked(server):
    photo = {'id':str(uuid4()), 'file_size':len(server.photo), 'sha256':hashlib.sha256(server.photo).hexdigest(),
             'provenance':'customer_pre_shipment', 'identity_verified':False}
    assert client(server).photo(SID, photo) == server.photo
    assert server.requests[-1] == ('GET',f"/internal/intake/submissions/{SID}/pre-shipment-photos/{photo['id']}",'spectra_session='+TOKEN)
    with pytest.raises(PreviewError, match='integrity'):
        client(server).photo(SID,{**photo,'sha256':'0'*64})
    with pytest.raises(PreviewError, match='provenance'):
        client(server).photo(SID,{**photo,'identity_verified':True})
    server.photo_mime='image/svg+xml'
    with pytest.raises(PreviewError, match='unsupported'):
        client(server).photo(SID,photo)
    server.photo_mime='image/png'
    server.photo=b'x'*(8*1024*1024+1)
    with pytest.raises(PreviewError, match='too large'):
        client(server).photo(SID,photo)


def test_gui_customer_photo_metadata_is_separate_and_disconnect_clears(ui, server):
    widget, _ = ui
    server.photo=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==')
    server.detail['entries'][0]['pre_shipment_photos']=[{'id':str(uuid4()), 'entry_id':EID, 'copy_number':2,
        'side':'front','uploaded_at':'2026-10-25T12:00:00Z','provenance':'customer_pre_shipment','identity_verified':False,
        'file_size':len(server.photo),'sha256':hashlib.sha256(server.photo).hexdigest()}]
    connect(widget,server)
    widget.queue.selectRow(0)
    wait_until(lambda:not widget.busy)
    assert widget.photos.rowCount()==1 and widget.expected.rowCount()==2
    assert widget.photos.item(0,1).text()=='2'
    widget.photos.selectRow(0)
    widget.photo_button.click()
    wait_until(lambda:not widget.busy)
    assert not widget.photo_preview.pixmap().isNull()
    widget.disconnect()
    assert widget.photos.rowCount()==0 and widget.photo_preview.pixmap().isNull()


@pytest.mark.parametrize('code', [401, 403])
def test_unauthorized_expired_or_revoked(server, code):
    server.code = code
    with pytest.raises(PreviewError) as error:
        client(server).submissions()
    assert error.value.disconnect
    assert TOKEN not in str(error.value)


def test_invalid_session_and_empty_list(server):
    with pytest.raises(PreviewError, match='Session expired'):
        client(server, 'b' * 43).staff()
    server.rows = []
    assert client(server).submissions() == []


def test_unreachable_timeout_redirect_and_invalid_response(server):
    server.redirect = True
    with pytest.raises(PreviewError):
        client(server).staff()
    assert len(server.requests) == 1  # Do not follow redirects with the credential.
    server.redirect = False
    server.delay = 0.2
    api = client(server)
    api.timeout = 0.02
    with pytest.raises(PreviewError, match='unreachable'):
        api.staff()
    server.delay = 0
    server.rows = {'unexpected': True}
    with pytest.raises(PreviewError, match='invalid submission list'):
        client(server).submissions()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    origin = f'http://127.0.0.1:{httpd.server_port}'
    httpd.server_close()
    with pytest.raises(PreviewError, match='unreachable'):
        PreviewClient(origin, TOKEN, 'spectra_session', timeout=0.1).staff()


@pytest.mark.parametrize('url', ['http://example.org', 'http://127.0.0.1.example.org',
                                 'https://user:secret@example.org', 'https://example.org/api',
                                 'https://example.org?token=secret', 'file:///tmp/example',
                                 'https://example.org:bad'])
def test_reject_unsafe_origins(url):
    with pytest.raises(PreviewError):
        backend_url(url)


def test_loopback_https_and_production_cookie():
    assert backend_url('http://[::1]:8000/') == 'http://[::1]:8000'
    assert backend_url('https://example.org') == 'https://example.org'
    with pytest.raises(PreviewError, match='require HTTPS'):
        PreviewClient('http://localhost:8000', TOKEN)


@pytest.fixture
def ui():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication

    from selby_workstation.incoming_ui import IncomingSubmissions
    app = QApplication.instance() or QApplication([])
    widget = IncomingSubmissions()
    widget.show()
    yield widget, app
    widget.disconnect()
    wait_until(lambda: not widget.busy)
    widget.close()


def wait_until(predicate, timeout=4000):
    from PySide6.QtTest import QTest
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def connect(widget, server, wait=True):
    widget.auth=DesktopAuthService(DesktopConnection('development',server.url,'http://127.0.0.1:3000'),MemoryCredentials())
    widget.controls()
    widget.email.setText('operator@example.invalid')
    widget.password.setText('desktop-test-pass')
    widget.connect_button.click()
    assert widget.password.text() == ''
    if wait:
        wait_until(lambda: not widget.busy)


def test_gui_multi_card_distinction_search_refresh_and_expiry(ui, server):
    widget, _ = ui
    connect(widget, server)
    assert widget.queue.rowCount() == 1
    widget.queue.selectRow(0)
    wait_until(lambda: not widget.busy)
    assert widget.expected.rowCount() == 2
    assert widget.physical.rowCount() == 1
    assert 'Declared: 3 · Received: 1' in widget.detail.text()
    assert 'reconciliation_pending' in widget.detail.text()
    assert 'no local mapping' in widget.detail.text()
    assert widget.parcels.rowCount() == 1 and widget.issues.rowCount() == 1
    server.detail['status'] = 'on_hold'
    widget.refresh_button.click()
    wait_until(lambda: not widget.busy)
    assert 'on_hold' in widget.detail.text()
    widget.search.setText('SP-ABC')
    widget.refresh_button.click()
    wait_until(lambda: not widget.busy)
    assert any('search=SP-ABC' in path for _, path, _ in server.requests)
    server.code = 401
    widget.refresh_button.click()
    wait_until(lambda: not widget.busy)
    assert widget.client is None and widget.expected.rowCount() == 0
    assert widget.queue.rowCount() == 0 and 'expired' in widget.status.text()
    assert all(method == 'GET' or path in ('/api/auth/login','/api/auth/logout') for method, path, _ in server.requests)


def test_gui_empty_error_and_disconnect_ignores_late_result(ui, server):
    widget, _ = ui
    server.rows = []
    connect(widget, server)
    assert 'no submitted submissions' in widget.status.text()
    server.code = 503
    widget.refresh_button.click()
    wait_until(lambda: not widget.busy)
    assert 'failed' in widget.status.text()
    server.code = 200
    server.rows = [SUMMARY]
    server.delay = 0.15
    widget.refresh_button.click()
    widget.disconnect_button.click()
    from PySide6.QtTest import QTest
    QTest.qWait(400)
    wait_until(lambda: not widget.busy)
    assert widget.client is None and widget.queue.rowCount() == 0
    assert widget.status.text().startswith('Signed out')


def test_navigation_responsive_and_preserves_registry_and_session(server, tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from test_selby_desktop import saved_dossier

    from selby_workstation.app import Workstation
    from selby_workstation.orders import OrderStore
    from spectra_scanner.storage import sha256_file

    app = QApplication.instance() or QApplication([])
    w = Workstation(settings_path=tmp_path / 'desktop.ini')
    w.orders_path = tmp_path / 'orders.sqlite3'
    w.draft_directory = tmp_path / 'drafts'
    store = OrderStore(w.orders_path)
    order = store.create_order('Preserved')
    card = store.add_cards(order['id'])[0]
    path, image, report = saved_dossier(tmp_path)
    w.open_session(path)
    current, data = w.session, deepcopy(w.session.data)
    files = (w.orders_path, path, image, report)
    hashes = {p: sha256_file(p) for p in files}
    w.show()
    page = w.desktop.pages['Incoming Submissions']
    w.desktop.buttons['Incoming Submissions'].click()
    assert w.desktop.current == 'Incoming Submissions'
    server.delay = 0.2
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    connect(page,server,wait=False)
    assert page.busy
    w.desktop.buttons['Inspection'].click()
    assert w.desktop.current == 'Inspection' and page.busy
    wait_until(lambda: not page.busy)
    timer.stop()
    assert len(ticks) >= 5
    assert w.session is current and w.session.data == data
    assert store.get_card(card['id'])['id'] == 'SLB-C-000001'
    assert {p: sha256_file(p) for p in files} == hashes
    # Entering the preview also works without ever creating a registry.
    w.orders_path = tmp_path / 'never-created.sqlite3'
    w.desktop.navigate('Incoming Submissions')
    assert not w.orders_path.exists()
    w.dirty = False
    w.close()
    app.processEvents()
    assert page.client is None
