"""Kits, the recipes behind them, kits shipped inside Charpente (local sources), per-workspace package settings, packaging."""
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from charpente import flags
from charpente.dsl import api
from charpente.dsl.model import OS, Kind, Target, Workspace
from charpente.errors import ChError
from charpente.pkg import fetch, kits, localsrc, materialize, recipe
from charpente.pkg.store import PackageStore

RECIPES = Path(__file__).resolve().parent.parent / "charpente" / "pkg" / "recipes"
ALL_RECIPES = {r.name: r for r in (recipe.load(p) for p in sorted(RECIPES.glob("*.toml")))}
ALL_KITS = kits.load_all()


# ------------------------------------------------------------------ recipes
@pytest.mark.parametrize("path", sorted(RECIPES.glob("*.toml")), ids=lambda p: p.stem)
def test_every_bundled_recipe_is_valid_pinned_and_licensed(path):
    r = recipe.load(path)
    assert path.stem == f"{r.name}-{r.version}" or path.stem.startswith(r.name.lower())
    assert len(r.source.sha256) == 64 and r.license and r.description
    assert r.source.url.startswith(("https://", localsrc.SCHEME))
    for dependency in r.dependencies:
        name = recipe.constraint_of(dependency)[0]
        assert name in ALL_RECIPES, f"{r.name} depends on {name}, which has no recipe"


def test_the_recipes_needed_by_the_kits_and_templates_exist():
    for name in ("simdjson", "stb", "miniaudio", "cgltf", "volk", "vma", "meshoptimizer", "asio", "websocketpp", "tracy",
                 "imgui", "imgui-glfw-opengl3", "glfw", "freertos", "printf", "cmsis", "tinylibc", "charpente-mobile",
                 "openxr-headers", "pybind11"):
        assert name in ALL_RECIPES, name


# ------------------------------------------------------------------ kits
@pytest.mark.parametrize("name", sorted(ALL_KITS))
def test_every_kit_names_recipes_that_exist_and_says_what_was_verified(name):
    kit = ALL_KITS[name]
    assert kit.description and kit.verified and (kit.unverified or kit.notes)
    for spec in kit.requires:
        package, constraint = recipe.constraint_of(spec)
        assert package in ALL_RECIPES, f"{name} requires {package}"
        assert constraint.matches(ALL_RECIPES[package].version), f"{spec} does not match the bundled {package}"
    assert set(kit.uses) <= set(ALL_RECIPES)


def test_the_kits_from_the_specification_exist():
    assert {"kit-core", "kit-app", "kit-graphics", "kit-xr", "kit-game", "kit-net", "kit-embedded", "kit-android", "kit-ohos",
            "kit-mobile"} <= set(ALL_KITS)


def test_kit_files_are_validated(tmp_path):
    good = 'kit = 1'
    for text, fragment in (('[kit]\nname = "notakit"\nrequires = ["a"]', "kit-"), ('[kit]\nname = "kit-x"\nrequires = []', "empty"),
                           ('[kit]\nname = "kit-x"\nrequires = ["a"]\ncolour = 1', "unknown"), ('[other]\nx = 1', "exactly one"),
                           ('[kit]\nname = "kit-x"\nrequires = [1]', "list of strings"), ("not toml [", "not valid TOML")):
        with pytest.raises(ChError) as exc:
            kits.parse(text)
        assert fragment in str(exc.value), (text, good)
    parsed = kits.parse('[kit]\nname = "kit-x"\nrequires = ["a@^1", "b"]')
    assert parsed.uses == ("a", "b")


def test_a_project_can_add_kits_but_not_shadow_bundled_ones(tmp_path):
    (tmp_path / "kit-mine.toml").write_text('[kit]\nname = "kit-mine"\nrequires = ["fmt@^10"]\nuses = ["fmt"]\n')
    assert "kit-mine" in kits.load_all(tmp_path)
    (tmp_path / "kit-core.toml").write_text('[kit]\nname = "kit-core"\nrequires = ["fmt@^10"]\n')
    with pytest.raises(ChError):
        kits.load_all(tmp_path)


def test_unknown_kit_lists_the_known_ones():
    with pytest.raises(ChError) as exc:
        kits.get("kit-nope")
    assert exc.value.code == "CH6016" and "kit-core" in str(exc.value)


def test_members_expand_in_order_without_duplicates():
    assert kits.members(ALL_KITS, ["engine", "kit-net", "asio"]) == ["engine", "asio", "websocketpp"]


