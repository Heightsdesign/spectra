import json
import os
from unittest.mock import patch
from uuid import uuid4
import pytest
from incoming_fixtures import MemoryCredentials
from selby_workstation.connection import DesktopConnection
from selby_workstation.desktop_auth import DesktopAuthService, AuthTransport
from selby_workstation.incoming import PreviewError
from test_selby_incoming import server, wait_until, SUMMARY  # noqa: F401

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtTest import QTest
from PySide6.QtCore import QThreadPool
from selby_workstation.incoming_ui import IncomingSubmissions


@pytest.fixture
def incoming(server):
    app=QApplication.instance() or QApplication([])
    vault=MemoryCredentials()
    auth=DesktopAuthService(DesktopConnection('development',server.url,'http://127.0.0.1:3000'),vault,timeout=0.5)
    widget=IncomingSubmissions(auth_service=auth);widget.show()
    wait_until(lambda:not widget.busy)
    yield widget,auth,vault,app
    widget.disconnect();QThreadPool.globalInstance().waitForDone(3000);app.processEvents();widget.close()


def sign_in(widget,password='desktop-test-pass'):
    widget.email.setText('operator@example.invalid');widget.password.setText(password);widget.connect_button.click()
    assert widget.password.text()==''
    wait_until(lambda:not widget.busy)


def test_gui_login_automatic_recent_orders_search_pages_and_logout(incoming,server):
    widget,auth,vault,_=incoming
    assert not hasattr(widget,'token') and not hasattr(widget,'origin') and not hasattr(widget,'cookie')
    assert widget.password.echoMode()==QLineEdit.EchoMode.Password
    server.rows=[{**SUMMARY,'id':str(uuid4()),'customer_name':f'Customer {i}','submitted_at':'2026-10-25T12:00:00Z'} for i in range(50)]
    sign_in(widget)
    assert widget.queue.rowCount()==50 and widget.queue.columnCount()==6
    assert widget.queue.item(0,1).text()=='Customer 0' and '2026-10-25' in widget.queue.item(0,4).text()
    assert widget.next_button.isEnabled() and widget.login_form.isHidden()
    server.rows=[{**SUMMARY,'customer_name':'Last Customer'}]
    widget.next_button.click();wait_until(lambda:not widget.busy)
    assert widget.offset==50 and widget.queue.rowCount()==1 and not widget.next_button.isEnabled()
    assert any('offset=50' in path for _,path,_ in server.requests)
    widget.search.setText('Last Customer');widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert widget.offset==0 and any('search=Last+Customer' in path for _,path,_ in server.requests)
    widget.disconnect_button.click();wait_until(lambda:not widget.busy)
    assert widget.queue.rowCount()==0 and widget.client is None and vault.value is None and server.revoked
    assert 'revoked' in widget.status.text()


def test_gui_invalid_role_expiry_and_no_secret_in_widgets(incoming,server):
    widget,_,vault,_=incoming
    sign_in(widget,'incorrect')
    assert 'Invalid email or password' in widget.status.text() and widget.client is None and vault.value is None
    server.role=None;sign_in(widget)
    assert widget.client is None and vault.value is None and server.revoked
    server.role='operator';sign_in(widget)
    server.code=401;widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert widget.client is None and widget.queue.rowCount()==0 and vault.value is None
    assert 'session expired' in widget.connection_state.text()
    assert all('desktop-test-pass' not in line.text() for line in widget.findChildren(QLineEdit))


def test_gui_permission_and_reachability_diagnostics(incoming, server):
    widget, _, _, _ = incoming
    sign_in(widget)
    assert 'authenticated' in widget.connection_state.text()
    server.code=503
    widget.refresh_button.click();wait_until(lambda:not widget.busy)
    server.code=200
    widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert 'Backend reachable' in widget.connection_state.text()
    server.role=None
    widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert 'permission denied' in widget.connection_state.text()


def test_gui_restores_own_saved_session_and_loads_automatically(server):
    app=QApplication.instance() or QApplication([])
    vault=MemoryCredentials();auth=DesktopAuthService(DesktopConnection('development',server.url,'http://127.0.0.1:3000'),vault)
    auth.sign_in('operator@example.invalid','desktop-test-pass')
    before=sum(method=='POST' and path=='/api/auth/login' for method,path,_ in server.requests)
    widget=IncomingSubmissions(auth_service=DesktopAuthService(auth.connection,vault));widget.show()
    try:
        wait_until(lambda:widget.queue.rowCount()==1 and not widget.busy)
        assert sum(method=='POST' and path=='/api/auth/login' for method,path,_ in server.requests)==before
        assert widget.client is not None
    finally:
        widget.disconnect();app.processEvents();widget.close()
    assert vault.value is not None  # Closing preserves an authorized OS-stored session, unlike Sign out.


def test_gui_offline_logout_queues_revocation_and_never_restores_orders(incoming,server):
    widget,auth,vault,app=incoming
    sign_in(widget)
    with patch.object(AuthTransport,'revoke',side_effect=PreviewError('Offline',kind='offline')):
        widget.disconnect_button.click();wait_until(lambda:not widget.busy)
    assert widget.client is None and widget.queue.rowCount()==0
    assert json.loads(vault.value)['pending_revocation']
    assert 'pending offline' in widget.status.text()
    widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert server.revoked and vault.value is None and widget.queue.rowCount()==0


def test_gui_close_during_sign_in_discards_late_authorization(incoming,server):
    widget,_,vault,app=incoming
    server.delay=0.1
    widget.email.setText('operator@example.invalid');widget.password.setText('desktop-test-pass');widget.connect_button.click()
    widget.disconnect()
    assert QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents();QTest.qWait(20)
    assert widget.client is None and widget.queue.rowCount()==0 and vault.value is None
    assert not any(method=='POST' and path=='/api/auth/login' for method,path,_ in server.requests) or server.revoked


def test_gui_network_failure_keeps_session_for_refresh_and_local_tools(incoming,server):
    widget,auth,vault,_=incoming
    sign_in(widget);saved=vault.value
    with patch('selby_workstation.incoming.PreviewClient.submissions',side_effect=PreviewError('Offline: service unavailable',kind='offline')):
        widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert 'Offline' in widget.status.text() and widget.client is not None and vault.value==saved
    assert 'Backend unreachable' in widget.connection_state.text()
    assert widget.queue.rowCount()==0
    widget.refresh_button.click();wait_until(lambda:not widget.busy)
    assert widget.queue.rowCount()==1
    assert 'authenticated' in widget.connection_state.text()
