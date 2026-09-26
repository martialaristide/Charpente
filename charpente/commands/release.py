"""`charpente release`, `charpente ci init`, `charpente sign` -- shipping.

`release` does every *local* step (version, changelog, packages, checksums, signature, provenance, commit, tag) and stops.
Pushing and creating the GitHub release happen only with `--publish`, because they are visible to other people and cannot
be undone quietly. `--dry-run` prints the plan and changes nothing.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List

from ..core import process
from ..errors import ChError
from ..quality import gate
from ..vcs import ci as ci_mod
from ..vcs import git as git_mod
from ..vcs import release as rel
from ..vcs import vault
from ._common import find_root, load
from .vcs import _bus


def _cli(root: Path, args: List[str]) -> process.ProcessResult:
    return process.run([sys.executable, "-m", "charpente", *args], cwd=str(root), timeout=3600)


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente release", description="Prepare (and, with --publish, publish) a release.")
    parser.add_argument("--bump", default="auto", help="auto (from the commits), major, minor, patch, or an exact version like 1.2.3")
    parser.add_argument("--platforms", default="", help="Comma-separated platforms to package (default: this machine's, plus "
                                                        "any listed under `platforms` in the workspace)")
    parser.add_argument("--key", default="release", help="Name of the signing key in the vault (see `charpente sign init`)")
    parser.add_argument("--no-sign", action="store_true", help="Skip signing (checksums and provenance are still written, unsigned)")
    parser.add_argument("--level", default="strict", choices=["rapide", "standard", "strict"], help="Quality-gate level to require")
    parser.add_argument("--branch", help="Branch a release must be made from (default: the remote's default branch)")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan; change nothing")
    parser.add_argument("--publish", action="store_true", help="Push the commit and tag and create the GitHub release (with gh)")
    parser.add_argument("--remote", default="origin")
    parsed = parser.parse_args(args)

    root = find_root()
    g = git_mod.Git(root)
    g.require_repo()
    status = g.status()
    base_branch = parsed.branch or g.default_base(parsed.remote)
    if not status.clean:
        raise ChError("CH8016", reason="the working tree has uncommitted changes; commit or stash them first")
    if status.branch != base_branch:
        raise ChError("CH8016", reason=f"releases are made from {base_branch!r} (you are on {status.branch or 'a detached HEAD'!r}); "
                                       "use --branch to change this")
    if status.behind:
        raise ChError("CH8016", reason=f"the branch is {status.behind} commit(s) behind {status.upstream}; pull first")

    current = rel.read_version(root) or (g.latest_tag() or "v0.0.0").lstrip("v")
    tag = g.latest_tag()
    commits = list(reversed(g.log(f"{tag}..HEAD" if tag else "HEAD")))
    if not commits:
        raise ChError("CH8016", reason="there are no commits since the last release")
    kind = parsed.bump if parsed.bump != "auto" else rel.bump_kind(commits, current)
    if kind is None:
        raise ChError("CH8016", reason="none of the commits since the last release is user-visible (feat/fix/perf/refactor); "
                                       "pass --bump patch to release anyway")
    version = rel.next_version(current, kind)
    section = rel.changelog_section(version, commits)
    print(f"Release plan: {current} -> {version} ({kind}), {len(commits)} commit(s) since {tag or 'the beginning'}\n")
    print(section)
    if parsed.dry_run:
        print("Dry run: nothing was changed.")
        return 0
    if parsed.publish and not shutil.which("gh"):
        raise ChError("CH8016", reason="--publish needs the GitHub CLI (`gh`) to create the release; install it or publish by hand "
                                       "(the tag and files are prepared either way)")

    phrase = None
    if not parsed.no_sign:
        vault.public_key(parsed.key)                       # fail early if the key does not exist
        phrase = vault.passphrase(f"Passphrase for key {parsed.key!r}: ")
        vault.unlock(parsed.key, phrase)                   # ... or the passphrase is wrong

    bus = _bus()
    result = gate.run_gate(root, level=parsed.level, bus=bus, say=print)
    print(gate.render(result))
    if not result.ok:
        raise ChError("CH8016", reason="the quality gate did not pass: " + (", ".join(r.name for r in result.failed) or "skipped checks"))

    started = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = [rel.write_version(root, current, version)] if rel.read_version(root) else []
    changelog = root / "CHANGELOG.md"
    changelog.write_text(rel.prepend_changelog(changelog.read_text(encoding="utf-8") if changelog.exists() else "", section),
                         encoding="utf-8")
    dist = root / "dist" / f"v{version}"
    dist.mkdir(parents=True, exist_ok=True)
    platforms = [p for p in parsed.platforms.split(",") if p] or [""]
    artifacts: List[Path] = []
    command: List[str] = []
    for platform in platforms:
        out = dist / (f"package{'-' + platform if platform else ''}.zip")
        command = ["package", "--format", "zip", "--config", "Release", "--output", str(out.relative_to(root))]
        if platform:
            command += ["--platform", platform]
        built = _cli(root, command)
        if built.returncode != 0:
            raise ChError("CH8016", reason=f"packaging {platform or 'this machine'} failed: {built.output.strip()[-400:]}")
        artifacts.append(out)
    sbom = _cli(root, ["sbom", "--output", str(dist)])
    artifacts += sorted(dist.glob("*.spdx.json")) + sorted(dist.glob("*.cdx.json")) if sbom.returncode == 0 else []
    sums = dist / "SHA256SUMS"
    sums.write_text(rel.checksums(artifacts), encoding="utf-8")
    artifacts.append(sums)
    remote_url = g.remote_url(parsed.remote) or f"file://{root.as_posix()}"
    head = g.head() or ""
    finished = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    statement = rel.provenance_statement(
        [a for a in artifacts if a.name != "SHA256SUMS"], source_uri=remote_url, commit=head, command=["charpente", *command],
        version=version, builder_id=rel.builder_identity(dict(os.environ)), started=started, finished=finished)
    provenance = dist / "provenance.intoto.json"
    if phrase is not None:
        def seed_sign(message: bytes) -> bytes:
            return vault.sign_bytes(parsed.key, message, phrase)[0]

        key_id = vault.sign_bytes(parsed.key, b"", phrase)[1]
        sums_sig = dist / "SHA256SUMS.sig"
        sums_sig.write_text(seed_sign(sums.read_bytes()).hex() + "\n", encoding="utf-8")
        artifacts.append(sums_sig)
        envelope = rel.dsse_envelope(statement, key_id, seed_sign)
        provenance.write_text(json.dumps(envelope, indent=1), encoding="utf-8")
        (dist / "release-key.pub").write_text(vault.public_key(parsed.key) + "\n", encoding="utf-8")
        artifacts.append(dist / "release-key.pub")
    else:
        provenance.write_text(json.dumps(statement, indent=1), encoding="utf-8")
    artifacts.append(provenance)
    notes = dist / "RELEASE_NOTES.md"
    notes.write_text(section, encoding="utf-8")

    for path in written + [changelog]:
        g.call(["add", str(path)])
    sha = g.commit(f"chore(release): v{version}")
    g.tag(f"v{version}", f"Release v{version}")
    _bus(quiet=True).emit("vcs.commit_created", sha=sha, message=f"chore(release): v{version}")
    print(f"\nPrepared v{version}: commit {sha[:7]}, tag v{version}, files in {dist.relative_to(root)}:")
    for artifact in artifacts:
        print(f"  {artifact.name}")
    if not parsed.publish:
        print("\nNothing was pushed or published. To publish: `charpente release --publish` after resetting, or "
              f"`git push --follow-tags {parsed.remote} {status.branch}` and `gh release create v{version} {dist}/*`.")
        return 0
    g.push(parsed.remote, status.branch, tags=True)
    created = process.run(["gh", "release", "create", f"v{version}", *[str(a) for a in artifacts], "--title", f"v{version}",
                           "--notes-file", str(notes)], cwd=str(root), timeout=900)
    if created.returncode != 0:
        raise ChError("CH8016", reason="the tag was pushed but `gh release create` failed: " + created.output.strip()[-400:])
    print(f"Published: {created.stdout.strip().splitlines()[-1] if created.stdout.strip() else 'v' + version}")
    return 0


# ------------------------------------------------------------------ ci init
def execute_ci(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente ci", description="Continuous integration setup.")
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Write a GitHub Actions workflow that runs the quality gate on a matrix")
    init.add_argument("--platforms", default="", help="Comma-separated extra platforms to build (default: the workspace's `platforms`)")
    init.add_argument("--install", default="python -m pip install charpente",
                      help="How CI installs Charpente (e.g. 'python -m pip install git+https://github.com/you/charpente')")
    init.add_argument("--level", default="standard", choices=["rapide", "standard", "strict"])
    init.add_argument("--force", action="store_true", help="Overwrite an existing workflow")
    init.add_argument("--print", action="store_true", help="Print the workflow instead of writing it")
    parsed = parser.parse_args(args)
    root = find_root()
    platforms = [p for p in parsed.platforms.split(",") if p]
    if not platforms:
        try:
            platforms = list(load(None, None, materialize_packages=False).platforms)
        except ChError:
            platforms = []
    text = ci_mod.render(platforms=platforms, install=parsed.install, level=parsed.level)
    if parsed.print:
        print(text)
        return 0
    path = root / ci_mod.WORKFLOW_PATH
    if path.exists() and not parsed.force:
        raise ChError("CH8016", reason=f"{ci_mod.WORKFLOW_PATH} already exists; use --force to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {ci_mod.WORKFLOW_PATH} ({len(text.splitlines())} lines) for: gate on ubuntu/windows/macos x Debug/Release"
          + (f", plus {', '.join(platforms)}" if platforms else "") + ".")
    print("Commit it; CI will run `charpente check` exactly as you do locally.")
    return 0


# ------------------------------------------------------------------ sign
def execute_sign(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente sign", description="Release signing keys (Ed25519, stored encrypted).")
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create a signing key")
    init.add_argument("name", nargs="?", default="release")
    sub.add_parser("list", help="List keys (public parts only)")
    show = sub.add_parser("public", help="Print a key's public part")
    show.add_argument("name", nargs="?", default="release")
    verify = sub.add_parser("verify", help="Verify a detached signature (hex) over a file with a public key")
    verify.add_argument("file")
    verify.add_argument("signature")
    verify.add_argument("--public", required=True, help="The public key (hex) or a file holding it")
    parsed = parser.parse_args(args)
    if parsed.action == "init":
        first = vault.passphrase(f"New passphrase for key {parsed.name!r}: ")
        if sys.stdin.isatty() and not os.environ.get(vault.PASSPHRASE_ENV):
            import getpass

            if getpass.getpass("Repeat it: ") != first:
                raise ChError("CH8016", reason="the two passphrases differ; no key was created")
        public = vault.create(parsed.name, first)
        print(f"Created key {parsed.name!r} in {vault.keys_dir()}.\nPublic key (share this, it verifies your releases): {public}\n"
              "The private part is encrypted with your passphrase; there is no way to recover it if you forget it.")
        return 0
    if parsed.action == "list":
        keys = vault.list_keys()
        for name, public in keys:
            print(f"  {name:<16} {public}")
        if not keys:
            print("No keys yet: `charpente sign init`.")
        return 0
    if parsed.action == "public":
        print(vault.public_key(parsed.name))
        return 0
    public = parsed.public
    if Path(public).is_file():
        public = Path(public).read_text(encoding="utf-8").strip()
    ok = vault.verify_bytes(public, Path(parsed.file).read_bytes(), bytes.fromhex(Path(parsed.signature).read_text(encoding="utf-8").strip()))
    print("Signature is valid." if ok else "SIGNATURE DOES NOT MATCH.")
    return 0 if ok else 1