# ------------------------------------------------------------------ the DSL: ws.kit, package_settings, output names
def _load(text, tmp_path):
    from charpente.dsl.loader import load_workspace

    path = tmp_path / "app.charpente"
    path.write_text(text)
    import os

    os.environ["CHARPENTE_TRUST_ALL"] = "1"
    return load_workspace(str(path))


def test_ws_kit_requires_the_packages_and_uses_expands_to_the_members(tmp_path):
    ws = _load('from charpente import *\nwith Workspace("w") as ws:\n    ws.kit("kit-net")\n'
               '    with Target("app") as t:\n        t.uses("kit-net")\n        t.uses_public("kit-net")\n', tmp_path)
    assert ws.requires == ["asio@^1.30", "websocketpp@^0.8"]
    assert ws.kits["kit-net"] == ["asio", "websocketpp"]
    assert ws.targets["app"].uses == ["asio", "websocketpp"] and ws.targets["app"].uses_public == ["asio", "websocketpp"]


def test_an_unknown_kit_in_a_workspace_file_is_reported(tmp_path):
    with pytest.raises(ChError) as exc:
        _load('from charpente import *\nwith Workspace("w") as ws:\n    ws.kit("kit-nope")\n', tmp_path)
    assert "CH6016" in str(exc.value) or "kit-nope" in str(exc.value)


def test_the_linter_knows_kit_names_and_their_members(tmp_path):
    from charpente.lint import lint_source

    good = 'from charpente import *\nwith Workspace("w") as ws:\n    ws.kit("kit-net")\n    with Target("a") as t:\n        t.sources(["a.cpp"])\n        t.uses("kit-net", "asio")\n'
    assert [i for i in lint_source(good) if i.code == "CH1109"] == []
    bad = good.replace('ws.kit("kit-net")', "pass")
    assert any(i.code == "CH1109" for i in lint_source(bad))


def test_package_settings_are_validated_and_recorded(tmp_path):
    ws = _load('from charpente import *\nwith Workspace("w") as ws:\n    ws.package_settings("freertos", include_dirs=["config"], '
               'defines=["X=1"], uses=["tinylibc"])\n    ws.package_settings("freertos", include_dirs=["config", "more"])\n', tmp_path)
    assert ws.package_settings["freertos"] == {"include_dirs": ["config", "more"], "defines": ["X=1"], "compile_flags": [],
                                               "uses": ["tinylibc"], "link_libraries": []}
    with pytest.raises(ChError):
        _load('from charpente import *\nwith Workspace("w") as ws:\n    ws.package_settings("bad name")\n', tmp_path)


def test_package_settings_change_only_the_package_target_of_this_workspace(tmp_path):
    target = Target(name="freertos", location=tmp_path, external=True)
    materialize.apply_settings(target, {"include_dirs": ["config"], "defines": ["A=1"], "compile_flags": ["-Os"],
                                        "uses": ["tinylibc"], "link_libraries": ["m"]}, tmp_path)
    assert target.include_dirs == [str(tmp_path / "config")] and target.define_macros == ["A=1"]
    assert target.extra_compile_flags == ["-Os"] and target.uses == ["tinylibc"] and target.link_libraries == ["m"]


def test_settings_for_a_package_that_is_not_required_are_an_error(tmp_path):
    ws = Workspace(name="w", location=tmp_path)
    ws.requires.append("fmt@^10")
    ws.package_settings["ghost"] = {"defines": ["X"]}
    lock = tmp_path / "charpente.lock"
    lock.write_text('lock_version = 1\n[[package]]\nname = "fmt"\nversion = "10.2.1"\nrecipe_sha256 = "a"\nsource_url = "u"\n'
                    'source_sha256 = "b"\ndependencies = []\nrequested_by = []\n')
    monkeypatched = materialize.load_locked_recipe
    materialize.load_locked_recipe = lambda pkg, root, store: (ALL_RECIPES["fmt"], tmp_path)          # type: ignore[assignment]
    try:
        with pytest.raises(ChError) as exc:
            materialize.materialize(ws, PackageStore())
    finally:
        materialize.load_locked_recipe = monkeypatched                                              # type: ignore[assignment]
    assert exc.value.code == "CH6017" and "ghost" in str(exc.value)


def test_python_extensions_can_name_their_output(tmp_path):
    ws = _load('from charpente import *\nwith Workspace("w") as ws:\n    with Target("fast") as t:\n        t.kind(Kind.PLUGIN)\n'
               '        t.output_prefix("")\n        t.output_extension(".pyd")\n', tmp_path)
    fake = flags.Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
    assert flags.output_filename(ws.targets["fast"], OS.WINDOWS, fake) == "fast.pyd"
    assert flags.output_filename(Target(name="x", kind=Kind.SHARED_LIBRARY), OS.LINUX, fake) == "libx.so"      # default unchanged
    assert flags.output_filename(Target(name="x", kind=Kind.SHARED_LIBRARY, output_prefix="", output_extension=".node"),
                                 OS.LINUX, fake) == "x.node"
    with pytest.raises(ChError):
        api.Target("t")                                                                                       # not inside a workspace


