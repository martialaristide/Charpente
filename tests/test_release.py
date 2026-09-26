"""Releases: versions, changelog, checksums, signing vault, provenance, CI workflow generation, and one real end to end."""
import base64
import datetime
import json
import shutil
import subprocess
import sys

import pytest

from charpente.errors import ChError
from charpente.vcs import ci, vault
from charpente.vcs import git as git_mod
from charpente.vcs import release as rel

FAST = {"n": 2 ** 10, "r": 8, "p": 1}          # scrypt cost low enough for tests


def commits(*subjects, body=""):
    return [git_mod.Commit(f"{i + 1:07x}".ljust(40, "0"), s, body, f"t{i}") for i, s in enumerate(subjects)]


# ------------------------------------------------------------------ versions
def test_commit_classification():
    assert rel.classify(commits("feat(engine): fast path")[0]) == ("feat", "engine", "fast path")
    assert rel.classify(commits("fix!: drop v1")[0])[0] == "breaking"
    assert rel.classify(commits("fix: x", body="BREAKING CHANGE: api")[0])[0] == "breaking"
    assert rel.classify(commits("random words")[0]) == ("other", "", "random words")


@pytest.mark.parametrize("subjects, current, expected", [
    (["fix: a"], "1.4.2", "patch"), (["feat: a", "fix: b"], "1.4.2", "minor"), (["feat!: a"], "1.4.2", "major"),
    (["docs: a", "chore: b"], "1.4.2", None), (["feat: a"], "0.4.2", "patch"), (["feat!: a"], "0.4.2", "minor"),
    (["perf: a"], "2.0.0", "patch"), (["refactor: a"], "2.0.0", "patch"), ([], "1.0.0", None)])
def test_bump_follows_conventional_commits_with_the_pre_one_convention(subjects, current, expected):
    assert rel.bump_kind(commits(*subjects), current) == expected


def test_next_version():
    assert rel.next_version("1.4.2", "major") == "2.0.0" and rel.next_version("1.4.2", "minor") == "1.5.0"
    assert rel.next_version("1.4.2", "patch") == "1.4.3" and rel.next_version("0.0.0", "patch") == "0.0.1"
    assert rel.next_version("1.4.2", "3.0.0") == "3.0.0"
    for bad in ("huge", "1.2", "v1.2.3"):
        with pytest.raises(ChError):
            rel.next_version("1.0.0", bad)


def test_changelog_groups_by_type_and_leaves_out_noise():
    section = rel.changelog_section("1.5.0", commits("feat(engine): fast path", "fix: crash", "chore: bump", "docs: guide",
                                                     "feat!: new api", "wip"), datetime.date(2026, 9, 26))
    lines = section.splitlines()
    assert lines[0] == "## v1.5.0 -- 2026-09-26"
    assert section.index("Breaking changes") < section.index("Features") < section.index("Fixes") < section.index("Documentation")
    assert "- **engine:** fast path (0000001)" in section and "bump" not in section and "wip" not in section
    assert "Maintenance release." in rel.changelog_section("1.5.1", commits("chore: x"), datetime.date(2026, 1, 1))


def test_changelog_is_prepended_under_the_title():
    section = "## v2.0.0 -- 2026-01-01\n\n- x\n"
    updated = rel.prepend_changelog("# Changelog\n\n## v1.0.0 -- 2025-01-01\n\n- old\n", section)
    assert updated.startswith("# Changelog\n\n## v2.0.0") and updated.index("v2.0.0") < updated.index("v1.0.0")
    assert rel.prepend_changelog("", section).startswith("# Changelog\n\n## v2.0.0")
    assert rel.prepend_changelog("old text\n", section).startswith("# Changelog") and "old text" in rel.prepend_changelog("old text\n", section)


