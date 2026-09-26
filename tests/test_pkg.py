import hashlib
import io
import json
import os
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest
from helpers import GCC, FakeToolchain

from charpente import builder
from charpente.cli import main
from charpente.commands._common import load
from charpente.core.planner import plan_workspace
from charpente.dsl.loader import load_workspace
from charpente.dsl.model import OS, Kind
from charpente.errors import ChError
from charpente.pkg import audit as audit_mod
from charpente.pkg import fetch, index, lock, materialize, mirror, recipe, resolver, sbom, vendor
from charpente.pkg import install as install_mod
from charpente.pkg.store import PackageStore, file_sha256
from charpente.platform import host_os
from charpente.toolchains import NoToolchainFoundError, pick_default

SCHEMAS = Path(__file__).resolve().parent / "fixtures" / "schemas"


def _has_compiler() -> bool:
    try:
        pick_default(host_os())
        return True
    except NoToolchainFoundError:
        return False


requires_compiler = pytest.mark.skipif(not _has_compiler(), reason="no C/C++ compiler on PATH")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("CHARPENTE_PKG_DIR", str(tmp_path / "pkgstore"))
    monkeypatch.delenv("CHARPENTE_RECIPES", raising=False)
    monkeypatch.delenv("CHARPENTE_OFFLINE", raising=False)


# ------------------------------------------------------------------ fixtures
def make_tar(path: Path, files: dict, prefix: str = "lib-1.0") -> str:
    with tarfile.open(path, "w:gz") as tf:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{prefix}/{name}" if prefix else name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe_text(name="mylib", version="1.0.0", url="file:///x", sha="0" * 64, deps=(), build=None, license="MIT",
                extra=""):
    build = build or 'type = "header_only"\ninclude_dirs = ["include"]\n'
    return textwrap.dedent(f"""
        [package]
        name = "{name}"
        version = "{version}"
        license = "{license}"
        description = "test package"
        purl = "pkg:github/example/{name}"
        [source]
        url = "{url}"
        sha256 = "{sha}"
        strip_prefix = "lib-1.0"
        [build]
        {build}
        [dependencies]
        requires = {json.dumps(list(deps))}
        {extra}
    """)