def test_platform_settings_accepts_a_setting_called_name(tmp_path):
    ws = _load('from charpente import *\nwith Workspace("w") as ws:\n    with Target("a") as t:\n'
               '        t.platform_settings("ios", name="My App", bundle_id="a.b")\n', tmp_path)
    assert ws.targets["a"].platform_settings["ios"] == {"name": "My App", "bundle_id": "a.b"}


# ------------------------------------------------------------------ kits shipped inside Charpente
def test_local_source_digests_are_in_step_with_the_shipped_files():
    spec = importlib.util.spec_from_file_location("sync_kit_digests", Path(__file__).resolve().parent.parent / "tools" / "sync_kit_digests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(check=True) == 0, "run: python tools/sync_kit_digests.py"


def test_tree_digest_ignores_line_endings_and_detects_any_change(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for folder, newline in ((a, "\n"), (b, "\r\n")):
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "x.h").write_bytes(f"int x;{newline}int y;{newline}".encode())
    assert localsrc.tree_digest(a) == localsrc.tree_digest(b)
    (b / "sub" / "x.h").write_bytes(b"int x;\nint z;\n")
    assert localsrc.tree_digest(a) != localsrc.tree_digest(b)
    (b / "sub" / "x.h").write_bytes(b"int x;\r\nint y;\r\n")
    (b / "sub" / "new.h").write_bytes(b"")
    assert localsrc.tree_digest(a) != localsrc.tree_digest(b)


def test_a_local_source_is_copied_only_if_its_digest_matches(tmp_path):
    good = ALL_RECIPES["tinylibc"]
    destination = tmp_path / "out"
    localsrc.materialize(good.source.url, good.source.sha256, destination)
    assert (destination / "include" / "string.h").is_file() and (destination / "src" / "string.c").is_file()
    with pytest.raises(ChError) as exc:
        localsrc.materialize(good.source.url, "0" * 64, tmp_path / "out2")
    assert exc.value.code == "CH6002" and not (tmp_path / "out2").exists()


def test_local_source_urls_cannot_escape_the_kit_folder():
    for bad in ("charpente://../../etc", "charpente://", "charpente:///abs", "charpente://nonexistent"):
        with pytest.raises(ChError):
            localsrc.resolve(bad)
    assert localsrc.is_local("charpente://x") and not localsrc.is_local("https://x")


def test_fetch_source_installs_a_local_kit_without_any_download(tmp_path):
    store = PackageStore(tmp_path / "store")
    tree = fetch.fetch_source(ALL_RECIPES["charpente-mobile"], store)
    assert (tree / "include" / "charpente" / "mobile.hpp").is_file()
    assert fetch.fetch_source(ALL_RECIPES["charpente-mobile"], store) == tree                               # idempotent


def test_tinylibc_really_compiles_freestanding_and_behaves(tmp_path):
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("needs gcc")
    kit = localsrc.resolve("charpente://tinylibc")
    (tmp_path / "t.c").write_text(
        '#include <stddef.h>\n#include <string.h>\n#include <stdlib.h>\nint main(void){ char b[16]; strcpy(b,"abc"); strcat(b,"def");\n'
        ' if (strlen(b)!=6 || strcmp(b,"abcdef")!=0 || memcmp("ab","ac",2)>=0) return 1; memmove(b+1,b,3); if (b[1]!=\'a\') return 2;\n'
        ' if (strtol("-0x1f",0,0)!=-31 || atoi("42")!=42 || abs(-3)!=3 || strrchr(b,\'f\')==0 || strchr(b,\'z\')!=0) return 3; return 0; }\n')
    # -fno-builtin: the compiler must call *our* functions instead of folding them away
    build = [gcc, "-fno-builtin", "-I" + str(kit / "include"), str(tmp_path / "t.c"), str(kit / "src" / "string.c"), str(kit / "src" / "stdlib.c"),
             "-o", str(tmp_path / "t.exe")]
    compiled = subprocess.run(build, capture_output=True, text=True)
    if compiled.returncode != 0 and "cannot find" in compiled.stderr:
        pytest.skip("this gcc cannot link the freestanding test")
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(tmp_path / "t.exe")]).returncode == 0


