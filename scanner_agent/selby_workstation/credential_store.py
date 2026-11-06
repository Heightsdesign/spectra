"""Windows Credential Manager, current Windows user, local-machine persistence.

No file/SQLite/plaintext fallback. No credential enumeration.
"""
import ctypes
from ctypes import wintypes
import sys


class CredentialStoreError(Exception):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class WindowsCredentialStore:
    def __init__(self, target):
        self.target = target

    def _api(self):
        if sys.platform != 'win32':
            raise CredentialStoreError('Secure session storage requires Windows Credential Manager on this version.')
        try:
            api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        except OSError:
            raise CredentialStoreError('Windows secure session storage is unavailable.') from None
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def save(self, value):
        data = value.encode('utf-8')
        if len(data) > 2560:
            raise CredentialStoreError('Session record exceeds secure storage limits.')
        api = self._api()
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        record = _Credential(Type=1, TargetName=self.target, CredentialBlobSize=len(data),
            CredentialBlob=buffer, Persist=2, UserName='SELBY session')
        try:
            if not api.CredWriteW(ctypes.byref(record), 0):
                raise CredentialStoreError('Windows secure session storage is unavailable. Sign-in was not saved.')
        finally:
            ctypes.memset(buffer, 0, len(data))

    def load(self):
        api = self._api()
        pointer = ctypes.POINTER(_Credential)()
        if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise CredentialStoreError('Windows secure session storage is unavailable.')
        try:
            size = pointer.contents.CredentialBlobSize
            if size > 2560:
                raise CredentialStoreError('Invalid secure session record.')
            try:
                return ctypes.string_at(pointer.contents.CredentialBlob, size).decode('utf-8')
            except UnicodeError:
                raise CredentialStoreError('Invalid secure session record. Remove the SELBY credential and sign in again.') from None
        finally:
            api.CredFree(pointer)

    def delete(self):
        api = self._api()
        if not api.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialStoreError('Unable to remove the saved Windows session. Ask an administrator.')