class Env:
    """A recipe folder, archives, and a workspace, all in tmp_path."""

    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path / "proj"
        self.root.mkdir()
        self.recipes = tmp_path / "recipes"
        self.recipes.mkdir()
        self.archives = tmp_path / "archives"
        self.archives.mkdir()
        monkeypatch.setenv("CHARPENTE_RECIPES", str(self.recipes))
        self.store = PackageStore()

    def package(self, name, version, files, deps=(), build=None, extra="", prefix="lib-1.0"):
        archive = self.archives / f"{name}-{version}.tar.gz"
        sha = make_tar(archive, files, prefix)
        text = recipe_text(name, version, archive.as_uri(), sha, deps, build, extra=extra)
        (self.recipes / f"{name}-{version}.toml").write_text(text)
        return archive, sha

    def workspace(self, requires, extra_dsl=""):
        (self.root / "main.cpp").write_text("int main(){return 0;}")
        (self.root / "w.charpente").write_text(textwrap.dedent(f"""
            from charpente import *
            with Workspace("W", version="1.0.0") as ws:
                ws.requires({', '.join(repr(r) for r in requires)})
                with Target("app") as t:
                    t.sources(["main.cpp"])
                    {extra_dsl}
        """))
        return load_workspace(str(self.root / "w.charpente"))

    def index(self, workspace=None):
        return index.RecipeIndex(self.store, workspace_root=workspace.root if workspace else None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


# ===================================================================== recipes
def test_a_valid_recipe_parses_with_a_digest_of_its_bytes(tmp_path):
    path = tmp_path / "r.toml"
    path.write_text(recipe_text(build='type = "sources"\nsources = ["a.c"]\nlanguage = "c"\ninclude_dirs = ["inc"]\n'
                                      'defines = ["X=1"]\n\n[build.platform."windows-*"]\nlinks = ["ws2_32"]\n'))
    r = recipe.load(path)
    assert (r.name, r.version, r.license) == ("mylib", "1.0.0", "MIT")
    assert r.build.type == "sources" and r.build.language == "c" and r.build.sources == ("a.c",)
    assert r.build.overrides_for("windows-x64")[0].links == ("ws2_32",) and r.build.overrides_for("linux-x64") == []
    assert r.digest == hashlib.sha256(path.read_bytes()).hexdigest() and r.ident == "mylib@1.0.0"


@pytest.mark.parametrize("edit,fragment", [
    (lambda t: t.replace('sha256 = "' + "0" * 64 + '"', 'sha256 = "abc"'), "sha256"),
    (lambda t: t.replace('version = "1.0.0"', 'version = "one"'), "version"),
    (lambda t: t.replace('name = "mylib"', 'name = "bad name"'), "name"),
    (lambda t: t.replace('type = "header_only"', 'type = "cmake"'), "type"),
    (lambda t: t.replace("[build]", "[build]\nbogus = 1"), "bogus"),
    (lambda t: t.replace("[dependencies]", "[surprise]\nx = 1\n[dependencies]"), "surprise"),
    (lambda t: t.replace('requires = []', 'requires = ["bad name@^1"]'), "NAME"),
    (lambda t: t.replace('license = "MIT"\n', ""), "license"),
    (lambda t: "not toml [", "TOML"),
])
def test_invalid_recipes_are_specific(edit, fragment):
    with pytest.raises(ChError) as exc:
        recipe.parse(edit(recipe_text()), "r.toml")
    assert exc.value.code == "CH6008" and fragment in str(exc.value)


def test_a_sources_build_needs_sources():
    with pytest.raises(ChError, match="sources"):
        recipe.parse(recipe_text(build='type = "sources"\n'))


def test_every_bundled_recipe_is_valid_and_pinned():
    files = sorted(index.BUNDLED_DIR.glob("*.toml"))
    assert len(files) >= 8
    seen = set()
    for path in files:
        r = recipe.load(path)
        local = r.source.url.startswith("charpente://")            # a kit shipped inside Charpente: no download, no purl
        assert (local or r.source.url.startswith("https://")) and len(r.source.sha256) == 64
        assert r.license and r.description and (local or (r.purl and r.source.strip_prefix))
        assert (r.name, r.version) not in seen
        seen.add((r.name, r.version))
        assert path.stem.lower() == f"{r.name}-{r.version}".lower()
    assert {"fmt", "spdlog", "doctest", "nlohmann_json", "glm", "CLI11", "entt", "vulkan-headers"} <= {n for n, _ in seen}


# ===================================================================== index
def test_bundled_recipes_are_found_and_local_recipes_shadow_nothing(env):
    idx = env.index()
    assert "fmt" in idx.names() and idx.versions("fmt") == ["10.2.1"]
    env.package("fmt", "99.0.0", {"include/x.h": ""})
    idx = env.index()
    assert idx.versions("fmt") == ["10.2.1", "99.0.0"]
    assert idx.ref("fmt", "99.0.0").origin == "local" and idx.ref("fmt", "10.2.1").origin == "bundled"
    assert idx.best("fmt", recipe.constraint_of("fmt@^10")[1]) == "10.2.1"


def test_a_broken_local_recipe_hides_itself_not_the_others(env):
    (env.recipes / "broken.toml").write_text("this is not a recipe [")
    env.package("ok", "1.0.0", {"include/a.h": ""})
    assert "ok" in env.index().names()


def test_registry_index_with_relative_urls(env, tmp_path):
    archive, sha = make_tar(tmp_path / "reg-a.tar.gz", {"include/a.h": ""}), None
    reg = tmp_path / "reg"
    (reg / "recipes").mkdir(parents=True)
    text = recipe_text("remote", "2.0.0", "../a.tar.gz", archive)
    (reg / "recipes" / "remote-2.0.0.toml").write_text(text)
    (reg / "a.tar.gz").write_bytes((tmp_path / "reg-a.tar.gz").read_bytes())
    digest = hashlib.sha256((reg / "recipes" / "remote-2.0.0.toml").read_bytes()).hexdigest()
    (reg / "index.json").write_text(json.dumps({"packages": {"remote": {"versions": {"2.0.0": {
        "recipe": "recipes/remote-2.0.0.toml", "sha256": digest}}}}}))
    idx = index.RecipeIndex(PackageStore(), [str(reg / "index.json")])
    assert idx.versions("remote") == ["2.0.0"]
    r = idx.load(idx.ref("remote", "2.0.0"))
    assert r.name == "remote" and PackageStore().recipe_path("remote", "2.0.0", r.digest).exists()
    assert sha is None


def test_registry_recipe_with_a_wrong_digest_is_refused(env, tmp_path):
    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "r.toml").write_text(recipe_text("remote", "1.0.0"))
    (reg / "index.json").write_text(json.dumps({"packages": {"remote": {"versions": {"1.0.0": {
        "recipe": "r.toml", "sha256": "0" * 64}}}}}))
    idx = index.RecipeIndex(PackageStore(), [str(reg / "index.json")])
    with pytest.raises(ChError) as exc:
        idx.load(idx.ref("remote", "1.0.0"))
    assert exc.value.code == "CH6002"


def test_bad_registry_indexes_are_reported(env, tmp_path):
    (tmp_path / "bad.json").write_text("[]")
    idx = index.RecipeIndex(PackageStore(), [str(tmp_path / "bad.json")])
    with pytest.raises(ChError) as exc:
        idx.names()
    assert exc.value.code == "CH7012"


def test_offline_mode_ignores_remote_registries(env, monkeypatch):
    monkeypatch.setenv("CHARPENTE_OFFLINE", "1")
    idx = index.RecipeIndex(PackageStore(), ["https://registry.example.org/index.json"])
    assert "fmt" in idx.names()                       # bundled recipes still work


# ==================================================================== resolver
def test_highest_matching_version_wins(env):
    for v in ("1.0.0", "1.4.0", "2.0.0"):
        env.package("dep", v, {"include/a.h": ""})
    out = resolver.resolve(["dep@^1"], env.index())
    assert out["dep"].recipe.version == "1.4.0" and out["dep"].requested_by == ["workspace"]


def test_transitive_dependencies_and_install_order(env):
    env.package("base", "1.0.0", {"include/b.h": ""})
    env.package("mid", "1.0.0", {"include/m.h": ""}, deps=["base@^1"])
    env.package("top", "1.0.0", {"include/t.h": ""}, deps=["mid@^1"])
    out = resolver.resolve(["top"], env.index())
    assert set(out) == {"top", "mid", "base"}
    assert resolver.install_order(out) == ["base", "mid", "top"]
    assert out["base"].requested_by == ["mid@1.0.0"]