# ------------------------------------------------------------------ the kit command
def test_kit_command_lists_shows_and_edits_the_workspace_file(tmp_path, monkeypatch, capsys):
    from charpente.commands import kit as kit_cmd

    (tmp_path / "app.charpente").write_text('from charpente import *\n\nwith Workspace("demo") as ws:\n    with Target("a") as t:\n        t.sources(["a.cpp"])\n')
    monkeypatch.chdir(tmp_path)
    assert kit_cmd.execute(["list"]) == 0
    assert "kit-core" in capsys.readouterr().out
    assert kit_cmd.execute(["show", "kit-net"]) == 0
    shown = capsys.readouterr().out
    assert "asio" in shown and "Verified:" in shown and "Not verified:" in shown
    assert kit_cmd.execute(["add", "kit-net"]) == 0
    text = (tmp_path / "app.charpente").read_text()
    assert 'with Workspace("demo") as ws:\n    ws.kit("kit-net")\n' in text
    assert kit_cmd.execute(["add", "kit-net"]) == 0 and (tmp_path / "app.charpente").read_text() == text          # idempotent
    with pytest.raises(ChError):
        kit_cmd.execute(["show", "kit-nope"])
    no_workspace = 'print("no workspace here")\n'
    assert kit_cmd.add_to_file('from charpente import *\nwith Workspace("x") as w:\n    pass\n', "kit-net").count('w.kit("kit-net")') == 1
    with pytest.raises(ChError):
        kit_cmd.add_to_file(no_workspace, "kit-net")


# ------------------------------------------------------------------ packaging: data files must be in the wheel
def test_pyproject_declares_every_data_directory_of_the_package():
    """setuptools leaves out non-Python files unless they are listed: recipes, kits, kit sources and templates once
    went missing from the wheel. This checks the declaration against the files on disk (no build needed)."""
    try:
        import tomllib
    except ImportError:                                            # Python 3.9/3.10
        import tomli as tomllib
    root = Path(__file__).resolve().parent.parent
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["charpente"]
    covered = set()
    for pattern in patterns:
        covered.update(p.relative_to(root / "charpente").as_posix() for p in (root / "charpente").glob(pattern) if p.is_file())
    for required in ("pkg/recipes/fmt-10.2.1.toml", "pkg/kits/kit-core.toml", "kit_sources/tinylibc/src/string.c",
                     "kit_sources/mobile/include/charpente/mobile.hpp", "templates_data/console/template.toml",
                     "templates_data/console/files/@NAME@.charpente",
                     "templates_data/app-harmonyos/files/harmony/AppScope/resources/base/media/app_icon.png"):
        assert required in covered, f"{required} would be missing from the wheel: add it to [tool.setuptools.package-data]"
    on_disk = {p.relative_to(root / "charpente").as_posix() for folder in ("pkg/recipes", "pkg/kits", "kit_sources", "templates_data")
               for p in (root / "charpente" / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert on_disk <= covered, sorted(on_disk - covered)[:5]
    hidden = [p for p in on_disk if any(part.startswith(".") for part in p.split("/"))]
    assert not hidden, f"packaging tools skip dot-files; store them as dot_NAME: {hidden[:3]}"


@pytest.mark.skipif(importlib.util.find_spec("setuptools") is None, reason="needs setuptools (a real wheel build)")
def test_the_wheel_contains_recipes_kits_kit_sources_and_templates(tmp_path):
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "-m", "pip", "wheel", str(root), "--no-deps", "--no-build-isolation", "-w", str(tmp_path), "-q"],
                            capture_output=True, text=True, cwd=str(tmp_path))
    if result.returncode != 0:
        pytest.skip("could not build a wheel here: " + result.stderr[-200:])
    wheel = next(tmp_path.glob("charpente-*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    assert any(n.endswith("pkg/recipes/fmt-10.2.1.toml") for n in names), "recipes missing from the wheel"
    assert any(n.endswith("pkg/kits/kit-core.toml") for n in names), "kits missing from the wheel"
    assert any(n.endswith("kit_sources/tinylibc/src/string.c") for n in names), "kit sources missing from the wheel"
    assert any(n.endswith("kit_sources/mobile/include/charpente/mobile.hpp") for n in names)
    assert any(n.endswith("templates_data/console/template.toml") for n in names), "templates missing from the wheel"
    assert any(n.endswith("templates_data/console/files/@NAME@.charpente") for n in names)
    assert any(n.endswith("templates_data/app-harmonyos/files/harmony/AppScope/resources/base/media/app_icon.png") for n in names)