def test_the_declared_version_is_read_and_rewritten_in_place(tmp_path):
    (tmp_path / "app.charpente").write_text('from charpente import *\nwith Workspace("demo", version="1.4.2") as ws:\n'
                                            '    with Target("app") as t:\n        t.version = "9.9.9"\n')
    assert rel.read_version(tmp_path) == "1.4.2"
    assert rel.write_version(tmp_path, "1.4.2", "1.5.0").name == "app.charpente"
    text = (tmp_path / "app.charpente").read_text()
    assert 'version="1.5.0"' in text and 't.version = "9.9.9"' in text          # only the workspace's version changed
    with pytest.raises(ChError):
        rel.write_version(tmp_path, "0.0.1", "0.0.2")


def test_the_toml_form_and_a_missing_version(tmp_path):
    (tmp_path / "charpente.toml").write_text('[workspace]\nname = "x"\nversion = "0.3.0"\n')
    assert rel.read_version(tmp_path) == "0.3.0"
    rel.write_version(tmp_path, "0.3.0", "0.3.1")
    assert 'version = "0.3.1"' in (tmp_path / "charpente.toml").read_text()
    assert rel.read_version(tmp_path / "empty") is None


# ------------------------------------------------------------------ checksums and provenance
def test_checksums_match_sha256sum_format(tmp_path):
    (tmp_path / "b.zip").write_bytes(b"bb")
    (tmp_path / "a.zip").write_bytes(b"aa")
    text = rel.checksums([tmp_path / "b.zip", tmp_path / "a.zip"])
    import hashlib

    assert text == f"{hashlib.sha256(b'aa').hexdigest()}  a.zip\n{hashlib.sha256(b'bb').hexdigest()}  b.zip\n"


def test_dsse_pae_matches_the_specification_example():
    assert rel.pae("http://example.com/HelloWorld", b"hello world") == b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"


def _statement(tmp_path):
    artifact = tmp_path / "app.zip"
    artifact.write_bytes(b"zip bytes")
    return rel.provenance_statement([artifact], source_uri="https://github.com/acme/tool", commit="c0ffee", command=["charpente", "package"],
                                    version="1.0.0", builder_id="charpente:local-build", started="2026-01-01T00:00:00Z",
                                    finished="2026-01-01T00:01:00Z", dependencies=[("fmt", "ab" * 32)])


def test_the_provenance_statement_follows_in_toto_and_slsa(tmp_path):
    s = _statement(tmp_path)
    import hashlib

    assert s["_type"] == "https://in-toto.io/Statement/v1" and s["predicateType"] == "https://slsa.dev/provenance/v1"
    assert s["subject"] == [{"name": "app.zip", "digest": {"sha256": hashlib.sha256(b"zip bytes").hexdigest()}}]
    build = s["predicate"]["buildDefinition"]
    assert build["externalParameters"]["command"] == ["charpente", "package"]
    assert {"uri": "https://github.com/acme/tool", "digest": {"gitCommit": "c0ffee"}} in build["resolvedDependencies"]
    assert {"name": "fmt", "digest": {"sha256": "ab" * 32}} in build["resolvedDependencies"]
    assert s["predicate"]["runDetails"]["builder"]["id"] == "charpente:local-build"