def test_backtracking_finds_an_older_version_that_fits(env):
    env.package("b", "1.0.0", {"include/b.h": ""})
    env.package("b", "2.0.0", {"include/b.h": ""})
    env.package("a", "1.0.0", {"include/a.h": ""}, deps=["b@^1"])
    env.package("a", "2.0.0", {"include/a.h": ""}, deps=["b@^2"])
    out = resolver.resolve(["a", "b@^1"], env.index())           # a@2 would need b@2, but b@^1 is required
    assert out["a"].recipe.version == "1.0.0" and out["b"].recipe.version == "1.0.0"


def test_conflicts_say_who_wants_what(env):
    env.package("b", "1.0.0", {"include/b.h": ""})
    env.package("a", "1.0.0", {"include/a.h": ""}, deps=["b@^2"])
    with pytest.raises(ChError) as exc:
        resolver.resolve(["a"], env.index())
    assert exc.value.code == "CH6010" and "a@1.0.0 needs b@^2" in str(exc.value) and "1.0.0" in str(exc.value)


def test_unknown_package(env):
    with pytest.raises(ChError) as exc:
        resolver.resolve(["no-such-package"], env.index())
    assert exc.value.code == "CH6007"
    env.package("a", "1.0.0", {"include/a.h": ""}, deps=["ghost@^1"])
    with pytest.raises(ChError) as exc:
        resolver.resolve(["a"], env.index())
    assert exc.value.code == "CH6007"


def test_preferred_versions_keep_the_lock_stable(env):
    for v in ("1.0.0", "1.1.0"):
        env.package("dep", v, {"include/a.h": ""})
    assert resolver.resolve(["dep@^1"], env.index(), preferred={"dep": "1.0.0"})["dep"].recipe.version == "1.0.0"
    assert resolver.resolve(["dep@^1"], env.index(), preferred={"dep": "9.9.9"})["dep"].recipe.version == "1.1.0"


# ====================================================================== lock
def test_lock_round_trip_and_requirement_matching():
    lk = lock.Lock({"fmt": lock.LockedPackage("fmt", "10.2.1", "r" * 64, "https://x/f.tgz", "s" * 64,
                                              ("other@^1",), ("workspace",))})
    again = lock.loads(lk.dumps())
    assert again.packages == lk.packages
    assert lock.matches_requirements(again, ["fmt@^10", "fmt"]) and not lock.matches_requirements(again, ["fmt@^11"])
    assert not lock.matches_requirements(again, ["glm"])


@pytest.mark.parametrize("text", ["not toml [", "lock_version = 9\n", "lock_version = 1\n[[package]]\nname = 'x'\n"])
def test_bad_lock_files(text):
    with pytest.raises(ChError) as exc:
        lock.loads(text)
    assert exc.value.code == "CH6006"


# ==================================================================== archives
def test_extraction_strips_the_prefix_and_reads_files(tmp_path):
    archive = tmp_path / "a.tar.gz"
    make_tar(archive, {"include/a.h": "hello", "src/a.c": "x"})
    dest = tmp_path / "out"
    fetch.extract(archive, dest, "lib-1.0")
    assert (dest / "include" / "a.h").read_text() == "hello" and not (dest / "lib-1.0").exists()


