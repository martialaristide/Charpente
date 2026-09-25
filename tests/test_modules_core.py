import json
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from charpente.dsl.model import OS
from charpente.errors import ChError
from charpente.events import EventBus
from charpente.modules import conformance, installer, manifest, signing
from charpente.modules.api import MODULE_API_VERSION, Capabilities
from charpente.modules.capabilities import ModuleContext
from charpente.modules.loader import ModuleManager
from charpente.modules.registry import ExtensionRegistry
from charpente.modules.store import InstalledModule, ModuleStore

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "modules" / "charpente-hello"

VALID = """
[module]
name = "my-mod"
version = "1.2.0"
api = "^2.0"
license = "MIT"
description = "d"
entry = "my_mod:register"
[provides]
commands = ["x"]
[capabilities]
process = ["git"]
filesystem = "workspace"
network = ["example.org"]
"""


def make_module(root: Path, name="my-mod", version="1.0.0", body=None, provides=None, caps="", api="^2.0",
                extra_files=None) -> Path:
    pkg = name.replace("-", "_")
    folder = root / name
    (folder / pkg).mkdir(parents=True)
    provides_toml = provides if provides is not None else 'commands = ["cmd-' + name + '"]'
    (folder / "charpente-module.toml").write_text(textwrap.dedent(f"""
        [module]
        name = "{name}"
        version = "{version}"
        api = "{api}"
        license = "MIT"
        description = "test module"
        entry = "{pkg}:register"
        [provides]
        {provides_toml}
        [capabilities]
        {caps}
    """), encoding="utf-8")
    (folder / pkg / "__init__.py").write_text(textwrap.dedent(body or f"""
        class Cmd:
            name = "cmd-{name}"
            help = "h"
            def __init__(self, ctx): self.ctx = ctx
            def __call__(self, args):
                print("ran {name}", *args)
                return 7
        def register(registry, ctx):
            registry.add_command(Cmd(ctx))
    """), encoding="utf-8")
    for rel, text in (extra_files or {}).items():
        (folder / rel).write_text(text, encoding="utf-8")
    return folder


@pytest.fixture
def store(tmp_path):
    return ModuleStore(tmp_path / "store")


# ================================================================== manifest
def test_a_valid_manifest_parses():
    m, warnings = manifest.loads(VALID)
    assert (m.name, m.version, m.entry) == ("my-mod", "1.2.0", "my_mod:register") and warnings == []
    assert m.provides["commands"] == ("x",)
    assert m.capabilities.process == ("git",) and m.capabilities.filesystem == "workspace"
    assert m.capabilities.network == ("example.org",)


def test_every_manifest_problem_is_reported_at_once():
    bad = VALID.replace('name = "my-mod"', 'name = "Bad Name"').replace('version = "1.2.0"', 'version = "x"') \
               .replace('entry = "my_mod:register"', 'entry = "nocolon"').replace('filesystem = "workspace"', 'filesystem = "all"')
    with pytest.raises(ChError) as exc:
        manifest.loads(bad)
    assert exc.value.code == "CH7003"
    text = str(exc.value)
    for fragment in ("name", "version", "entry", "filesystem"):
        assert fragment in text


@pytest.mark.parametrize("text,fragment", [
    ("", "[module]"), ("[module]\n", "name"), ("this is = not toml [", "not valid TOML"),
    (VALID.replace('description = "d"\n', ""), "description"),
    (VALID.replace('api = "^2.0"', 'api = "??"'), "api"),
    (VALID.replace('network = ["example.org"]', 'network = 3'), "network"),
    (VALID.replace('commands = ["x"]', 'commands = "x"'), "commands"),
])
def test_invalid_manifests(text, fragment):
    with pytest.raises(ChError) as exc:
        manifest.loads(text)
    assert exc.value.code == "CH7003" and fragment in str(exc.value)


def test_unknown_keys_are_warnings_not_errors():
    _, warnings = manifest.loads(VALID.replace("[provides]", '[provides]\nwidgets = ["w"]'))
    assert any("widgets" in w for w in warnings)


