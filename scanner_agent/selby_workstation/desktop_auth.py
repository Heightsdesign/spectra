"""First-party native HTTPS session login; no OAuth/token protocol or browser scraping."""
from dataclasses import dataclass, field, asdict
from http.cookiejar import CookieJar
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from .incoming import NoRedirect, PreviewClient, PreviewError
from .credential_store import WindowsCredentialStore, CredentialStoreError


@dataclass
class SessionCredential:
    cookie_name: str
    expires_at: int
    token: str = field(repr=False)
    pending_revocation: bool = False

    def encode(self):
        return json.dumps({'version': 1, **asdict(self)})

    @classmethod
    def decode(cls, value, connection):
        try:
            data = json.loads(value)
            if set(data) != {'version', 'cookie_name', 'expires_at', 'token', 'pending_revocation'} or data.pop('version') != 1:
                raise ValueError()
            if (data['cookie_name'] != connection.cookie_name or type(data['expires_at']) is not int
                or type(data['pending_revocation']) is not bool or not isinstance(data['token'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data['token'])):
                raise ValueError()
            return cls(**data)
        except (ValueError, TypeError, KeyError):
            raise PreviewError('Invalid saved session. Sign out and sign in again.', kind='storage') from None


class AuthTransport:
    """Only existing authentication writes are allowed; no intake mutation transport."""
    def __init__(self, connection, timeout=12):
        self.connection, self.timeout = connection, timeout
        self.jar = CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.jar))

    def request(self, path, payload=None, credential=None, csrf=None):
        allowed = {'/api/auth/login': 'POST', '/api/auth/logout': 'POST', '/api/auth/csrf': 'GET'}
        method = 'POST' if payload is not None else 'GET'
        if allowed.get(path) != method:
            raise PreviewError('Unsupported desktop authentication operation.')
        headers = {'Accept': 'application/json', 'Cache-Control': 'no-store'}
        if payload is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': self.connection.auth_origin, 'X-Spectra-Client': '1'})
        if credential:
            headers['Cookie'] = f'{credential.cookie_name}={credential.token}'
        if csrf:
            headers['X-CSRF-Token'] = csrf
        request = Request(self.connection.backend_origin + path, method=method, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise PreviewError('Authentication service returned an unexpected response.')
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise PreviewError('Authentication response exceeds its limit.')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except HTTPError as exc:
            messages = {401: 'Invalid email or password.' if path.endswith('/login') else 'Session expired or revoked. Sign in again.',
                403: 'Authentication security check failed. Ask an administrator to verify connection settings.',
                422: 'Enter a valid email and password.', 429: 'Too many sign-in attempts. Wait before retrying.'}
            raise PreviewError(messages.get(exc.code, 'Authentication service unavailable. Try again later.'),
                               disconnect=exc.code == 401, kind='auth') from None
        except (URLError, OSError, TimeoutError):
            raise PreviewError('Offline: sign-in service unreachable or TLS verification failed. Local modules remain available.', kind='offline') from None
        except (ValueError, UnicodeError):
            raise PreviewError('Invalid authentication response.', kind='auth') from None

    def login(self, email, password):
        self.request('/api/auth/login', {'email': email, 'password': password})
        cookies = [cookie for cookie in self.jar if cookie.name == self.connection.cookie_name]
        if len(cookies) != 1:
            raise PreviewError('Expected secure session was not issued. Check environment settings.', kind='auth')
        cookie = cookies[0]
        if (not re.fullmatch(r'[A-Za-z0-9_-]{43}', cookie.value) or type(cookie.expires) is not int
            or cookie.expires <= time.time() or cookie.path != '/' or not cookie.has_nonstandard_attr('HttpOnly')
            or (self.connection.environment == 'production' and (not cookie.secure or cookie.domain_specified))):
            raise PreviewError('Backend session did not meet desktop security requirements.', kind='auth')
        return SessionCredential(cookie.name, cookie.expires, cookie.value)

    def revoke(self, credential):
        try:
            csrf = self.request('/api/auth/csrf', credential=credential).get('csrf_token')
            if not isinstance(csrf, str) or not re.fullmatch('[a-f0-9]{64}', csrf):
                raise PreviewError('Invalid authentication security response.')
            self.request('/api/auth/logout', {}, credential, csrf)
        except PreviewError as exc:
            if exc.disconnect:  # Already expired/revoked/disabled credentials cannot authenticate.
                return
            raise


class DesktopAuthService:
    def __init__(self, connection, store=None, timeout=12):
        self.connection = connection
        self.store = store if store is not None else WindowsCredentialStore(connection.credential_target)
        self.timeout = timeout
        self._lock = threading.RLock()
        self._current = None

    def intake_client(self):
        from .intake_client import IntakeClient
        with self._lock:
            credential = self._current
            if credential is None or credential.pending_revocation or credential.expires_at <= time.time():
                raise PreviewError('Session expired. Sign in again before physical intake.', disconnect=True, kind='expired')
            return IntakeClient(self.connection, credential, self.timeout)

    def _stored(self):
        value = self.store.load()
        if value is None:
            return None
        credential = SessionCredential.decode(value, self.connection)
        if credential.expires_at <= time.time():
            self.store.delete()
            return None
        return credential

    def _revoke(self, credential):
        try:
            AuthTransport(self.connection, self.timeout).revoke(credential)
        except PreviewError:
            credential.pending_revocation = True
            self.store.save(credential.encode())
            raise
        self.store.delete()

    def _authorized(self, credential):
        client = PreviewClient(self.connection.backend_origin, credential.token, credential.cookie_name, self.timeout)
        actor = client.staff()  # Server-side role check, repeated by every business GET.
        return client, actor

    def sign_in(self, email, password, cancelled=None):
        with self._lock:
            try:
                if cancelled is not None and cancelled.is_set():
                    return None
                previous = self._current or self._stored()
                if previous:
                    self._current = None
                    self._revoke(previous)  # Never overwrite a pending/unrevoked previous session.
                if cancelled is not None and cancelled.is_set():
                    return None
                credential = AuthTransport(self.connection, self.timeout).login(email, password)
                try:
                    result = self._authorized(credential)
                    if cancelled is not None and cancelled.is_set():
                        self._revoke(credential)
                        return None
                    self.store.save(credential.encode())
                except (PreviewError, CredentialStoreError):
                    try:
                        self._revoke(credential)
                    except (PreviewError, CredentialStoreError):
                        pass  # No business client is returned on failed authorization/storage.
                    raise
                self._current = credential
                return result
            except CredentialStoreError as exc:
                raise PreviewError(str(exc), kind='storage') from None

    def restore(self):
        with self._lock:
            try:
                self._current = None
                credential = self._stored()
                if credential is None:
                    return None
                if credential.pending_revocation:
                    self._revoke(credential)
                    return None
                try:
                    result = self._authorized(credential)
                except PreviewError as exc:
                    if exc.disconnect:
                        self._revoke(credential)
                    raise
                self._current = credential
                return result
            except CredentialStoreError as exc:
                raise PreviewError(str(exc), kind='storage') from None

    def sign_out(self):
        with self._lock:
            try:
                try:
                    credential = self._current or self._stored()
                except PreviewError as exc:
                    if exc.kind != 'storage':
                        raise
                    self.store.delete()
                    raise PreviewError('Invalid saved session removed. Sign in again; server revocation could not be verified.', kind='storage') from None
                self._current = None
                if credential:
                    try:
                        self._revoke(credential)
                    except PreviewError:
                        return False  # Pending revocation is stored securely and never resumed.
                return True
            except CredentialStoreError as exc:
                raise PreviewError(str(exc), kind='storage') from None