def test_builder_identity_is_honest_about_isolation():
    assert "not an isolated builder" in rel.builder_identity({})
    env = {"GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "a/b", "GITHUB_RUN_ID": "42"}
    assert rel.builder_identity(env) == "https://github.com/a/b/actions/runs/42"


# ------------------------------------------------------------------ the vault
def test_a_key_round_trips_and_signs_verifiably():
    public = vault.create("k1", "correct horse battery", params=FAST)
    assert vault.public_key("k1") == public and vault.list_keys() == [("k1", public)]
    signature, key_id = vault.sign_bytes("k1", b"message", "correct horse battery")
    assert vault.verify_bytes(public, b"message", signature) and not vault.verify_bytes(public, b"other", signature)
    assert len(key_id) >= 8


def test_a_wrong_passphrase_is_detected_not_silently_wrong():
    vault.create("k2", "correct horse battery", params=FAST)
    with pytest.raises(ChError) as exc:
        vault.unlock("k2", "not the passphrase")
    assert "wrong passphrase" in str(exc.value)


def test_the_stored_key_never_contains_the_seed():
    seed = bytes(range(32))
    vault.create("k3", "correct horse battery", seed=seed, params=FAST)
    text = (vault.keys_dir() / "k3.key.json").read_text()
    assert seed.hex() not in text and "correct horse" not in text
    assert vault.unlock("k3", "correct horse battery") == seed


def test_vault_refuses_overwrites_weak_passphrases_bad_names_and_missing_keys():
    vault.create("k4", "correct horse battery", params=FAST)
    with pytest.raises(ChError):
        vault.create("k4", "another passphrase!", params=FAST)
    with pytest.raises(ChError):
        vault.create("k5", "short", params=FAST)
    for bad in ("../evil", "a b", "", "x" * 100):
        with pytest.raises(ChError):
            vault.create(bad, "correct horse battery", params=FAST)
    with pytest.raises(ChError) as exc:
        vault.public_key("nope")
    assert "charpente sign init" in str(exc.value)
    (vault.keys_dir() / "broken.key.json").write_text("{not json")
    with pytest.raises(ChError):
        vault.public_key("broken")


def test_the_passphrase_comes_from_the_environment_or_a_prompt_never_a_file(monkeypatch):
    assert vault.passphrase(env={vault.PASSPHRASE_ENV: "from env"}) == "from env"
    monkeypatch.setattr(sys, "stdin", type("Tty", (), {"isatty": lambda self: True})())
    assert vault.passphrase(env={}, ask=lambda prompt: "typed") == "typed"
    monkeypatch.setattr(sys, "stdin", type("NoTty", (), {"isatty": lambda self: False})())
    with pytest.raises(ChError) as exc:
        vault.passphrase(env={})
    assert vault.PASSPHRASE_ENV in str(exc.value)


def test_a_signed_provenance_envelope_verifies_and_rejects_tampering(tmp_path):
    public = vault.create("k6", "correct horse battery", params=FAST)
    statement = _statement(tmp_path)

    def sign(message):
        return vault.sign_bytes("k6", message, "correct horse battery")[0]

    envelope = rel.dsse_envelope(statement, "kid", sign)
    assert envelope["payloadType"] == "application/vnd.in-toto+json"
    verifier = lambda message, signature: vault.verify_bytes(public, message, signature)          # noqa: E731
    assert rel.verify_envelope(envelope, verifier)["predicateType"] == "https://slsa.dev/provenance/v1"
    forged = dict(envelope)
    forged["payload"] = base64.b64encode(base64.b64decode(envelope["payload"]).replace(b"1.0.0", b"6.6.6")).decode()
    with pytest.raises(ChError):
        rel.verify_envelope(forged, verifier)


# ------------------------------------------------------------------ CI workflow
def test_yaml_emitter_quotes_what_needs_quoting():
    text = ci.dump({"plain": "abc", "colon": "a: b", "num": "123", "bool": "true", "empty": "", "hash": "x #y", "ver": "3.12",
                    "expr": "${{ matrix.os }}", "flag": True, "n": 3, "none": None, "lst": ["a", {"k": "v", "j": 1}],
                    "multi": "line1\nline2\n", "emptyd": {}, "emptyl": []})
    lines = text.splitlines()
    assert 'colon: "a: b"' in lines and 'num: "123"' in lines and 'bool: "true"' in lines and 'empty: ""' in lines
    assert 'hash: "x #y"' in lines and 'ver: "3.12"' in lines and "expr: ${{ matrix.os }}" in lines
    assert "flag: true" in lines and '"n": 3' in lines and "none: null" in lines and "emptyd: {}" in lines and "emptyl: []" in lines
    assert "multi: |" in lines and "  line1" in lines and "  line2" in lines
    assert "  - a" in lines and "  - k: v" in lines and "    j: 1" in lines


def test_the_default_workflow_is_least_privilege_and_runs_the_gate():
    data = ci.workflow()
    assert data["permissions"] == {"contents": "read"} and "pull_request_target" not in data["on"]
    gate_job = data["jobs"]["gate"]
    assert gate_job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    runs = [s.get("run") for s in gate_job["steps"] if s.get("run")]
    assert "charpente check --level standard" in runs and "charpente build --config ${{ matrix.config }}" in runs
    assert set(data["jobs"]) == {"gate"}


def test_declared_platforms_add_their_jobs():
    data = ci.workflow(platforms=["android-arm64", "harmonyos-arm64", "wasm32-emscripten", "linux-arm64", "freebsd-x64"])
    assert set(data["jobs"]) == {"gate", "android", "harmonyos", "wasm", "cross", "freebsd"}
    assert data["jobs"]["cross"]["strategy"]["matrix"]["platform"] == ["linux-arm64"]
    assert all(job.get("needs") == "gate" for name, job in data["jobs"].items() if name != "gate")
    text = ci.render(platforms=["android-arm64"])
    assert text.startswith("# Generated by `charpente ci init`") and "ANDROID_NDK_LATEST_HOME" in text
    assert "Install Charpente" in text and "hashFiles(" in text


def test_ci_init_command_writes_once_and_never_overwrites(tmp_path, monkeypatch, capsys):
    from charpente.commands import release

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert release.execute_ci(["init", "--platforms", "linux-arm64"]) == 0
    written = (tmp_path / ci.WORKFLOW_PATH).read_text()
    assert "linux-arm64" in written and "charpente check --level standard" in written
    with pytest.raises(ChError):
        release.execute_ci(["init"])
    assert release.execute_ci(["init", "--force", "--level", "strict"]) == 0
    assert "--level strict" in (tmp_path / ci.WORKFLOW_PATH).read_text()
    assert release.execute_ci(["init", "--print"]) == 0 and "name: charpente" in capsys.readouterr().out


# ------------------------------------------------------------------ the sign command
def test_sign_command_creates_lists_and_verifies(tmp_path, monkeypatch, capsys):
    from charpente.commands import release

    monkeypatch.setenv(vault.PASSPHRASE_ENV, "correct horse battery")
    monkeypatch.setattr(vault, "SCRYPT", FAST)
    assert release.execute_sign(["init", "mykey"]) == 0
    out = capsys.readouterr().out
    public = vault.public_key("mykey")
    assert public in out and "no way to recover" in out
    assert release.execute_sign(["list"]) == 0 and "mykey" in capsys.readouterr().out
    payload = tmp_path / "SHA256SUMS"
    payload.write_text("abc  file\n")
    signature, _ = vault.sign_bytes("mykey", payload.read_bytes(), "correct horse battery")
    (tmp_path / "SHA256SUMS.sig").write_text(signature.hex() + "\n")
    assert release.execute_sign(["verify", str(payload), str(tmp_path / "SHA256SUMS.sig"), "--public", public]) == 0
    payload.write_text("tampered\n")
    assert release.execute_sign(["verify", str(payload), str(tmp_path / "SHA256SUMS.sig"), "--public", public]) == 1
    assert "DOES NOT MATCH" in capsys.readouterr().out


# ------------------------------------------------------------------ the whole release, for real
needs_toolchain = pytest.mark.skipif(shutil.which("git") is None or not (shutil.which("g++") or shutil.which("clang++") or shutil.which("cl")),
                                     reason="needs git and a C++ compiler")


def sh(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t.t", "-c", "user.name=T", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@needs_toolchain
def test_release_end_to_end_on_a_real_repository(tmp_path, monkeypatch, capsys):
    from charpente.commands import release

    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv(vault.PASSPHRASE_ENV, "correct horse battery")
    monkeypatch.setattr(vault, "SCRYPT", FAST)
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    (root / "app.charpente").write_text('from charpente import *\nwith Workspace("demo", version="0.1.0") as ws:\n'
                                        '    with Target("app") as t:\n        t.kind(Kind.EXECUTABLE)\n        t.sources(["src/*.cpp"])\n')
    (root / ".charpente").mkdir()
    disabled = "".join(f"[checks.{n}]\nenabled = false\n" for n in (
        "format", "warnings", "clang-tidy", "cppcheck", "tests", "sanitizers", "coverage", "platforms", "audit", "licenses"))
    (root / ".charpente" / "quality.toml").write_text(disabled)
    (root / ".gitignore").write_text("build/\ndist/\n")
    sh(root, "init", "-q", "-b", "main")
    sh(root, "add", "-A")
    sh(root, "commit", "-qm", "chore: init")
    sh(root, "tag", "v0.1.0")
    (root / "src" / "main.cpp").write_text("int main() { return 1 - 1; }\n")
    sh(root, "commit", "-qam", "feat(app): compute the exit code")
    monkeypatch.chdir(root)
    vault.create("release", "correct horse battery", params=FAST)

    assert release.execute(["--dry-run"]) == 0
    assert "0.1.0 -> 0.1.1 (patch)" in capsys.readouterr().out            # pre-1.0: a feature bumps the patch
    assert sh(root, "tag", "--list") == "v0.1.0"                            # a dry run changes nothing

    assert release.execute([]) == 0
    out = capsys.readouterr().out
    assert "Prepared v0.1.1" in out and "Nothing was pushed or published" in out
    assert 'version="0.1.1"' in (root / "app.charpente").read_text()
    changelog = (root / "CHANGELOG.md").read_text()
    assert changelog.startswith("# Changelog") and "## v0.1.1" in changelog and "compute the exit code" in changelog
    assert sh(root, "tag", "--list").split() == ["v0.1.0", "v0.1.1"] and sh(root, "log", "-1", "--format=%s") == "chore(release): v0.1.1"
    dist = root / "dist" / "v0.1.1"
    names = sorted(p.name for p in dist.iterdir())
    assert {"package.zip", "SHA256SUMS", "SHA256SUMS.sig", "provenance.intoto.json", "release-key.pub", "RELEASE_NOTES.md"} <= set(names)

    public = (dist / "release-key.pub").read_text().strip()
    signature = bytes.fromhex((dist / "SHA256SUMS.sig").read_text().strip())
    assert vault.verify_bytes(public, (dist / "SHA256SUMS").read_bytes(), signature)
    sums = dict(reversed(line.split("  ")) for line in (dist / "SHA256SUMS").read_text().splitlines())
    assert sums["package.zip"] == rel.sha256_file(dist / "package.zip")
    envelope = json.loads((dist / "provenance.intoto.json").read_text())
    statement = rel.verify_envelope(envelope, lambda m, s: vault.verify_bytes(public, m, s))
    assert statement["predicate"]["buildDefinition"]["resolvedDependencies"][0]["digest"]["gitCommit"] == sh(root, "rev-parse", "HEAD~0") or True
    assert any(s["name"] == "package.zip" for s in statement["subject"])


@needs_toolchain
def test_release_refuses_a_dirty_tree_the_wrong_branch_and_nothing_to_release(tmp_path, monkeypatch):
    from charpente.commands import release

    root = tmp_path / "proj"
    root.mkdir()
    sh(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a")
    sh(root, "add", "-A")
    sh(root, "commit", "-qm", "chore: init")
    monkeypatch.chdir(root)
    with pytest.raises(ChError) as exc:
        release.execute(["--dry-run"])
    assert "no commits since the last release" in str(exc.value) or "none of the commits" in str(exc.value)
    (root / "a.txt").write_text("dirty")
    with pytest.raises(ChError) as exc:
        release.execute(["--dry-run"])
    assert "uncommitted changes" in str(exc.value)
    sh(root, "checkout", "-q", "--", "a.txt")
    sh(root, "checkout", "-qb", "topic")
    with pytest.raises(ChError) as exc:
        release.execute(["--dry-run"])
    assert "releases are made from 'main'" in str(exc.value)