def test_api_compatibility():
    ok, _ = manifest.loads(VALID)
    manifest.check_api(ok)
    old, _ = manifest.loads(VALID.replace('api = "^2.0"', 'api = "^1.0"'))
    with pytest.raises(ChError) as exc:
        manifest.check_api(old)
    assert exc.value.code == "CH7004" and MODULE_API_VERSION in str(exc.value)


# ============================================================== capabilities
def test_capability_coverage_and_description():
    have = Capabilities(process=("git",), filesystem="workspace", network=("a.org",))
    assert have.covers(Capabilities(process=("git",)))
    assert have.covers(Capabilities(filesystem="none"))
    assert not have.covers(Capabilities(process=("git", "curl")))
    assert not have.covers(Capabilities(filesystem="home"))
    assert not have.covers(Capabilities(network=("b.org",)))
    assert not have.covers(Capabilities(network=True))
    assert Capabilities(network=True).covers(Capabilities(network=("anything.org",)))
    assert Capabilities(process=("*",)).covers(Capabilities(process=("x", "y")))
    assert "nothing beyond" in Capabilities().describe()[0]
    assert Capabilities.from_dict(have.to_dict()) == have


def _ctx(tmp_path, caps, opener=None, workspace=None):
    m, _ = manifest.loads(VALID.replace('commands = ["x"]', 'commands = ["x"]\nevents = ["mod.done"]'))
    return ModuleContext(m, caps, data_dir=tmp_path / "data", workspace_root=workspace, opener=opener)


def test_process_guard(tmp_path):
    ctx = _ctx(tmp_path, Capabilities(process=("python",)))
    assert ctx.process.run([sys.executable, "-c", "print(1)"]).stdout.strip() == "1"
    with pytest.raises(ChError) as exc:
        ctx.process.run(["git", "--version"])
    assert exc.value.code == "CH7005" and "process:git" in str(exc.value)
    with pytest.raises(ChError):
        ctx.process.run([])
    assert _ctx(tmp_path, Capabilities()).process.allowed("anything") is False
    assert _ctx(tmp_path, Capabilities(process=("*",))).process.allowed("anything")


def test_filesystem_guard_confines_a_module(tmp_path):
    ws = tmp_path / "ws"
    (ws / "build").mkdir(parents=True)
    (ws / "src.txt").write_text("hi")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    ctx = _ctx(tmp_path, Capabilities(filesystem="workspace"), workspace=ws)
    assert ctx.fs.read_text(ws / "src.txt") == "hi"
    ctx.fs.write_text(ws / "out" / "x.txt", "ok")
    assert (ws / "out" / "x.txt").read_text() == "ok"
    with pytest.raises(ChError):
        ctx.fs.read_text(outside)
    with pytest.raises(ChError):
        ctx.fs.read_text(ws / ".." / "outside.txt")              # traversal
    ctx.fs.write_text(tmp_path / "data" / "own.txt", "mine")     # its own data folder is always allowed

    none = _ctx(tmp_path, Capabilities(filesystem="none"), workspace=ws)
    with pytest.raises(ChError):
        none.fs.read_text(ws / "src.txt")
    build_only = _ctx(tmp_path, Capabilities(filesystem="build"), workspace=ws)
    build_only.fs.write_text(ws / "build" / "y.txt", "y")
    with pytest.raises(ChError):
        build_only.fs.read_text(ws / "src.txt")


def test_filesystem_guard_resists_symlink_escape(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    link = ws / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    ctx = _ctx(tmp_path, Capabilities(filesystem="workspace"), workspace=ws)
    with pytest.raises(ChError):
        ctx.fs.read_text(link)


class _Response:
    status = 200

    def __init__(self, body=b"ok"):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_network_guard(tmp_path):
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, request.get_method(), request.data))
        return _Response()

    ctx = _ctx(tmp_path, Capabilities(network=("hooks.example.org",)), opener=opener)
    status, body = ctx.net.post_json("https://hooks.example.org/x", {"a": 1})
    assert status == 200 and body == b"ok" and json.loads(calls[0][2]) == {"a": 1}
    with pytest.raises(ChError):
        ctx.net.request("GET", "https://evil.example.com/")
    with pytest.raises(ChError):
        ctx.net.request("GET", "file:///etc/passwd")                  # only http(s)
    denied = _ctx(tmp_path, Capabilities(network=False), opener=opener)
    with pytest.raises(ChError):
        denied.net.request("GET", "https://hooks.example.org/x")
    anywhere = _ctx(tmp_path, Capabilities(network=True), opener=opener)
    assert anywhere.net.request("GET", "https://any.org/")[0] == 200
    assert len(calls) == 2