def test_zip_archives_work(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("top/include/z.h", "zip")
    dest = tmp_path / "out"
    fetch.extract(archive, dest, "top")
    assert (dest / "include" / "z.h").read_text() == "zip"


def test_hostile_archives_are_refused(tmp_path):
    for evil_name in ("../escape.txt", "lib-1.0/../../escape.txt", "/abs/escape.txt"):
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo(evil_name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        with pytest.raises(ChError) as exc:
            fetch.extract(archive, tmp_path / "o1", "")
        assert exc.value.code == "CH6012" and "unsafe path" in str(exc.value)
    assert not (tmp_path.parent / "escape.txt").exists()

    linked = tmp_path / "link.tar.gz"
    with tarfile.open(linked, "w:gz") as tf:
        info = tarfile.TarInfo("lib-1.0/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        tf.addfile(info)
    with pytest.raises(ChError, match="points outside"):
        fetch.extract(linked, tmp_path / "o2", "lib-1.0")

    zipped = tmp_path / "slip.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        zf.writestr("../slip.txt", "x")
    with pytest.raises(ChError, match="unsafe path"):
        fetch.extract(zipped, tmp_path / "o3", "")


def test_harmless_symlinks_are_skipped_not_created(tmp_path):
    archive = tmp_path / "ok.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        data = b"content"
        info = tarfile.TarInfo("lib-1.0/real.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("lib-1.0/alias.txt")
        link.type = tarfile.SYMTYPE
        link.linkname = "real.txt"
        tf.addfile(link)
    fetch.extract(archive, tmp_path / "out", "lib-1.0")
    assert (tmp_path / "out" / "real.txt").exists() and not (tmp_path / "out" / "alias.txt").exists()


def test_missing_prefix_and_corrupt_archive(tmp_path):
    archive = tmp_path / "a.tar.gz"
    make_tar(archive, {"a.h": "x"})
    with pytest.raises(ChError, match="strip_prefix"):
        fetch.extract(archive, tmp_path / "o", "no-such-prefix")
    (tmp_path / "junk.tar.gz").write_bytes(b"this is not an archive")
    with pytest.raises(ChError) as exc:
        fetch.extract(tmp_path / "junk.tar.gz", tmp_path / "o2", "")
    assert exc.value.code == "CH6012"


@pytest.mark.skipif(os.name != "nt", reason="the 260-character limit is a Windows matter")
def test_paths_longer_than_260_characters_extract_on_windows(tmp_path):
    archive = tmp_path / "deep.tar.gz"
    deep = "/".join(["d" * 40] * 8) + "/file.txt"
    make_tar(archive, {deep: "deep"})
    dest = tmp_path / "x"
    fetch.extract(archive, dest, "lib-1.0")
    assert (dest.parts and any(True for _ in os.walk("\\\\?\\" + str(dest))))


def test_unified_diff_patches(tmp_path):
    (tmp_path / "f.txt").write_text("one\ntwo\nthree\n")
    diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
    assert fetch.apply_unified_diff(diff, tmp_path) == ["f.txt"]
    assert (tmp_path / "f.txt").read_text() == "one\nTWO\nthree\n"
    with pytest.raises(ChError) as exc:
        fetch.apply_unified_diff(diff, tmp_path)                         # already applied: context no longer matches
    assert exc.value.code == "CH6011"
    with pytest.raises(ChError):
        fetch.apply_unified_diff("--- a/../evil.txt\n+++ b/../evil.txt\n@@ -0,0 +1 @@\n+x\n", tmp_path)


# ================================================================== install
LIB_SOURCES = {"include/mylib.h": "#pragma once\nint triple(int);\n", "src/mylib.cpp":
               '#include "mylib.h"\nint triple(int x) { return x * 3; }\n'}
SRC_BUILD = 'type = "sources"\nsources = ["src/*.cpp"]\ninclude_dirs = ["include"]\nstandard = "c++17"\n'


def test_install_resolves_fetches_verifies_and_locks(env):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["mylib@^1"])
    messages = []
    lk = install_mod.install(ws, env.store, env.index(ws), progress=messages.append)
    assert lk.packages["mylib"].version == "1.0.0" and (env.root / "charpente.lock").exists()
    tree = env.store.source_dir("mylib", "1.0.0", lk.packages["mylib"].recipe_sha256)
    assert (tree / "include" / "mylib.h").exists()
    assert any("Wrote charpente.lock" in m for m in messages)
    assert install_mod.is_installed(ws, env.store)
    again = []
    install_mod.install(ws, env.store, env.index(ws), progress=again.append)
    assert again == ["Everything in charpente.lock is already installed."]


def test_a_tampered_archive_is_never_unpacked(env):
    archive, _sha = env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    ws = env.workspace(["mylib"])
    with pytest.raises(ChError) as exc:
        install_mod.install(ws, env.store, env.index(ws))
    assert exc.value.code == "CH6002" and not list((env.store.root / "src").glob("*")) if (env.store.root / "src").exists() else True


def test_install_with_patches(env):
    archive = env.archives / "p.tar.gz"
    sha = make_tar(archive, {"include/mylib.h": "line one\nline two\n"})
    patch = "--- a/include/mylib.h\n+++ b/include/mylib.h\n@@ -1,2 +1,2 @@\n line one\n-line two\n+line PATCHED\n"
    (env.recipes / "mylib-1.0.0.toml").write_text(
        recipe_text("mylib", "1.0.0", archive.as_uri(), sha) + '\n[[patch]]\nfile = "fix.patch"\n')
    (env.recipes / "fix.patch").write_text(patch)
    ws = env.workspace(["mylib"])
    lk = install_mod.install(ws, env.store, env.index(ws))
    tree = env.store.source_dir("mylib", "1.0.0", lk.packages["mylib"].recipe_sha256)
    assert "PATCHED" in (tree / "include" / "mylib.h").read_text()
    # the patch travels with the stored recipe, so a later offline build does not need the recipe folder
    materialize.load_locked_recipe(lk.packages["mylib"], ws.root, env.store)


def test_update_only_moves_when_asked(env):
    env.package("dep", "1.0.0", {"include/a.h": ""})
    ws = env.workspace(["dep@^1"])
    install_mod.install(ws, env.store, env.index(ws))
    env.package("dep", "1.5.0", {"include/a.h": ""})
    install_mod.install(ws, env.store, env.index(ws))
    assert lock.load(ws.root).packages["dep"].version == "1.0.0"          # the lock keeps it
    install_mod.install(ws, env.store, env.index(ws), update=True)
    assert lock.load(ws.root).packages["dep"].version == "1.5.0"


def test_changed_requirements_are_re_resolved(env):
    env.package("dep", "1.0.0", {"include/a.h": ""})
    env.package("dep", "2.0.0", {"include/a.h": ""})
    ws = env.workspace(["dep@^1"])
    install_mod.install(ws, env.store, env.index(ws))
    ws2 = env.workspace(["dep@^2"])
    install_mod.install(ws2, env.store, env.index(ws2))
    assert lock.load(ws.root).packages["dep"].version == "2.0.0"


def test_install_with_nothing_required(env):
    ws = env.workspace([])
    with pytest.raises(ChError) as exc:
        install_mod.install(ws, env.store, env.index(ws))
    assert exc.value.code == "CH4005"


# ================================================================ materialize
def test_builds_refuse_to_download_and_say_what_to_run(env):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["mylib"])
    with pytest.raises(ChError) as exc:
        materialize.materialize(ws, env.store)
    assert exc.value.code == "CH6005" and "charpente pkg install" in exc.value.format()
    assert not (env.store.root / "downloads").exists()                    # nothing was fetched


def test_packages_become_targets_with_public_settings(env):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD + 'defines = ["MYLIB=1"]\nlinks = ["m"]\n')
    ws = env.workspace(["mylib"], extra_dsl='t.uses("mylib")')
    install_mod.install(ws, env.store, env.index(ws))
    added = materialize.materialize(ws, env.store)
    assert added == ["mylib"]
    pkg = ws.targets["mylib"]
    assert pkg.external and pkg.kind == Kind.STATIC_LIBRARY and pkg.location.is_dir()
    assert any(d.endswith("include") for d in pkg.public_include_dirs) and pkg.public_define_macros == ["MYLIB=1"]
    p = plan_workspace(ws, GCC, OS.LINUX)
    assert any(a.startswith("-I") and a.endswith("include") for a in p.graph.actions["compile:app:main.cpp"].argv)
    assert "-DMYLIB=1" in p.graph.actions["compile:app:main.cpp"].argv
    assert "-lmylib" in p.graph.actions["link:app"].argv and "-lm" in p.graph.actions["link:app"].argv
    assert "archive:mylib" in p.graph.deps["link:app"]


def test_header_only_packages_add_no_actions(env):
    env.package("hdr", "1.0.0", {"include/hdr.h": "#pragma once\n"})
    ws = env.workspace(["hdr"], extra_dsl='t.uses("hdr")')
    install_mod.install(ws, env.store, env.index(ws))
    materialize.materialize(ws, env.store)
    p = plan_workspace(ws, GCC, OS.LINUX)
    assert list(p.target_actions) == ["app"] and ws.targets["hdr"].kind == Kind.HEADER_ONLY


def test_unused_packages_are_not_built_and_are_never_the_default_target(env):
    env.package("unused", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["unused"])                          # required, never used by app
    install_mod.install(ws, env.store, env.index(ws))
    materialize.materialize(ws, env.store)
    p = plan_workspace(ws, GCC, OS.LINUX)
    assert list(p.target_actions) == ["app"]
    from charpente.commands._common import resolve_target
    assert resolve_target(ws, None).name == "app"


def test_a_lock_that_no_longer_matches_the_requirements_is_reported(env):
    env.package("dep", "1.0.0", {"include/a.h": ""})
    ws = env.workspace(["dep"])
    install_mod.install(ws, env.store, env.index(ws))
    ws2 = env.workspace(["dep@^2"])
    with pytest.raises(ChError) as exc:
        materialize.materialize(ws2, env.store)
    assert exc.value.code == "CH6006"


def test_a_package_may_not_shadow_a_target(env):
    env.package("app", "1.0.0", {"include/a.h": ""})
    ws = env.workspace(["app"])
    install_mod.install(ws, env.store, env.index(ws))
    with pytest.raises(ChError) as exc:
        materialize.materialize(ws, env.store)
    assert exc.value.code == "CH6015"


def test_a_recipe_edited_after_locking_is_refused(env):
    env.package("dep", "1.0.0", {"include/a.h": ""})
    ws = env.workspace(["dep"])
    lk = install_mod.install(ws, env.store, env.index(ws))
    stored = env.store.recipe_path("dep", "1.0.0", lk.packages["dep"].recipe_sha256)
    stored.write_text(stored.read_text() + "\n# edited\n")
    with pytest.raises(ChError) as exc:
        materialize.materialize(ws, env.store)
    assert exc.value.code == "CH6009"


def test_dependencies_of_packages_propagate(env):
    env.package("base", "1.0.0", {"include/base.h": "#pragma once\n"}, build='type = "header_only"\ninclude_dirs = ["include"]\ndefines = ["BASE"]\n')
    env.package("mid", "1.0.0", {"include/mid.h": "#pragma once\n"}, deps=["base@^1"])
    ws = env.workspace(["mid"], extra_dsl='t.uses("mid")')
    install_mod.install(ws, env.store, env.index(ws))
    materialize.materialize(ws, env.store)
    argv = plan_workspace(ws, GCC, OS.LINUX).graph.actions["compile:app:main.cpp"].argv
    assert "-DBASE" in argv and sum(a.endswith("include") for a in argv) == 2


@requires_compiler
def test_a_package_builds_and_links_for_real(env, monkeypatch, capfd):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    (env.root / "main.cpp").write_text('#include <cstdio>\n#include "mylib.h"\nint main() { std::printf("triple=%d\\n", triple(14)); }\n')
    (env.root / "w.charpente").write_text(textwrap.dedent("""
        from charpente import *
        with Workspace("W") as ws:
            ws.requires("mylib@^1")
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("mylib")
    """))
    monkeypatch.chdir(env.root)
    assert main(["run"]) == 1 and "CH6005" in capfd.readouterr().err       # not installed: builds never download
    assert main(["pkg", "install"]) == 0
    capfd.readouterr()
    assert main(["run"]) == 0
    assert "triple=42" in capfd.readouterr().out
    assert main(["pkg", "check"]) == 0


# ===================================================================== vendor
def test_vendored_packages_build_without_the_store_or_recipes(env, monkeypatch):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["mylib"], extra_dsl='t.uses("mylib")')
    install_mod.install(ws, env.store, env.index(ws))
    done = vendor.vendor(ws, env.store)
    assert done == ["mylib"] and (env.root / "vendor" / "charpente-vendor.json").exists()
    assert vendor.verify(ws) == []

    # a machine with no store and no recipe folders at all
    monkeypatch.setenv("CHARPENTE_PKG_DIR", str(env.root.parent / "empty-store"))
    monkeypatch.delenv("CHARPENTE_RECIPES")
    fresh = load_workspace(str(env.root / "w.charpente"))
    materialize.materialize(fresh, PackageStore())
    assert fresh.targets["mylib"].location == env.root / "vendor" / "mylib-1.0.0"
    assert install_mod.is_installed(fresh, PackageStore())
    plan_workspace(fresh, GCC, OS.LINUX)


