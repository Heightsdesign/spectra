import json
import os
import threading
import time
from uuid import uuid4
from unittest.mock import patch
import pytest
from selby_workstation.connection import DesktopConnection
from selby_workstation.credential_store import WindowsCredentialStore, CredentialStoreError
from selby_workstation.desktop_auth import DesktopAuthService, SessionCredential, AuthTransport
from selby_workstation.incoming import PreviewClient, PreviewError
from incoming_fixtures import MemoryCredentials
from test_selby_incoming import server, TOKEN, connect, wait_until, SUMMARY  # noqa: F401


def service(server, store=None):
    return DesktopAuthService(DesktopConnection('development',server.url,'http://127.0.0.1:3000'),store or MemoryCredentials(),timeout=0.5)


def test_login_restore_logout_revocation_and_no_intake_writes(server):
    vault=MemoryCredentials();auth=service(server,vault)
    client,actor=auth.sign_in('operator@example.invalid','desktop-test-pass')
    assert actor['role']=='operator' and client.submissions()==[SUMMARY]
    assert 'desktop-test-pass' not in vault.value
    assert TOKEN not in repr(SessionCredential.decode(vault.value,auth.connection))
    restored,_=service(server,vault).restore()
    assert restored.submissions()==[SUMMARY]
    assert auth.sign_out() and server.revoked and vault.value is None
    with pytest.raises(PreviewError):
        client.submissions()
    assert all(method=='GET' or path in ('/api/auth/login','/api/auth/logout') for method,path,_ in server.requests)
    with pytest.raises(PreviewError,match='Unsupported'):
        AuthTransport(auth.connection).request('/internal/intake/submissions',{})


def test_bad_password_and_unauthorized_role_never_saved(server):
    auth=service(server)
    with pytest.raises(PreviewError,match='Invalid email or password'):
        auth.sign_in('operator@example.invalid','wrong')
    assert auth.store.value is None
    server.role=None
    with pytest.raises(PreviewError,match='Operator or administrator'):
        auth.sign_in('operator@example.invalid','desktop-test-pass')
    assert auth.store.value is None and server.revoked


def test_expiration_and_server_revocation_clear_saved_credentials(server):
    auth=service(server)
    auth.sign_in('operator@example.invalid','desktop-test-pass')
    record=SessionCredential.decode(auth.store.value,auth.connection);record.expires_at=int(time.time())-1
    auth.store.save(record.encode());assert service(server,auth.store).restore() is None
    assert auth.store.value is None
    auth.sign_in('operator@example.invalid','desktop-test-pass');server.code=401
    with pytest.raises(PreviewError):
        service(server,auth.store).restore()
    assert auth.store.value is None


def test_offline_resume_preserves_secure_record_but_offline_logout_never_resumes_it(server):
    auth=service(server);auth.sign_in('operator@example.invalid','desktop-test-pass')
    original=auth.store.value
    server.delay=0.15
    resumed=DesktopAuthService(auth.connection,auth.store,timeout=0.02)
    with pytest.raises(PreviewError) as error:
        resumed.restore()
    assert error.value.kind=='offline' and auth.store.value==original
    with patch.object(AuthTransport,'revoke',side_effect=PreviewError('Offline',kind='offline')):
        assert auth.sign_out() is False
        assert json.loads(auth.store.value)['pending_revocation'] is True
    server.delay=0
    assert service(server,auth.store).restore() is None
    assert server.revoked and auth.store.value is None


def test_cancelled_login_revokes_fresh_session(server):
    auth=service(server);cancelled=threading.Event()
    login=AuthTransport.login
    def late_cancel(transport,email,password):
        result=login(transport,email,password);cancelled.set();return result
    with patch.object(AuthTransport,'login',late_cancel):
        assert auth.sign_in('operator@example.invalid','desktop-test-pass',cancelled) is None
    assert server.revoked and auth.store.value is None


def test_cancelled_before_login_never_sends_credentials(server):
    auth=service(server);cancelled=threading.Event();cancelled.set()
    assert auth.sign_in('operator@example.invalid','desktop-test-pass',cancelled) is None
    assert server.requests==[] and auth.store.value is None


def test_secure_storage_failure_has_no_plaintext_fallback(server):
    class BrokenVault(MemoryCredentials):
        def save(self,value):
            raise CredentialStoreError('Secure storage unavailable')
    vault=BrokenVault();auth=service(server,vault)
    with pytest.raises(PreviewError,match='Secure storage'):
        auth.sign_in('operator@example.invalid','desktop-test-pass')
    assert server.revoked and vault.value is None


def test_corrupt_store_can_be_removed_without_echoing_secrets(server):
    vault=MemoryCredentials();vault.value='PRIVATE-MALFORMED-SESSION'
    auth=service(server,vault)
    with pytest.raises(PreviewError) as error:
        auth.restore()
    assert 'PRIVATE' not in str(error.value)
    with pytest.raises(PreviewError,match='removed'):
        auth.sign_out()
    assert vault.value is None


def test_redirect_login_never_forwards_password(server):
    auth=service(server)
    server.redirect=True
    with pytest.raises(PreviewError):
        auth.sign_in('operator@example.invalid','desktop-test-pass')
    assert [(method,path) for method,path,_ in server.requests]==[('POST','/api/auth/login')]
    assert auth.store.value is None


def test_connection_configuration_and_scope_isolation():
    assert DesktopConnection.load({},environ={}) is None
    local=DesktopConnection.load({'incoming/environment':'development'},environ={})
    assert local.backend_origin=='http://127.0.0.1:8000'
    with pytest.raises(PreviewError):
        DesktopConnection('production','http://localhost:8000','https://portal.example')
    with pytest.raises(PreviewError):
        DesktopConnection('development','http://remote.example','http://localhost:3000')
    remote=DesktopConnection('production','https://backend.example','https://portal.example')
    assert remote.cookie_name=='__Host-spectra_session'
    assert remote.credential_target!=local.credential_target
    assert remote.credential_target!=DesktopConnection('production','https://other.example','https://portal.example').credential_target


@pytest.mark.skipif(os.environ.get('SELBY_TEST_CREDENTIAL_MANAGER')!='1',reason='Explicit opt-in: isolated native Windows Credential Manager roundtrip')
def test_native_windows_credential_manager_roundtrip():
    target='SELBY/TestOnly/'+uuid4().hex
    vault=WindowsCredentialStore(target)
    try:
        assert vault.load() is None
        vault.save('synthetic-session-fixture')
        assert vault.load()=='synthetic-session-fixture'
        vault.save('replacement-fixture')
        assert vault.load()=='replacement-fixture'
    finally:
        vault.delete()
    assert vault.load() is None