def test_module_events_must_be_declared(tmp_path):
    bus = EventBus(strict=True)
    seen = []
    bus.subscribe(seen.append, sync=True)
    m, _ = manifest.loads(VALID.replace('commands = ["x"]', 'commands = ["x"]\nevents = ["mod.done"]'))
    from charpente.events.types import register_extension_event
    register_extension_event("mod.done")
    ctx = ModuleContext(m, Capabilities(), data_dir=tmp_path, bus=bus)
    ctx.emit("mod.done", n=1)
    assert seen and seen[0].type == "mod.done"
    with pytest.raises(ChError):
        ctx.emit("session.started")


def test_extension_events_cannot_shadow_builtin_ones():
    from charpente.events.types import register_extension_event
    with pytest.raises(ValueError):
        register_extension_event("action.started")
    with pytest.raises(ValueError):
        register_extension_event("nodot")


# ================================================================== registry
def _reg_for(m_text=VALID, builtin=None):
    reg = ExtensionRegistry(builtin)
    m, _ = manifest.loads(m_text)
    return reg, reg.for_module(m), m


class _Cmd:
    def __init__(self, name):
        self.name, self.help = name, ""

    def __call__(self, args):
        return 0


def test_registering_a_declared_extension_works():
    reg, view, _ = _reg_for()
    view.add_command(_Cmd("x"))
    assert reg.get("command", "x").module == "my-mod" and reg.names("command") == ["x"]
    assert [e.name for e in reg.by_module("my-mod")] == ["x"]
    reg.remove_module("my-mod")
    assert reg.get("command", "x") is None


def test_undeclared_extension_is_refused():
    _, view, _ = _reg_for()
    with pytest.raises(ChError) as exc:
        view.add_command(_Cmd("sneaky"))
    assert exc.value.code == "CH7014"


def test_duplicate_names_are_refused():
    reg, view, _ = _reg_for()
    view.add_command(_Cmd("x"))
    other = ExtensionRegistry.for_module(reg, manifest.loads(VALID.replace("my-mod", "other"))[0])
    with pytest.raises(ChError) as exc:
        other.add_command(_Cmd("x"))
    assert exc.value.code == "CH7008" and "my-mod" in str(exc.value)


def test_a_module_cannot_replace_a_builtin_command():
    _, view, _ = _reg_for(builtin=["x"])
    with pytest.raises(ChError) as exc:
        view.add_command(_Cmd("x"))
    assert exc.value.code == "CH7013"


# ==================================================================== store
def test_store_round_trip_and_bad_entries(store):
    assert store.list() == []
    store.put(InstalledModule("a", "1.0.0", "/p", approved=Capabilities(process=("git",)).to_dict()))
    store.put(InstalledModule("b", "2.0.0", "/q", enabled=False))
    assert [m.name for m in store.list()] == ["a", "b"]
    assert store.get("a").approved_caps().process == ("git",)
    assert store.set_enabled("b", True) and store.get("b").enabled
    assert not store.set_enabled("zz", True)
    assert store.set_approved("a", Capabilities(filesystem="build")) and store.get("a").approved_caps().filesystem == "build"
    data = json.loads((store.root / "modules.json").read_text())
    data["modules"]["future"] = {"unknown_field": 1}
    (store.root / "modules.json").write_text(json.dumps(data))
    assert [m.name for m in store.list()] == ["a", "b"]         # an entry from the future is ignored
    assert store.remove("a") and not store.remove("a")


def test_store_survives_a_corrupt_state_file(store):
    store.root.mkdir(parents=True)
    (store.root / "modules.json").write_text("{{{ not json")
    assert store.list() == [] and store.registries() == []
    store.add_registry("r1")
    assert store.registries() == ["r1"]