def test_vendor_verification_detects_modification(env):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["mylib"])
    install_mod.install(ws, env.store, env.index(ws))
    vendor.vendor(ws, env.store)
    (env.root / "vendor" / "mylib-1.0.0" / "include" / "mylib.h").write_text("// tampered")
    assert vendor.verify(ws) == ["mylib"]


def test_vendor_needs_a_lock_and_a_manifest(env):
    ws = env.workspace(["mylib"])
    with pytest.raises(ChError) as exc:
        vendor.vendor(ws, env.store)
    assert exc.value.code == "CH6005"
    with pytest.raises(ChError) as exc:
        vendor.verify(ws)
    assert exc.value.code == "CH6014"


# ====================================================================== mirror
def test_a_mirror_serves_packages_to_another_machine(env, tmp_path, monkeypatch):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    ws = env.workspace(["mylib"])
    install_mod.install(ws, env.store, env.index(ws))
    added = mirror.populate(ws, env.store, tmp_path / "mirror")
    assert added == ["mylib 1.0.0"] and (tmp_path / "mirror" / "index.json").exists()
    assert list((tmp_path / "mirror" / "archives").glob("*"))

    server, url = mirror.serve_in_background(tmp_path / "mirror")
    try:
        # the "other machine": empty store, no recipe folders, only the mirror
        monkeypatch.setenv("CHARPENTE_PKG_DIR", str(tmp_path / "other-store"))
        monkeypatch.delenv("CHARPENTE_RECIPES")
        other_root = tmp_path / "other"
        other_root.mkdir()
        (other_root / "main.cpp").write_text("int main(){}")
        (other_root / "w.charpente").write_text(
            'from charpente import *\nwith Workspace("W") as ws:\n    ws.requires("mylib")\n'
            '    with Target("app") as t:\n        t.sources(["main.cpp"])\n        t.uses("mylib")\n')
        other = load_workspace(str(other_root / "w.charpente"))
        store2 = PackageStore()
        idx = index.RecipeIndex(store2, [url])
        install_mod.install(other, store2, idx)
        materialize.materialize(other, store2)
        assert other.targets["mylib"].location.is_dir()
        assert lock.load(other_root).packages["mylib"].source_url.startswith("http://127.0.0.1")
    finally:
        server.shutdown()
        server.server_close()


