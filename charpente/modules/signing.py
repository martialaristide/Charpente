"""Module integrity and signatures.

* `tree_digest(dir)`: a deterministic SHA-256 over a module folder's files.
* Ed25519 (RFC 8032), implemented here in pure Python from the public
  specification so that verifying a signature needs no extra dependency.
  It is verified against the RFC's published test vectors (tests/test_signing.py).
  Signing is offered for module authors (`charpente module sign`); it is not
  constant-time and must not be used for anything else.
* A signature file `charpente-module.sig` holds `{"key_id", "digest", "signature"}`
  (hex). A module counts as *signed* only if the key is in the trust store:
  the official keys shipped with Charpente plus keys the user added.

Sigstore (keyless, transparency-log based) is the intended complement for
registry-hosted official modules; it needs network services and is not done here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from .api import SIGNATURE_NAME

# Public keys of Charpente's official module signers, key_id -> hex public key.
# Empty until the maintainer publishes the first signed registry release; users
# can add keys they trust with `charpente module trust-key`.
OFFICIAL_KEYS: Dict[str, str] = {}

_IGNORED_DIRS = {"__pycache__", ".git", ".hg", ".svn"}


def tree_digest(directory: Path) -> str:
    """SHA-256 of relative paths and contents, in sorted order. The signature
    file is excluded (it signs this digest)."""
    h = hashlib.sha256()
    root = Path(directory)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if rel.name == SIGNATURE_NAME or any(part in _IGNORED_DIRS for part in rel.parts):
            continue
        h.update(rel.as_posix().encode("utf-8") + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


# ---------------------------------------------------------------- Ed25519 (RFC 8032)
_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
Point = Tuple[int, int, int, int]


def _add(a: Point, b: Point) -> Point:
    A, B = (a[1] - a[0]) * (b[1] - b[0]) % _P, (a[1] + a[0]) * (b[1] + b[0]) % _P
    C, D = 2 * a[3] * b[3] * _D % _P, 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, point: Point) -> Point:
    result: Point = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a: Point, b: Point) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y: int, sign: int) -> Optional[int]:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
assert _GX is not None
_G: Point = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(point: Point) -> bytes:
    zinv = _inv(point[2])
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes) -> Optional[Point]:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _sha512_modq(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _Q


def _expand(secret: bytes) -> Tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("an Ed25519 secret key is 32 bytes")
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return _compress(_mul(a, _G))


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    pub = _compress(_mul(a, _G))
    r = _sha512_modq(prefix + message)
    rs = _compress(_mul(r, _G))
    h = _sha512_modq(rs + pub + message)
    s = (r + h * a) % _Q
    return rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a_point = _decompress(public)
    r_point = _decompress(signature[:32])
    if a_point is None or r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(signature[:32] + public + message)
    return _equal(_mul(s, _G), _add(r_point, _mul(h, a_point)))


# ----------------------------------------------------------------- trust store
def key_id(public: bytes) -> str:
    return hashlib.sha256(public).hexdigest()[:16]


def _trusted_keys_file() -> Path:
    from ..dsl.trust import config_dir

    return config_dir() / "trusted_keys.json"


def trusted_keys() -> Dict[str, str]:
    """key_id -> hex public key: the official keys plus the user's own."""
    keys = dict(OFFICIAL_KEYS)
    try:
        data = json.loads(_trusted_keys_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            keys.update({str(k): str(v) for k, v in data.items()})
    except (OSError, ValueError):
        pass
    return keys


def add_trusted_key(public_hex: str) -> str:
    public = bytes.fromhex(public_hex)
    if len(public) != 32:
        raise ValueError("an Ed25519 public key is 32 bytes (64 hex characters)")
    kid = key_id(public)
    path = _trusted_keys_file()
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[kid] = public_hex.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return kid


def write_signature(directory: Path, secret: bytes) -> Path:
    """Sign a module folder with `secret` (module authors)."""
    digest = tree_digest(directory)
    pub = public_key(secret)
    payload = {"key_id": key_id(pub), "digest": digest,
               "signature": sign(secret, digest.encode("ascii")).hex()}
    path = Path(directory) / SIGNATURE_NAME
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


class SignatureStatus:
    """Result of checking a module folder's signature."""

    def __init__(self, state: str, detail: str = "", key: str = "") -> None:
        self.state = state          # 'signed' | 'unsigned' | 'invalid'
        self.detail = detail
        self.key = key

    @property
    def signed(self) -> bool:
        return self.state == "signed"


def check_signature(directory: Path, keys: Optional[Dict[str, str]] = None) -> SignatureStatus:
    trusted = trusted_keys() if keys is None else keys
    sig_file = Path(directory) / SIGNATURE_NAME
    if not sig_file.exists():
        return SignatureStatus("unsigned", "no signature file")
    try:
        payload = json.loads(sig_file.read_text(encoding="utf-8"))
        kid, claimed, signature = str(payload["key_id"]), str(payload["digest"]), bytes.fromhex(payload["signature"])
    except (OSError, ValueError, KeyError, TypeError):
        return SignatureStatus("invalid", "unreadable signature file")
    actual = tree_digest(directory)
    if claimed != actual:
        return SignatureStatus("invalid", "the files do not match the signed digest (modified after signing?)")
    public_hex = trusted.get(kid)
    if public_hex is None:
        return SignatureStatus("unsigned", f"signed by unknown key {kid}", kid)
    if not verify(bytes.fromhex(public_hex), actual.encode("ascii"), signature):
        return SignatureStatus("invalid", f"the signature does not verify with key {kid}", kid)
    return SignatureStatus("signed", "", kid)