def test_registries(store):
    store.add_registry("https://a/index.json")
    store.add_registry("https://a/index.json")
    assert store.registries() == ["https://a/index.json"]
    assert store.remove_registry("https://a/index.json") and not store.remove_registry("nope")


# ================================================================= installer
def yes(_manifest, _status):
    return True


def no(_manifest, _status):
    return False


def test_unsigned_module_needs_confirmation(tmp_path, store):
    src = make_module(tmp_path / "src")
    with pytest.raises(ChError) as exc:
        installer.install(str(src), store)
    assert exc.value.code == "CH7010"
    with pytest.raises(ChError):
        installer.install(str(src), store, approve=no)
    assert store.list() == []
    record = installer.install(str(src), store, approve=yes)
    assert record.name == "my-mod" and record.signature == "unsigned" and record.enabled
    assert (Path(record.path) / "charpente-module.toml").exists()


def test_allow_unsigned_skips_the_unsigned_question_but_still_asks_about_capabilities(tmp_path, store):
    src = make_module(tmp_path / "src")
    asked = []

    def approve(m, s):
        asked.append(m.name)
        return False

    with pytest.raises(ChError):
        installer.install(str(src), store, approve=approve, allow_unsigned=True)
    assert asked == ["my-mod"]
    installer.install(str(src), store, approve=approve, allow_unsigned=True, assume_yes=True)
    assert store.get("my-mod") is not None


def test_signed_module_installs_and_records_the_key(tmp_path, store):
    src = make_module(tmp_path / "src")
    secret = bytes(range(9, 41))
    signing.write_signature(src, secret)
    pub = signing.public_key(secret)
    keys = {signing.key_id(pub): pub.hex()}
    record = installer.install(str(src), store, keys=keys, assume_yes=True, approve=yes)
    assert record.signature == f"signed:{signing.key_id(pub)}"


def test_a_tampered_signed_module_is_refused_outright(tmp_path, store):
    src = make_module(tmp_path / "src")
    secret = bytes(range(9, 41))
    signing.write_signature(src, secret)
    (src / "my_mod" / "__init__.py").write_text("print('evil')")
    pub = signing.public_key(secret)
    with pytest.raises(ChError) as exc:
        installer.install(str(src), store, allow_unsigned=True, assume_yes=True,
                          keys={signing.key_id(pub): pub.hex()})
    assert exc.value.code == "CH7007" and store.list() == []


def test_zip_install_and_zip_slip_protection(tmp_path, store):
    src = make_module(tmp_path / "src")
    archive = tmp_path / "m.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src.parent).as_posix())          # one top-level folder
    record = installer.install(str(archive), store, allow_unsigned=True, assume_yes=True, approve=yes)
    assert record.name == "my-mod"

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escaped.txt", "x")
        zf.writestr("charpente-module.toml", VALID)
    with pytest.raises(ChError) as exc:
        installer.install(str(evil), ModuleStore(tmp_path / "s2"), allow_unsigned=True, assume_yes=True, approve=yes)
    assert exc.value.code == "CH7007" and "unsafe path" in str(exc.value)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_reinstalling_the_same_version_is_refused_but_an_upgrade_replaces_it(tmp_path, store):
    v1 = make_module(tmp_path / "v1", version="1.0.0")
    v2 = make_module(tmp_path / "v2", version="1.1.0")
    installer.install(str(v1), store, allow_unsigned=True, assume_yes=True, approve=yes)
    with pytest.raises(ChError) as exc:
        installer.install(str(v1), store, allow_unsigned=True, assume_yes=True, approve=yes)
    assert exc.value.code == "CH7011"
    installer.install(str(v2), store, allow_unsigned=True, assume_yes=True, approve=yes)
    assert store.get("my-mod").version == "1.1.0"
    assert not store.package_dir("my-mod", "1.0.0").exists()


