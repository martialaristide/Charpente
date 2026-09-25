import json

import pytest

from charpente.modules import signing
from charpente.modules.api import SIGNATURE_NAME

# RFC 8032, section 7.1 (test vectors 1 and 2).
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


@pytest.mark.parametrize("secret,public,message,signature", VECTORS)
def test_rfc8032_vectors(secret, public, message, signature):
    secret_b, msg = bytes.fromhex(secret), bytes.fromhex(message)
    assert signing.public_key(secret_b).hex() == public
    assert signing.sign(secret_b, msg).hex() == signature
    assert signing.verify(bytes.fromhex(public), msg, bytes.fromhex(signature))


def test_verification_rejects_tampering():
    secret = bytes(range(32))
    public = signing.public_key(secret)
    sig = signing.sign(secret, b"hello")
    assert signing.verify(public, b"hello", sig)
    assert not signing.verify(public, b"hellO", sig)
    assert not signing.verify(public, b"hello", sig[:-1] + bytes([sig[-1] ^ 1]))
    assert not signing.verify(signing.public_key(bytes(32)), b"hello", sig)
    assert not signing.verify(public, b"hello", sig[:10])
    assert not signing.verify(b"short", b"hello", sig)


def test_malformed_points_never_verify_or_crash():
    assert not signing.verify(b"\xff" * 32, b"m", b"\x00" * 64)
    assert not signing.verify(bytes(32), b"m", b"\xff" * 64)


def test_tree_digest_is_deterministic_and_content_sensitive(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"1")
    d1 = signing.tree_digest(tmp_path)
    (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"2")           # ignored
    (tmp_path / SIGNATURE_NAME).write_text("whatever")                   # ignored
    assert signing.tree_digest(tmp_path) == d1
    (tmp_path / "a.py").write_text("x = 2")
    assert signing.tree_digest(tmp_path) != d1
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "sub" / "c.txt").write_text("new file")
    assert signing.tree_digest(tmp_path) != d1


def test_sign_then_check_states(tmp_path):
    (tmp_path / "m.py").write_text("code")
    secret = bytes(range(1, 33))
    pub = signing.public_key(secret)
    kid = signing.key_id(pub)

    assert signing.check_signature(tmp_path, {}).state == "unsigned"

    signing.write_signature(tmp_path, secret)
    ok = signing.check_signature(tmp_path, {kid: pub.hex()})
    assert ok.signed and ok.key == kid

    unknown = signing.check_signature(tmp_path, {})
    assert unknown.state == "unsigned" and kid in unknown.detail

    (tmp_path / "m.py").write_text("tampered")
    bad = signing.check_signature(tmp_path, {kid: pub.hex()})
    assert bad.state == "invalid" and "modified after signing" in bad.detail


def test_a_forged_signature_by_another_key_is_invalid(tmp_path):
    (tmp_path / "m.py").write_text("code")
    author = bytes(range(1, 33))
    attacker = bytes(range(2, 34))
    signing.write_signature(tmp_path, attacker)
    payload = json.loads((tmp_path / SIGNATURE_NAME).read_text())
    payload["key_id"] = signing.key_id(signing.public_key(author))         # claims to be the author
    (tmp_path / SIGNATURE_NAME).write_text(json.dumps(payload))
    result = signing.check_signature(tmp_path, {payload["key_id"]: signing.public_key(author).hex()})
    assert result.state == "invalid"


def test_corrupt_signature_file(tmp_path):
    (tmp_path / SIGNATURE_NAME).write_text("not json")
    assert signing.check_signature(tmp_path, {}).state == "invalid"


def test_user_trust_store(tmp_path):
    pub = signing.public_key(bytes(range(3, 35)))
    kid = signing.add_trusted_key(pub.hex())
    assert signing.trusted_keys()[kid] == pub.hex()
    with pytest.raises(ValueError):
        signing.add_trusted_key("abcd")
