"""Setup is explicit, persists nonsecrets and enables the existing login immediately."""
import socket
import pytest
from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtWidgets import QApplication
from selby_workstation.connection import DesktopConnection
from selby_workstation.connection_settings import ConnectionSettings
from selby_workstation.incoming import PreviewError
from selby_workstation.desktop_auth import DesktopAuthService
from incoming_fixtures import MemoryCredentials
from test_selby_incoming import server, wait_until  # noqa: F401
from test_selby_desktop import desktop  # noqa: F401


def test_settings_explicit_save_enables_login_persists_and_preserves_other_preferences(desktop):
    window, app, _ = desktop
    shell = window.desktop
    panel = shell.connection_settings
    incoming = shell.pages['Incoming Submissions']
    assert incoming.auth is None and not incoming.connect_button.isEnabled()
    incoming.setup_button.click()
    assert shell.current == 'Settings'
    shell.settings.setValue('unrelated/preference', 'keep')
    panel.local_button.click()
    assert not shell.settings.contains('incoming/environment')  # Selecting defaults is not consent to save.
    panel.save_button.click()
    assert incoming.connect_button.isEnabled() and incoming.email.isEnabled() and incoming.password.isEnabled()
    assert incoming.auth.connection.backend_origin == 'http://127.0.0.1:8000'
    restored = QSettings(shell.settings.fileName(), QSettings.Format.IniFormat)
    values = {key: restored.value(key) for key in restored.allKeys()}
    assert values['unrelated/preference'] == 'keep'
    assert {key for key in values if key.startswith('incoming/')} == {'incoming/environment','incoming/backend_origin','incoming/auth_origin'}
    assert DesktopConnection.load(values, environ={}) == incoming.auth.connection
    assert 'Authentication required' in incoming.status.text()


def test_settings_invalid_origin_is_not_saved_and_remains_offline(desktop):
    window, _, _ = desktop
    panel = window.desktop.connection_settings
    panel.local_button.click()
    panel.backend.setText('http://192.0.2.10:8000')
    panel.save_button.click()
    assert 'HTTPS' in panel.status.text()
    assert not window.desktop.settings.contains('incoming/environment')
    assert window.desktop.pages['Incoming Submissions'].auth is None
    window.desktop.navigate('Inspection')
    assert window.desktop.current == 'Inspection'


def test_health_check_is_unauthenticated_and_reports_reachability(server):
    connection = DesktopConnection('development', server.url, 'http://127.0.0.1:3000')
    assert 'Backend reachable' in connection.check()
    assert server.requests == [('GET', '/api/health', None)]
    server.redirect = True
    with pytest.raises(PreviewError, match='health endpoint'):
        connection.check()
    assert not any(path == '/unexpected' for _,path,_ in server.requests)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]  # Bound but not listening.
        unavailable = DesktopConnection('development', f'http://127.0.0.1:{port}', connection.auth_origin)
        with pytest.raises(PreviewError, match='unreachable'):
            unavailable.check(timeout=0.1)


def test_settings_test_button_runs_background_health_check(tmp_path,server):
    app = QApplication.instance() or QApplication([])
    panel = ConnectionSettings(QSettings(str(tmp_path/'desktop.ini'),QSettings.Format.IniFormat))
    panel.local_button.click()
    panel.backend.setText(server.url)
    panel.test_button.click()
    assert not panel.test_button.isEnabled()
    wait_until(lambda:panel.job is None)
    assert 'Backend reachable' in panel.status.text()
    panel.close()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()


def test_environment_overrides_are_visible_and_cannot_be_silently_overwritten(tmp_path,monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('SELBY_ENVIRONMENT','development')
    panel = ConnectionSettings(QSettings(str(tmp_path/'desktop.ini'),QSettings.Format.IniFormat))
    assert not panel.save_button.isEnabled() and not panel.backend.isEnabled()
    assert 'environment overrides' in panel.status.text()
    panel.close()
    app.processEvents()


def test_origin_switch_preserves_pending_revocation_and_old_preferences(desktop, server):
    window, app, _ = desktop
    shell = window.desktop
    panel = shell.connection_settings
    page = shell.pages['Incoming Submissions']
    panel.local_button.click()
    panel.backend.setText(server.url)
    panel.save_button.click()
    auth = DesktopAuthService(page.auth.connection, MemoryCredentials(), timeout=0.2)
    page.auth = auth
    page.authenticated(auth.sign_in('operator@example.invalid', 'desktop-test-pass'))
    wait_until(lambda:not page.busy)
    server.code = 503
    panel.backend.setText('http://127.0.0.1:8001')
    panel.save_button.click()
    wait_until(lambda:not page.busy)
    assert shell.settings.value('incoming/backend_origin') == server.url
    assert page.auth is auth and 'pending' in panel.status.text()
    assert '"pending_revocation": true' in auth.store.value
    server.code = 200
    panel.save_button.click()
    wait_until(lambda:not page.busy)
    assert auth.store.value is None
    assert shell.settings.value('incoming/backend_origin') == 'http://127.0.0.1:8001'
    assert page.connect_button.isEnabled()
    app.processEvents()