def test_incompatible_api_and_python_are_refused(tmp_path, store):
    old = make_module(tmp_path / "a", api="^1.0")
    with pytest.raises(ChError) as exc:
        installer.install(str(old), store, allow_unsigned=True, approve=yes)
    assert exc.value.code == "CH7004"
    new_python = make_module(tmp_path / "b", name="py-mod")
    text = (new_python / "charpente-module.toml").read_text().replace('license = "MIT"', 'license = "MIT"\npython = ">=99.0"')
    (new_python / "charpente-module.toml").write_text(text)
    with pytest.raises(ChError) as exc:
        installer.install(str(new_python), store, allow_unsigned=True, approve=yes)
    assert "Python" in str(exc.value)


def _registry(tmp_path, releases):
    """A file-based registry: index.json + zips. releases: {name: {version: folder}}."""
    reg = tmp_path / "registry"
    reg.mkdir()
    index = {"modules": {}}
    import hashlib
    for name, versions in releases.items():
        for version, folder in versions.items():
            archive = reg / f"{name}-{version}.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for f in Path(folder).rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(folder).as_posix())
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            index["modules"].setdefault(name, {"versions": {}})["versions"][version] = {
                "url": archive.name, "sha256": sha}
    (reg / "index.json").write_text(json.dumps(index))
    return reg / "index.json"


def test_install_by_name_from_a_registry_picks_the_best_version(tmp_path, store):
    v1 = make_module(tmp_path / "v1", version="1.0.0")
    v2 = make_module(tmp_path / "v2", version="1.4.0")
    v3 = make_module(tmp_path / "v3", version="2.0.0")
    index = _registry(tmp_path, {"my-mod": {"1.0.0": v1, "1.4.0": v2, "2.0.0": v3}})
    record = installer.install("my-mod@^1.0", store, registries=[str(index)], allow_unsigned=True,
                               assume_yes=True, approve=yes)
    assert record.version == "1.4.0"


def test_registry_checksum_mismatch_is_refused(tmp_path, store):
    v1 = make_module(tmp_path / "v1")
    index = _registry(tmp_path, {"my-mod": {"1.0.0": v1}})
    data = json.loads(index.read_text())
    data["modules"]["my-mod"]["versions"]["1.0.0"]["sha256"] = "0" * 64
    index.write_text(json.dumps(data))
    with pytest.raises(ChError) as exc:
        installer.install("my-mod", store, registries=[str(index)], allow_unsigned=True, assume_yes=True, approve=yes)
    assert exc.value.code == "CH6002"


def test_unknown_module_and_missing_registry(tmp_path, store):
    with pytest.raises(ChError) as exc:
        installer.install("ghost", store)
    assert exc.value.code == "CH7006" and "registry" in str(exc.value)
    index = _registry(tmp_path, {})
    with pytest.raises(ChError) as exc:
        installer.install("ghost", store, registries=[str(index)])
    assert exc.value.code == "CH7006"
    with pytest.raises(ChError) as exc:
        installer.read_index(str(tmp_path / "nope.json"))
    assert exc.value.code == "CH7012"
    (tmp_path / "bad.json").write_text("[]")
    with pytest.raises(ChError) as exc:
        installer.read_index(str(tmp_path / "bad.json"))
    assert exc.value.code == "CH7012"


def test_update_installs_only_newer_versions(tmp_path, store):
    v1 = make_module(tmp_path / "v1", version="1.0.0")
    v2 = make_module(tmp_path / "v2", version="1.1.0")
    index = _registry(tmp_path, {"my-mod": {"1.0.0": v1, "1.1.0": v2}})
    store.add_registry(str(index))
    installer.install(str(v1), store, allow_unsigned=True, assume_yes=True, approve=yes)
    updated = installer.update("my-mod", store, allow_unsigned=True, assume_yes=True, approve=yes)
    assert updated is not None and updated.version == "1.1.0"
    assert installer.update("my-mod", store, allow_unsigned=True, assume_yes=True, approve=yes) is None
    with pytest.raises(ChError):
        installer.update("not-installed", store)


# ==================================================================== loader
def install(tmp_path, store, **kw):
    src = make_module(tmp_path / "src", **kw)
    return installer.install(str(src), store, allow_unsigned=True, assume_yes=True, approve=yes)


