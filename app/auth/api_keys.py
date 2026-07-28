import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import SecretStr

type RandomBytes = Callable[[int], bytes]

_API_KEY_PATTERN = re.compile(r"^evk_([0-9a-f]{12})_([A-Za-z0-9_-]{40,128})$")
_SCRYPT_VERSION = "1"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16
_SCRYPT_MAXMEM = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class GeneratedAPIKey:
    plaintext: SecretStr
    prefix: str
    key_hash: str


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def extract_key_prefix(plaintext: str) -> str | None:
    match = _API_KEY_PATTERN.fullmatch(plaintext)
    if match is None:
        return None
    return f"evk_{match.group(1)}"


def hash_api_key(plaintext: str, *, salt: bytes) -> str:
    if len(salt) != _SCRYPT_SALT_BYTES:
        raise ValueError(f"scrypt salt must be {_SCRYPT_SALT_BYTES} bytes")
    digest = hashlib.scrypt(
        plaintext.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            _SCRYPT_VERSION,
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _encode_bytes(salt),
            _encode_bytes(digest),
        )
    )


def verify_api_key(plaintext: str, encoded_hash: str) -> bool:
    try:
        algorithm, version, n, r, p, encoded_salt, encoded_digest = encoded_hash.split("$")
        if (
            algorithm != "scrypt"
            or version != _SCRYPT_VERSION
            or int(n) != _SCRYPT_N
            or int(r) != _SCRYPT_R
            or int(p) != _SCRYPT_P
        ):
            return False
        salt = _decode_bytes(encoded_salt)
        expected_digest = _decode_bytes(encoded_digest)
        if len(salt) != _SCRYPT_SALT_BYTES or len(expected_digest) != _SCRYPT_DKLEN:
            return False
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.scrypt(
        plaintext.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_DKLEN,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def generate_api_key(*, random_bytes: RandomBytes = secrets.token_bytes) -> GeneratedAPIKey:
    prefix = f"evk_{random_bytes(6).hex()}"
    secret = _encode_bytes(random_bytes(32))
    plaintext = f"{prefix}_{secret}"
    key_hash = hash_api_key(plaintext, salt=random_bytes(_SCRYPT_SALT_BYTES))
    return GeneratedAPIKey(
        plaintext=SecretStr(plaintext),
        prefix=prefix,
        key_hash=key_hash,
    )
