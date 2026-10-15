"""Versioned scrypt password hashes; standard-library implementation."""
import hashlib
import hmac
import secrets

# OWASP scrypt baseline: N=2^17, r=8, p=1 (~128 MiB per verification).
N, R, P = 2**17, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=N, r=R, p=P, maxmem=256*1024*1024, dklen=32)
    return f"scrypt${N}${R}${P}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = stored.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (N, R, P):
            return False
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=N, r=R, p=P, maxmem=256*1024*1024, dklen=32)
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
