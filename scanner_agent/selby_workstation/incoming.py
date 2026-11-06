"""GET-only staff preview client. No local registry or evidence dependencies."""

import ipaddress
import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class PreviewError(Exception):
    def __init__(self, message, disconnect=False, kind='server'):
        super().__init__(message)
        self.disconnect = disconnect
        self.kind = kind


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a session to a different origin or a sign-in redirect.
        return None


def backend_url(value):
    value = value.strip()
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        if (parts.scheme not in ('http', 'https') or not host or parts.username
                or parts.password or parts.path not in ('', '/') or parts.query
                or parts.fragment or any(c.isspace() for c in value)):
            raise ValueError()
        local = host == 'localhost'
        try:
            local = local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parts.scheme == 'http' and not local:
            raise PreviewError('Use HTTPS for every non-local backend.')
        # Read port to validate it; retain IPv6 brackets from the original netloc.
        if port == 0:
            raise ValueError()
        return f'{parts.scheme}://{parts.netloc}'
    except ValueError:
        raise PreviewError('Enter a backend origin, for example https://backend.example.org.') from None


class PreviewClient:
    """Existing session-cookie authentication; credentials never persisted or logged."""

    def __init__(self, origin, token, cookie_name='__Host-spectra_session', timeout=12):
        self.origin = backend_url(origin)
        if cookie_name not in ('spectra_session', '__Host-spectra_session'):
            raise PreviewError('Unsupported session cookie name.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise PreviewError('Invalid session credential. Sign in again.')
        if cookie_name.startswith('__Host-') and not self.origin.startswith('https://'):
            raise PreviewError('Production session cookies require HTTPS.')
        self._cookie = f'{cookie_name}={token}'
        self.timeout = timeout

    def _get(self, path, image=False):
        # Only private callers construct allowlisted intake paths; no arbitrary URLs.
        request = Request(self.origin + path, method='GET', headers={
            'Cookie': self._cookie, 'Accept': 'image/jpeg,image/png' if image else 'application/json', 'Cache-Control': 'no-store',
        })
        try:
            # Avoid ambient proxy configuration forwarding the operator credential.
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise PreviewError('Unexpected backend response. Check the backend origin.')
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise PreviewError('Preview response is too large. Narrow the search.')
                if image:
                    if response.headers.get_content_type() not in ('image/jpeg', 'image/png'):
                        raise PreviewError('Backend returned an unsupported customer photograph.')
                    return raw
                return json.loads(raw)
        except HTTPError as exc:
            messages = {
                401: 'Session expired or invalid. Sign in again.',
                403: 'Operator or administrator access is required. Sign in with an authorized account.',
                404: 'Submission or preview endpoint not found. Refresh the list or check the backend origin.',
                429: 'Too many requests. Wait before refreshing.',
            }
            raise PreviewError(messages.get(exc.code, 'Backend request failed. Try refreshing later.'),
                               disconnect=exc.code in (401, 403),
                               kind='expired' if exc.code == 401 else 'permission' if exc.code == 403 else 'server') from None
        except (URLError, OSError, TimeoutError):
            raise PreviewError('Offline: backend unreachable or TLS connection failed. Local modules remain available.', kind='offline') from None
        except (ValueError, UnicodeError):
            raise PreviewError('Backend returned an invalid preview response.') from None

    def staff(self):
        result = self._get('/internal/intake/me')
        if not isinstance(result, dict) or result.get('role') not in ('operator', 'admin'):
            raise PreviewError('Operator or administrator access is required.', disconnect=True)
        return result

    def photo(self, submission_id, photo):
        """Bounded private GET; customer uploads never enter local grading storage."""
        sid, identifier = str(UUID(submission_id)), str(UUID(photo['id']))
        if photo.get('provenance') != 'customer_pre_shipment' or photo.get('identity_verified') is not False:
            raise PreviewError('Unexpected customer photograph provenance.')
        data = self._get(f'/internal/intake/submissions/{sid}/pre-shipment-photos/{identifier}', image=True)
        if len(data) != photo.get('file_size') or hashlib.sha256(data).hexdigest() != photo.get('sha256'):
            raise PreviewError('Customer photograph integrity check failed.')
        return data

    def submissions(self, search='', offset=0):
        query = urlencode({'search': search.strip(), 'offset': offset, 'limit': 50})
        result = self._get('/internal/intake/submissions?' + query)
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise PreviewError('Backend returned an invalid submission list.')
        for row in result:
            self._summary(row)
        return result

    @staticmethod
    def _summary(row):
        required = ('id', 'reference', 'status', 'declared_quantity', 'received_quantity')
        if any(key not in row for key in required):
            raise PreviewError('Backend returned incomplete submission data.')
        try:
            UUID(row['id'])
            if (not all(isinstance(row[k], str) for k in ('reference', 'status'))
                    or not all(type(row[k]) is int and row[k] >= 0
                               for k in ('declared_quantity', 'received_quantity'))):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise PreviewError('Backend returned invalid submission data.') from None

    def submission(self, identifier):
        identifier = str(UUID(identifier))
        result = self._get('/internal/intake/submissions/' + identifier)
        if not isinstance(result, dict):
            raise PreviewError('Backend returned an invalid submission detail.')
        self._summary(result)
        for field in ('entries', 'cards', 'parcels', 'discrepancies'):
            if not isinstance(result.get(field), list) or any(not isinstance(r, dict) for r in result[field]):
                raise PreviewError('Backend returned incomplete submission detail.')
        if result['id'] != identifier:
            raise PreviewError('Backend returned a different submission.')
        return result
