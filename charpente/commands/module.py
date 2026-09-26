"""`charpente module ...` -- install, inspect and author modules."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..errors import ChError
from ..modules import conformance, installer, official, runtime, signing
from ..modules.api import MANIFEST_NAME, MODULE_API_VERSION, Manifest
from ..modules.manifest import load as load_manifest
from ..modules.store import InstalledModule, ModuleStore
from ..units import parse_size


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def describe(manifest: Manifest, status: Optional[signing.SignatureStatus] = None) -> List[str]:
    lines = [f"{manifest.name} {manifest.version}  --  {manifest.description}",
             f"  license: {manifest.license}   module API: {manifest.api}"]
    if status is not None:
        lines.append("  signature: " + ("signed by a trusted key (" + status.key + ")" if status.signed
                                        else f"NOT signed ({status.detail})"))
    lines.append("  it asks to:")
    lines.extend(f"    - {line}" for line in manifest.capabilities.describe())
    provided = [f"{k}: {', '.join(v)}" for k, v in manifest.provides.items() if v]
    if provided:
        lines.append("  it provides: " + "; ".join(provided))
    return lines


def _approver(assume_yes: bool) -> installer.Approver:
    def approve(manifest: Manifest, status: signing.SignatureStatus) -> bool:
        for line in describe(manifest, status):
            print(line)
        if assume_yes and status.signed:
            return True
        if not _interactive():
            print("Cannot ask for confirmation (not an interactive terminal); "
                  "review the above and repeat with --yes" + ("" if status.signed else " --allow-unsigned") + ".")
            return assume_yes and status.signed
        return input("Install it with these permissions? [y/N] ").strip().lower() in ("y", "yes")

    return approve


def _row(m: InstalledModule, manifest: Optional[Manifest]) -> str:
    state = "enabled" if m.enabled else "disabled"
    if manifest is not None and m.enabled and not m.approved_caps().covers(manifest.capabilities):
        state = "needs approval"
    origin = "bundled" if m.bundled else ("signed" if m.signature.startswith("signed") else "unsigned")
    return f"  {m.name:<28}{m.version:<10}{state:<16}{origin}"


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente module", description="Manage Charpente modules.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="Installed and bundled modules")
    info = sub.add_parser("info", help="What a module provides and asks for")
    info.add_argument("name")
    add = sub.add_parser("add", help="Install from a folder, .zip, URL, or registry name")
    add.add_argument("source")
    add.add_argument("--yes", action="store_true", help="Approve the requested capabilities (signed modules only)")
    add.add_argument("--allow-unsigned", action="store_true")
    add.add_argument("--registry", action="append", help="Registry index (repeatable)")
    add.add_argument("--max-download", default=None, help="Refuse a download larger than this (e.g. 5MB)")
    for name in ("remove", "enable", "disable", "approve"):
        p = sub.add_parser(name)
        p.add_argument("name")
    upd = sub.add_parser("update", help="Install newer versions from the registries")
    upd.add_argument("name", nargs="?")
    check = sub.add_parser("check", help="Run the conformance checks on a module folder")
    check.add_argument("path")
    new = sub.add_parser("new", help="Scaffold a new module")
    new.add_argument("name")
    new.add_argument("--dir", default=".")
    keygen = sub.add_parser("keygen", help="Create a signing key pair")
    keygen.add_argument("--out", default="charpente-module.key")
    sign = sub.add_parser("sign", help="Sign a module folder")
    sign.add_argument("path")
    sign.add_argument("--key", required=True)
    trust = sub.add_parser("trust-key", help="Trust an Ed25519 public key (64 hex characters)")
    trust.add_argument("public_key")
    reg = sub.add_parser("registry", help="Manage registries")
    reg.add_argument("verb", choices=["add", "list", "remove"])
    reg.add_argument("url", nargs="?")
    parsed = parser.parse_args(args)

    store = ModuleStore()
    handler = globals()[f"_cmd_{parsed.action.replace('-', '_')}"]
    return int(handler(parsed, store))


def _all_records(store: ModuleStore) -> List[InstalledModule]:
    records = {m.name: m for m in store.list()}
    for name in official.bundled_names():
        records.setdefault(name, InstalledModule(name=name, version=official.bundled_manifest(name).version,
                                                 path="", enabled=False, signature="bundled", bundled=True))
    return sorted(records.values(), key=lambda m: m.name)


def _manifest_for(store: ModuleStore, name: str) -> Manifest:
    record = next((m for m in _all_records(store) if m.name == name), None)
    if record is None:
        raise ChError("CH7006", name=name, where="not installed and not bundled")
    if record.bundled:
        return official.bundled_manifest(name)
    return load_manifest(Path(record.path))[0]


def _cmd_list(parsed: argparse.Namespace, store: ModuleStore) -> int:
    records = _all_records(store)
    print(f"Module API {MODULE_API_VERSION}")
    print(f"  {'name':<28}{'version':<10}{'state':<16}origin")
    for m in records:
        try:
            manifest: Optional[Manifest] = _manifest_for(store, m.name)
        except ChError:
            manifest = None
        print(_row(m, manifest))
    problems = runtime.problems()
    for name, exc in problems.items():
        print(f"  ! {name}: {exc.message}")
    return 0


def _cmd_info(parsed: argparse.Namespace, store: ModuleStore) -> int:
    manifest = _manifest_for(store, parsed.name)
    record = next(m for m in _all_records(store) if m.name == parsed.name)
    for line in describe(manifest):
        print(line)
    print(f"  state: {'enabled' if record.enabled else 'disabled'}"
          f"{' (bundled with Charpente)' if record.bundled else ''}")
    if not record.bundled:
        print(f"  installed from: {record.source}   signature: {record.signature}")
    return 0


def _cmd_add(parsed: argparse.Namespace, store: ModuleStore) -> int:
    limit = parse_size(parsed.max_download) if parsed.max_download else None
    record = installer.install(parsed.source, store, approve=_approver(parsed.yes),
                               allow_unsigned=parsed.allow_unsigned, assume_yes=parsed.yes,
                               registries=parsed.registry, max_download=limit)
    runtime.reset()
    print(f"Installed {record.name} {record.version} ({record.signature}). It is enabled.")
    return 0


def _cmd_remove(parsed: argparse.Namespace, store: ModuleStore) -> int:
    existed = store.remove(parsed.name)
    runtime.reset()
    print(f"Removed {parsed.name}." if existed else f"{parsed.name} was not installed.")
    return 0 if existed else 1


def _cmd_disable(parsed: argparse.Namespace, store: ModuleStore) -> int:
    ok = store.set_enabled(parsed.name, False)
    runtime.reset()
    print(f"Disabled {parsed.name}." if ok else f"{parsed.name} is not enabled.")
    return 0 if ok else 1


def _approve_and_enable(name: str, store: ModuleStore, *, ask: bool) -> int:
    manifest = _manifest_for(store, name)
    for line in describe(manifest):
        print(line)
    if ask:
        if not _interactive():
            print("Cannot ask for confirmation here; run this in an interactive terminal.")
            return 1
        if input("Allow this? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Not approved.")
            return 1
    record = store.get(name)
    if record is None:
        record = InstalledModule(name=name, version=manifest.version, path="", enabled=True,
                                 signature="bundled", bundled=official.is_bundled(name))
    record.enabled = True
    record.approved = manifest.capabilities.to_dict()
    store.put(record)
    runtime.reset()
    print(f"{name} is enabled with the permissions above.")
    return 0


def _cmd_enable(parsed: argparse.Namespace, store: ModuleStore) -> int:
    return _approve_and_enable(parsed.name, store, ask=True)


def _cmd_approve(parsed: argparse.Namespace, store: ModuleStore) -> int:
    return _approve_and_enable(parsed.name, store, ask=True)


def _cmd_update(parsed: argparse.Namespace, store: ModuleStore) -> int:
    names = [parsed.name] if parsed.name else [m.name for m in store.list() if not m.bundled]
    if not names:
        print("No installed modules to update.")
        return 0
    changed = 0
    for name in names:
        record = installer.update(name, store, approve=_approver(False))
        if record is None:
            print(f"{name} is up to date.")
        else:
            changed += 1
            print(f"Updated {name} to {record.version}.")
    runtime.reset()
    return 0


def _cmd_check(parsed: argparse.Namespace, store: ModuleStore) -> int:
    path = Path(parsed.path)
    if not path.is_dir():
        record = store.get(parsed.path)
        if record is None:
            raise ChError("CH7006", name=parsed.path, where="not a folder, and not installed")
        path = Path(record.path)
    issues = conformance.check_module(path)
    for issue in issues:
        print(f"  {issue.level.upper():<8}{issue.message}")
    errors = sum(1 for i in issues if i.level == "error")
    print(f"{path.name}: {errors} error(s), {len(issues) - errors} warning(s).")
    return 1 if errors else 0


_MODULE_TOML = '''[module]
name = "{name}"
version = "0.1.0"
api = "^2.0"
license = "Apache-2.0"
description = "A Charpente module"
entry = "{package}:register"

[provides]
commands = ["{command}"]

[capabilities]
process = []
filesystem = "none"
network = false
'''

_MODULE_PY = '''"""{name}: a Charpente module. `register` is called when the module is loaded."""


class HelloCommand:
    name = "{command}"
    help = "charpente {command} -- say hello (an example command)"

    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, args):
        print("Hello from {name}!", *args)
        return 0


def register(registry, ctx):
    registry.add_command(HelloCommand(ctx))
'''


def _cmd_new(parsed: argparse.Namespace, store: ModuleStore) -> int:
    from ..modules.manifest import _NAME_RE  # noqa: PLC2701 (the same rule the manifest enforces)

    name = parsed.name
    if not _NAME_RE.match(name):
        raise ChError("CH4005", usage=f"Module names use lowercase letters, digits, '-', '_' and '.': {name!r}")
    root = Path(parsed.dir) / name
    if root.exists():
        print(f"charpente: {root} already exists.")
        return 1
    package = name.replace("-", "_").replace(".", "_")
    command = name.replace("charpente-", "", 1) or "hello"
    (root / package).mkdir(parents=True)
    (root / MANIFEST_NAME).write_text(_MODULE_TOML.format(name=name, package=package, command=command),
                                      encoding="utf-8")
    (root / package / "__init__.py").write_text(_MODULE_PY.format(name=name, command=command), encoding="utf-8")
    (root / "README.md").write_text(f"# {name}\n\nA Charpente module. Try it:\n\n```\n"
                                    f"charpente module check .\ncharpente module add . --allow-unsigned\n"
                                    f"charpente {command}\n```\n", encoding="utf-8")
    print(f"Created {root}\nNext: charpente module check {root}")
    return 0


def _cmd_keygen(parsed: argparse.Namespace, store: ModuleStore) -> int:
    import os

    secret = os.urandom(32)
    out = Path(parsed.out)
    if out.exists():
        print(f"charpente: {out} already exists; not overwriting a key.")
        return 1
    out.write_text(secret.hex(), encoding="utf-8")
    try:
        out.chmod(0o600)
    except OSError:
        pass
    pub = signing.public_key(secret)
    print(f"Secret key written to {out} (keep it private, never commit it).")
    print(f"Public key: {pub.hex()}\nKey id: {signing.key_id(pub)}")
    return 0


def _cmd_sign(parsed: argparse.Namespace, store: ModuleStore) -> int:
    try:
        secret = bytes.fromhex(Path(parsed.key).read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        raise ChError("CH4005", usage=f"Cannot read the key file {parsed.key}: {exc}") from exc
    path = signing.write_signature(Path(parsed.path), secret)
    print(f"Signed {parsed.path} -> {path}")
    return 0


def _cmd_trust_key(parsed: argparse.Namespace, store: ModuleStore) -> int:
    try:
        kid = signing.add_trusted_key(parsed.public_key)
    except ValueError as exc:
        raise ChError("CH4005", usage=str(exc)) from exc
    print(f"Trusted key {kid}.")
    return 0


def _cmd_registry(parsed: argparse.Namespace, store: ModuleStore) -> int:
    if parsed.verb == "list":
        for url in store.registries():
            print(url)
        return 0
    if not parsed.url:
        raise ChError("CH4005", usage="Usage: charpente module registry add|remove URL")
    if parsed.verb == "add":
        store.add_registry(parsed.url)
        print(f"Added registry {parsed.url}")
        return 0
    removed = store.remove_registry(parsed.url)
    print("Removed." if removed else "No such registry.")
    return 0 if removed else 1