def test_the_mirror_supports_range_requests(tmp_path):
    (tmp_path / "index.json").write_text("{}")
    (tmp_path / "blob.bin").write_bytes(bytes(range(200)))
    server, url = mirror.serve_in_background(tmp_path)
    try:
        import urllib.request
        base = url.rsplit("/", 1)[0]
        req = urllib.request.Request(base + "/blob.bin", headers={"Range": "bytes=150-"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206 and r.read() == bytes(range(150, 200))
        with urllib.request.urlopen(base + "/blob.bin") as r:
            assert r.status == 200 and len(r.read()) == 200
        bad = urllib.request.Request(base + "/blob.bin", headers={"Range": "bytes=500-"})
        with pytest.raises(Exception) as exc:
            urllib.request.urlopen(bad)
        assert "416" in str(exc.value)
    finally:
        server.shutdown()
        server.server_close()


# ======================================================================= audit
class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _lock_and_recipes(env):
    env.package("vuln", "1.0.0", {"include/a.h": ""})
    env.package("safe", "1.0.0", {"include/b.h": ""})
    (env.recipes / "nopurl-1.0.0.toml").write_text(recipe_text("nopurl").replace('purl = "pkg:github/example/nopurl"\n', ""))
    ws = env.workspace(["vuln", "safe"])
    lk = install_mod.install(ws, env.store, env.index(ws))
    recipes = {n: materialize.load_locked_recipe(lk.packages[n], ws.root, env.store)[0] for n in lk.packages}
    return lk, recipes


def test_audit_reports_findings_and_unchecked_packages(env):
    lk, recipes = _lock_and_recipes(env)
    lk.packages["nopurl"] = lock.LockedPackage("nopurl", "1.0.0", "r", "u", "s")
    recipes["nopurl"] = recipe.parse(recipe_text("nopurl").replace('purl = "pkg:github/example/nopurl"\n', ""))
    seen = []

    def opener(request, timeout):
        body = json.loads(request.data)
        seen.append(body)
        if "example/vuln" in body["package"]["purl"]:
            return _Resp({"vulns": [{"id": "OSV-1", "summary": "bad thing", "aliases": ["CVE-1"],
                                     "severity": [{"type": "CVSS_V3", "score": "9.8"}]}]})
        return _Resp({})

    report = audit_mod.audit(lk, recipes, opener=opener)
    assert [f.id for f in report.findings] == ["OSV-1"] and report.findings[0].aliases == ("CVE-1",)
    assert report.unchecked == ["nopurl 1.0.0"] and report.checked == 2
    assert seen[0] == {"version": "1.0.0", "package": {"purl": "pkg:github/example/safe"}}      # only purl+version leave


def test_audit_network_failure_is_a_coded_error(env):
    lk, recipes = _lock_and_recipes(env)

    def failing(request, timeout):
        raise OSError("no network")

    with pytest.raises(ChError) as exc:
        audit_mod.audit(lk, recipes, opener=failing)
    assert exc.value.code == "CH6001"


# ======================================================================== SBOM
def _sbom_inputs(env):
    env.package("base", "1.0.0", {"include/b.h": ""})
    env.package("mylib", "2.1.0", {"include/m.h": ""}, deps=["base@^1"])
    ws = env.workspace(["mylib"])
    lk = install_mod.install(ws, env.store, env.index(ws))
    recipes = {n: materialize.load_locked_recipe(lk.packages[n], ws.root, env.store)[0] for n in lk.packages}
    return ws, lk, recipes


def test_spdx_and_cyclonedx_validate_against_the_official_schemas(env):
    jsonschema = pytest.importorskip("jsonschema")
    ws, lk, recipes = _sbom_inputs(env)
    spdx_doc = sbom.spdx("W", "1.0.0", lk, recipes)
    cdx_doc = sbom.cyclonedx("W", "1.0.0", lk, recipes)
    spdx_schema = json.loads((SCHEMAS / "spdx-schema-2.3.json").read_text(encoding="utf-8"))
    jsonschema.Draft7Validator(spdx_schema).validate(spdx_doc)
    from referencing import Registry, Resource
    resources = [(f"http://cyclonedx.org/schema/{n}", Resource.from_contents(json.loads((SCHEMAS / n).read_text(encoding="utf-8"))))
                 for n in ("spdx.schema.json", "jsf-0.82.schema.json")]
    registry = Registry().with_resources(resources)
    bom = json.loads((SCHEMAS / "bom-1.5.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft7Validator(bom, registry=registry).validate(cdx_doc)


def test_sbom_content_reflects_the_real_dependency_graph(env):
    ws, lk, recipes = _sbom_inputs(env)
    doc = sbom.spdx("W", "1.0.0", lk, recipes)
    names = {p["name"] for p in doc["packages"]}
    assert names == {"W", "base", "mylib"}
    mylib = next(p for p in doc["packages"] if p["name"] == "mylib")
    assert mylib["versionInfo"] == "2.1.0" and mylib["licenseDeclared"] == "MIT"
    assert mylib["checksums"][0]["checksumValue"] == lk.packages["mylib"].source_sha256
    rel = {(r["spdxElementId"], r["relationshipType"], r["relatedSpdxElement"]) for r in doc["relationships"]}
    assert ("SPDXRef-RootPackage", "DEPENDS_ON", "SPDXRef-Package-mylib-2.1.0") in rel
    assert ("SPDXRef-Package-mylib-2.1.0", "DEPENDS_ON", "SPDXRef-Package-base-1.0.0") in rel
    assert ("SPDXRef-RootPackage", "DEPENDS_ON", "SPDXRef-Package-base-1.0.0") not in rel        # transitive only
    cdx = sbom.cyclonedx("W", "1.0.0", lk, recipes)
    graph = {d["ref"]: d["dependsOn"] for d in cdx["dependencies"]}
    assert graph["app:W"] == ["pkg:mylib@2.1.0"] and graph["pkg:mylib@2.1.0"] == ["pkg:base@1.0.0"]
    assert next(c for c in cdx["components"] if c["name"] == "base")["purl"] == "pkg:github/example/base@1.0.0"


def test_sbom_of_a_workspace_without_packages_is_still_valid(env):
    jsonschema = pytest.importorskip("jsonschema")
    doc = sbom.spdx("W", "", lock.Lock(), {})
    jsonschema.Draft7Validator(json.loads((SCHEMAS / "spdx-schema-2.3.json").read_text(encoding="utf-8"))).validate(doc)
    assert [p["name"] for p in doc["packages"]] == ["W"]


# ========================================================================= CLI
def test_pkg_cli_flow(env, monkeypatch, capsys):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    (env.root / "main.cpp").write_text("int main(){}")
    (env.root / "w.charpente").write_text(
        'from charpente import *\nwith Workspace("W", version="3.0.0") as ws:\n    ws.requires("mylib@^1")\n'
        '    with Target("app") as t:\n        t.sources(["main.cpp"])\n        t.uses("mylib")\n')
    monkeypatch.chdir(env.root)
    assert main(["pkg", "check"]) == 1
    assert main(["pkg", "list"]) == 0 and "Run `charpente pkg install`" in capsys.readouterr().out
    assert main(["pkg", "search", "mylib"]) == 0 and "mylib" in capsys.readouterr().out
    assert main(["pkg", "search", "zzzz"]) == 1
    assert main(["pkg", "info", "mylib"]) == 0 and "MIT" in capsys.readouterr().out
    assert main(["pkg", "info", "ghost"]) == 1
    assert main(["pkg", "install"]) == 0
    assert main(["pkg", "list"]) == 0
    assert "mylib" in capsys.readouterr().out
    assert main(["pkg", "vendor"]) == 0 and main(["pkg", "vendor", "--verify"]) == 0
    assert main(["pkg", "mirror", "populate", str(env.root.parent / "m")]) == 0
    assert main(["pkg", "mirror", "serve", str(env.root.parent / "nothing-here")]) == 1
    assert main(["pkg", "registry", "add", "https://example.org/i.json"]) == 0
    assert main(["pkg", "registry", "list"]) == 0 and "example.org" in capsys.readouterr().out
    assert main(["pkg", "registry", "remove", "https://example.org/i.json"]) == 0
    assert main(["pkg", "install", "--max-download", "banana"]) == 1
    assert main(["sbom", "--output", str(env.root / "out")]) == 0
    assert json.loads((env.root / "out" / "W.spdx.json").read_text())["spdxVersion"] == "SPDX-2.3"
    assert json.loads((env.root / "out" / "W.cdx.json").read_text())["specVersion"] == "1.5"
    capsys.readouterr()
    assert main(["sbom", "--format", "cyclonedx", "--output", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["bomFormat"] == "CycloneDX"


def test_download_budget_stops_the_install(env, monkeypatch, capsys):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    (env.root / "main.cpp").write_text("int main(){}")
    (env.root / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n    ws.requires("mylib")\n'
                                          '    with Target("app") as t:\n        t.sources(["main.cpp"])\n')
    monkeypatch.chdir(env.root)
    assert main(["pkg", "install", "--max-download", "10"]) == 1
    assert "CH6003" in capsys.readouterr().err


def test_offline_mode_blocks_registry_downloads_but_not_local_files(env, monkeypatch):
    env.package("mylib", "1.0.0", LIB_SOURCES, build=SRC_BUILD)
    monkeypatch.setenv("CHARPENTE_OFFLINE", "1")
    ws = env.workspace(["mylib"])
    install_mod.install(ws, env.store, env.index(ws))                       # file:// archive: allowed
    assert lock.load(ws.root) is not None


# ================================================================ real network
@pytest.mark.skipif(os.environ.get("CHARPENTE_NETWORK_TESTS") != "1", reason="set CHARPENTE_NETWORK_TESTS=1")
def test_bundled_recipes_download_and_verify_for_real(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.cpp").write_text("int main(){}")
    (tmp_path / "w.charpente").write_text(
        'from charpente import *\nwith Workspace("W") as ws:\n    ws.requires("fmt@^10", "nlohmann_json")\n'
        '    with Target("app") as t:\n        t.sources(["main.cpp"])\n')
    assert main(["pkg", "install"]) == 0
    store = PackageStore()
    for archive in store.downloads.glob("*"):
        assert archive.name.split(".")[0] == file_sha256(archive)
    assert load is not None and builder is not None and FakeToolchain is not None


# ============================================================ vendor selection
def test_vendoring_copies_only_what_building_needs(env):
    files = {"include/lib/a.h": "a", "include/lib/detail/b.h": "b", "src/impl.cpp": "i", "src/other.cpp": "o",
             "tests/big_test.cpp": "t", "docs/manual.pdf": "d", "examples/x/y/z.cpp": "e", "LICENSE.txt": "MIT",
             "COPYING": "c", "README.md": "r"}
    env.package("mylib", "1.0.0", files, build='type = "sources"\nsources = ["src/impl.cpp"]\ninclude_dirs = ["include"]\n')
    ws = env.workspace(["mylib"])
    install_mod.install(ws, env.store, env.index(ws))
    vendor.vendor(ws, env.store)
    tree = env.root / "vendor" / "mylib-1.0.0"
    got = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert got == ["COPYING", "LICENSE.txt", "include/lib/a.h", "include/lib/detail/b.h", "src/impl.cpp"]


def test_keep_patterns_limit_a_whole_repository_include_dir(env):
    files = {"glm/glm.hpp": "g", "glm/detail/x.inl": "x", "test/t.cpp": "t", "doc/d.md": "d", "copying.txt": "MIT"}
    env.package("mini-glm", "1.0.0", files, build='type = "header_only"\ninclude_dirs = ["."]\nkeep = ["glm/**"]\n')
    ws = env.workspace(["mini-glm"])
    install_mod.install(ws, env.store, env.index(ws))
    vendor.vendor(ws, env.store)
    tree = env.root / "vendor" / "mini-glm-1.0.0"
    got = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file())
    assert got == ["copying.txt", "glm/detail/x.inl", "glm/glm.hpp"]


def test_a_dot_include_dir_without_keep_vendors_everything(env):
    env.package("all", "1.0.0", {"a.h": "a", "sub/b.h": "b"}, build='type = "header_only"\ninclude_dirs = ["."]\n')
    ws = env.workspace(["all"])
    install_mod.install(ws, env.store, env.index(ws))
    vendor.vendor(ws, env.store)
    tree = env.root / "vendor" / "all-1.0.0"
    assert sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()) == ["a.h", "sub/b.h"]