def test_enabled_modules_are_loaded_and_their_commands_indexed(tmp_path, store):
    install(tmp_path, store)
    manager = ModuleManager(store, builtin_commands=["build"])
    assert manager.command_index() == {"cmd-my-mod": "my-mod"}          # from manifests, nothing imported
    registry = manager.load_all()
    assert registry.get("command", "cmd-my-mod").obj([]) == 7
    assert manager.problems == {}


def test_disabled_modules_are_neither_indexed_nor_loaded(tmp_path, store):
    install(tmp_path, store)
    store.set_enabled("my-mod", False)
    manager = ModuleManager(store)
    assert manager.command_index() == {} and manager.load_all().names("command") == []


def test_a_module_that_fails_to_import_is_skipped_with_a_reason(tmp_path, store):
    install(tmp_path, store, body="raise RuntimeError('boom at import')")
    manager = ModuleManager(store)
    manager.load_all()
    assert manager.problems["my-mod"].code == "CH7009" and "boom at import" in str(manager.problems["my-mod"])
    assert manager.registry.names("command") == []


def test_a_module_whose_register_raises_leaves_nothing_behind(tmp_path, store):
    body = """
        class C:
            name = "cmd-my-mod"; help = ""
            def __call__(self, a): return 0
        def register(registry, ctx):
            registry.add_command(C())
            raise ValueError("late failure")
    """
    install(tmp_path, store, body=body)
    manager = ModuleManager(store)
    manager.load_all()
    assert "my-mod" in manager.problems and manager.registry.names("command") == []


def test_undeclared_registration_disables_the_module(tmp_path, store):
    body = """
        class C:
            name = "not-declared"; help = ""
            def __call__(self, a): return 0
        def register(registry, ctx):
            registry.add_command(C())
    """
    install(tmp_path, store, body=body)
    manager = ModuleManager(store)
    manager.load_all()
    assert manager.problems["my-mod"].code == "CH7014"


def test_more_capabilities_than_approved_keeps_a_module_disabled_until_reapproved(tmp_path, store):
    install(tmp_path, store)
    folder = store.package_dir("my-mod", "1.0.0")
    text = (folder / "charpente-module.toml").read_text().replace("[capabilities]", '[capabilities]\nnetwork = true')
    (folder / "charpente-module.toml").write_text(text)                # e.g. an update asked for more
    manager = ModuleManager(store)
    manager.load_all()
    assert manager.problems["my-mod"].code == "CH7015"
    store.set_approved("my-mod", Capabilities(network=True))
    manager2 = ModuleManager(store)
    manager2.load_all()
    assert manager2.problems == {}


def test_a_later_api_break_is_reported_not_fatal(tmp_path, store):
    install(tmp_path, store)
    folder = store.package_dir("my-mod", "1.0.0")
    (folder / "charpente-module.toml").write_text(
        (folder / "charpente-module.toml").read_text().replace('api = "^2.0"', 'api = "^9.0"'))
    manager = ModuleManager(store)
    manager.load_all()
    assert manager.problems["my-mod"].code == "CH7004"


def test_module_context_gets_the_approved_capabilities_and_a_data_dir(tmp_path, store):
    body = """
        seen = {}
        class C:
            name = "cmd-my-mod"; help = ""
            def __call__(self, a): return 0
        def register(registry, ctx):
            seen["caps"] = ctx.approved
            seen["data"] = ctx.data_dir
            registry.add_command(C())
    """
    install(tmp_path, store, body=body, caps='process = ["git"]')
    manager = ModuleManager(store)
    manager.load_all()
    mod = sys.modules["my_mod"]
    assert mod.seen["caps"].process == ("git",) and mod.seen["data"] == store.data_dir("my-mod")
    manager.set_workspace(tmp_path)
    assert manager.contexts["my-mod"].workspace_root == tmp_path


def test_register_with_a_single_parameter_is_supported(tmp_path, store):
    body = """
        class C:
            name = "cmd-my-mod"; help = ""
            def __call__(self, a): return 5
        def register(registry):
            registry.add_command(C())
    """
    install(tmp_path, store, body=body)
    manager = ModuleManager(store)
    assert manager.load_all().get("command", "cmd-my-mod").obj([]) == 5


