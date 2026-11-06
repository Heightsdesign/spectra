"""Nonsecret Incoming connection preferences in the existing desktop.ini/env."""
from dataclasses import dataclass
import hashlib
import os
import json
from urllib.error import URLError, HTTPError
from urllib.request import build_opener, ProxyHandler, Request
from .incoming import backend_url, PreviewError, NoRedirect


@dataclass(frozen=True)
class DesktopConnection:
    environment: str
    backend_origin: str
    auth_origin: str

    def __post_init__(self):
        if self.environment not in ('development', 'production'):
            raise PreviewError('Incoming Orders is not configured. Choose the intended environment and origins in Settings, then Save connection.')
        for name in ('backend_origin', 'auth_origin'):
            value = backend_url(getattr(self, name))
            if self.environment == 'production' and not value.startswith('https://'):
                raise PreviewError('Production connections require HTTPS for backend and portal origins.')
            object.__setattr__(self, name, value)

    @property
    def cookie_name(self):
        return '__Host-spectra_session' if self.environment == 'production' else 'spectra_session'

    @property
    def credential_target(self):
        scope = f'{self.environment}|{self.backend_origin}|{self.auth_origin}'
        return 'SELBY/Incoming/v1/' + hashlib.sha256(scope.encode()).hexdigest()

    def check(self, timeout=3):
        """Unauthenticated, bounded health check; never send a saved credential."""
        try:
            request = Request(self.backend_origin + '/api/health', headers={'Accept': 'application/json'})
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(65537)
                if response.status != 200 or len(raw) > 65536 or json.loads(raw) != {'status': 'ok', 'application': 'SPECTRA'}:
                    raise ValueError()
        except HTTPError:
            raise PreviewError('Backend reachable, but the SELBY health endpoint is unavailable. Check the origin and backend version.') from None
        except (URLError, OSError, TimeoutError):
            raise PreviewError('Backend unreachable or TLS verification failed. Check the address and start FastAPI. Local modules remain available.', kind='offline') from None
        except (ValueError, UnicodeError):
            raise PreviewError('Backend reachable, but its health response is not recognized. Verify this is the intended SELBY backend.') from None
        return 'Backend reachable. Authentication required unless already signed in. Health does not verify database access or staff permissions.'

    @classmethod
    def load(cls, values=None, environ=None):
        values, environ = values or {}, os.environ if environ is None else environ
        def value(key, env, default=''):
            return str(environ.get(env, values.get('incoming/' + key, default))).strip()
        environment = value('environment', 'SELBY_ENVIRONMENT')
        if not environment:
            return None
        local = environment == 'development'
        return cls(environment, value('backend_origin', 'SELBY_BACKEND_ORIGIN', 'http://127.0.0.1:8000' if local else ''),
                   value('auth_origin', 'SELBY_AUTH_ORIGIN', 'http://127.0.0.1:3000' if local else ''))
