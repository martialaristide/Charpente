"""A local key vault for release signing: Ed25519 keys stored encrypted under a passphrase.

The vault file holds the 32-byte Ed25519 seed masked with a pad derived from the passphrase by scrypt (a memory-hard KDF)
and a random salt, plus the public key. A pad used exactly once per salt is a sound way to protect a fixed 32-byte secret,
and the stored public key detects a wrong passphrase (the recomputed public key would not match), so there is no
home-made cipher and no way to mistake garbage for a key. The passphrase comes from `CHARPENTE_KEY_PASSPHRASE` or a
prompt -- never from a file or the command line. Keys never leave `~/.charpente/keys/` and are never printed.

The signing primitive is the pure-Python Ed25519 already used for module signatures (RFC 8032 test vectors verified).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..dsl.trust import config_dir
from ..errors import ChError
from ..modules import signing

SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PASSPHRASE_ENV = "CHARPENTE_KEY_PASSPHRASE"


def keys_dir() -> Path:
    return config_dir() / "keys"


def _path(name: str) -> Path:
    if not _NAME.match(name):
        raise ChError("CH8016", reason=f"{name!r} is not a valid key name (letters, digits, . _ -)")
    return keys_dir() / f"{name}.key.json"


def _pad(passphrase: str, salt: bytes, params: Dict[str, int]) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                          maxmem=128 * params["n"] * params["r"] * 2, dklen=32)


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def create(name: str, passphrase: str, *, seed: Optional[bytes] = None, params: Optional[Dict[str, int]] = None) -> str:
    """Generate (or import, with `seed`) a key and store it; returns the public key in hex. Refuses to overwrite."""
    if len(passphrase) < 8:
        raise ChError("CH8016", reason="the key passphrase must be at least 8 characters")
    path = _path(name)
    if path.exists():
        raise ChError("CH8016", reason=f"a key named {name!r} already exists ({path}); choose another name")
    seed = seed if seed is not None else secrets.token_bytes(32)
    params = params or dict(SCRYPT)
    salt = secrets.token_bytes(16)
    public = signing.public_key(seed)
    record = {"version": 1, "kdf": "scrypt", **params, "salt": salt.hex(), "public": public.hex(),
              "blob": _xor(seed, _pad(passphrase, salt, params)).hex()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return public.hex()


def _load(name: str) -> Dict[str, object]:
    path = _path(name)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ChError("CH8016", reason=f"no key named {name!r} (create one with `charpente sign init {name}`)") from None
    except ValueError as exc:
        raise ChError("CH8016", reason=f"the key file {path} is damaged: {exc}") from exc
    if not isinstance(record, dict) or record.get("kdf") != "scrypt":
        raise ChError("CH8016", reason=f"the key file {path} has an unknown format")
    return record


def public_key(name: str) -> str:
    return str(_load(name)["public"])


def unlock(name: str, passphrase: str) -> bytes:
    """The 32-byte Ed25519 seed. A wrong passphrase raises instead of returning a wrong key."""
    record = _load(name)
    params = {"n": int(record["n"]), "r": int(record["r"]), "p": int(record["p"])}  # type: ignore[call-overload]
    seed = _xor(bytes.fromhex(str(record["blob"])), _pad(passphrase, bytes.fromhex(str(record["salt"])), params))
    if signing.public_key(seed).hex() != record["public"]:
        raise ChError("CH8016", reason="wrong passphrase for this key")
    return seed


def passphrase(prompt: str = "Key passphrase: ", *, env: Optional[Dict[str, str]] = None,
               ask: Callable[[str], str] = getpass.getpass) -> str:
    env = dict(os.environ) if env is None else env
    if env.get(PASSPHRASE_ENV):
        return env[PASSPHRASE_ENV]
    import sys

    if not sys.stdin.isatty():
        raise ChError("CH8016", reason=f"the key passphrase is needed: set ${PASSPHRASE_ENV} (CI) or run interactively")
    return ask(prompt)


def list_keys() -> List[Tuple[str, str]]:
    found = []
    if keys_dir().is_dir():
        for path in sorted(keys_dir().glob("*.key.json")):
            try:
                found.append((path.name[: -len(".key.json")], str(json.loads(path.read_text(encoding="utf-8"))["public"])))
            except (OSError, ValueError, KeyError):
                continue
    return found


def sign_bytes(name: str, message: bytes, phrase: str) -> Tuple[bytes, str]:
    """(signature, key id) of `message` signed with the stored key."""
    seed = unlock(name, phrase)
    public = signing.public_key(seed)
    return signing.sign(seed, message), signing.key_id(public)


def verify_bytes(public_hex: str, message: bytes, signature: bytes) -> bool:
    try:
        return signing.verify(bytes.fromhex(public_hex), message, signature)
    except ValueError:
        return False