# ================================================== the example third-party module
def test_the_example_module_passes_conformance_and_works(tmp_path, store, capsys):
    issues = conformance.check_module(EXAMPLE)
    assert not conformance.has_errors(issues), issues
    record = installer.install(str(EXAMPLE), store, allow_unsigned=True, assume_yes=True, approve=yes)
    bus = EventBus(strict=True)
    seen = []
    bus.subscribe(seen.append, sync=True)
    manager = ModuleManager(store, bus=bus)
    registry = manager.load_all()
    assert manager.problems == {}
    assert registry.get("command", "hello").obj(["Ada"]) == 0
    assert "Hello, Ada!" in capsys.readouterr().out
    assert [e.type for e in seen] == ["hello.said"]
    tcs = registry.get("toolchain", "example-cc").obj.detect(OS.LINUX, lambda n: "/opt/cc" if n == "example-cc" else None)
    assert tcs[0].name == "example-cc"
    assert record.version == "1.0.0"


def test_module_toolchains_join_detection_after_the_builtin_ones(tmp_path, monkeypatch):
    from charpente import toolchains
    from charpente.modules import runtime

    ModuleStore().root.mkdir(parents=True, exist_ok=True)
    installer.install(str(EXAMPLE), ModuleStore(), allow_unsigned=True, assume_yes=True, approve=yes)
    runtime.reset()
    found = toolchains.detect(OS.LINUX, lambda n: f"/bin/{n}" if n in ("gcc", "g++", "clang", "clang++", "example-cc") else None)
    assert [t.name for t in found] == ["gcc", "clang", "example-cc"]          # built-in preference order kept
    assert toolchains.pick_default(OS.LINUX, lambda n: "/bin/example-cc" if n == "example-cc" else None).name == "example-cc"


def test_builtin_toolchain_preference_order_is_unchanged():
    from charpente import toolchains

    everything = lambda n: f"C:/bin/{n}"          # noqa: E731
    assert [t.name for t in toolchains.detect(OS.WINDOWS, everything)] == ["msvc", "clang-cl", "mingw"]
    assert [t.name for t in toolchains.detect(OS.LINUX, everything)] == ["gcc", "clang"]
    assert [t.name for t in toolchains.detect(OS.MACOS, everything)] == ["apple-clang"]


# ================================================================ conformance
def test_conformance_flags_each_kind_of_problem(tmp_path):
    ok = make_module(tmp_path / "ok")
    assert [i.message for i in conformance.check_module(ok)] == ["not signed by a trusted key (no signature file)"]

    declared_not_registered = make_module(tmp_path / "a", body="def register(registry, ctx):\n    pass\n")
    assert any("never registers" in i.message for i in conformance.check_module(declared_not_registered))

    broken = make_module(tmp_path / "b", body="import nonexistent_thing_xyz\n")
    assert any("cannot be imported" in i.message for i in conformance.check_module(broken))

    wrong_interface = make_module(tmp_path / "c", body="""
        class Bad:
            name = "cmd-c"
        def register(registry, ctx):
            registry.add_command(Bad())
    """, name="c")
    assert any("does not implement" in i.message for i in conformance.check_module(wrong_interface))

    risky = make_module(tmp_path / "d", name="d", body="""
        import subprocess, os
        class C:
            name = "cmd-d"; help = ""
            def __call__(self, a):
                os.system("echo hi")
                return 0
        def register(registry, ctx):
            registry.add_command(C())
    """)
    issues = conformance.check_module(risky)
    assert not conformance.has_errors(issues)
    text = " ".join(i.message for i in issues)
    assert "imports subprocess" in text and "os.system" in text and "not signed" in text

    assert conformance.has_errors(conformance.check_module(tmp_path / "missing-folder"))


def test_conformance_cleans_up_after_itself(tmp_path):
    folder = make_module(tmp_path / "z", name="zed")
    before = list(sys.path)
    conformance.check_module(folder)
    assert sys.path == before and "zed" not in sys.modules
