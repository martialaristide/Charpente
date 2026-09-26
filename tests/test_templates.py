"""Project templates: every bundled template generates cleanly, its workspace file lints, and the ones that need no network
or special toolchain really build. The heavier verifications (emulators, GPUs, cross toolchains) are in docs/plans/phase-6.md."""
import shutil
import sys
from pathlib import Path

import pytest

from charpente import platforms, templates, toolchains
from charpente.commands import init as init_cmd
from charpente.errors import ChError
from charpente.lint import lint_source
from charpente.pkg import kits

ALL = templates.load_all()
NAMES = sorted(ALL)
HAVE_GXX = shutil.which("g++") is not None or shutil.which("clang++") is not None or shutil.which("cl") is not None
_REAL_ZIG = shutil.which("zig") or (str(toolchains.installed_zigs()[0]) if toolchains.installed_zigs() else "")
HAVE_ZIG = bool(_REAL_ZIG)                 # evaluated against the real home, before the per-test isolation applies


def test_the_expected_templates_are_bundled():
    expected = {"console", "bibliotheque", "app-gui", "jeu-2d", "jeu-3d-vulkan", "vr-openxr", "app-android", "app-harmonyos",
                "app-mobile", "web-wasm", "wasi-plugin", "plugin-python", "firmware-stm32", "firmware-esp32",
                "linux-embarque-rpi", "module-charpente"}
    assert expected <= set(NAMES)


def test_values_for_project_names():
    assert templates.values_for("my-game") == {"NAME": "my-game", "IDENT": "my_game", "TITLE": "My Game",
                                               "PACKAGE": "dev.example.my_game"}
    assert templates.values_for("3d.demo")["IDENT"] == "p_3d_demo"
    assert templates.render("@IDENT@/@NAME@ @UNKNOWN@", {"IDENT": "a", "NAME": "b", "TITLE": "", "PACKAGE": ""}) == "a/b @UNKNOWN@"


@pytest.mark.parametrize("name", NAMES)
def test_every_template_says_what_was_and_was_not_verified(name):
    info = ALL[name].info
    assert info.description and info.verified is not None
    if not info.verified:
        assert info.unverified, f"{name} verifies nothing and must say so"
    assert info.platforms and all(p == "host" or p in {x.name for x in platforms.all_platforms()} for p in info.platforms)
    for kit in info.kits:
        kits.get(kit)                                                     # every kit a template names exists


@pytest.mark.parametrize("name", NAMES)
def test_a_template_generates_every_file_with_no_token_left(name, tmp_path):
    target = tmp_path / "proj"
    written = ALL[name].generate(target, "my-app")
    assert written and all(p.exists() for p in written)
    for path in written:
        assert not any(token in path.name for token in ("@NAME@", "@IDENT@", "@TITLE@", "@PACKAGE@"))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue                                                       # binary (an icon)
        for token in ("@NAME@", "@IDENT@", "@TITLE@", "@PACKAGE@"):
            assert token not in text, f"{name}: {token} left in {path.name}"


@pytest.mark.parametrize("name", [n for n in NAMES if n not in ("module-charpente", "firmware-esp32")])
def test_the_generated_workspace_file_lints_without_errors_and_uses_real_platforms(name, tmp_path):
    ALL[name].generate(tmp_path, "my-app")
    workspace_file = next(p for p in tmp_path.glob("*.charpente") if p.is_file())
    issues = lint_source(workspace_file.read_text(encoding="utf-8"))
    assert [i for i in issues if i.severity == "error"] == [], issues
    text = workspace_file.read_text(encoding="utf-8")
    import re

    for match in re.findall(r'platforms\(\[([^\]]*)\]\)', text):
        for platform in re.findall(r'"([^"]+)"', match):
            if "*" not in platform:
                platforms.get(platform)                                    # a template never names a platform that does not exist
    assert "kit-" not in text or all(k in kits.load_all() for k in re.findall(r'"(kit-[a-z]+)"', text))


def test_a_template_never_overwrites_existing_files(tmp_path):
    ALL["console"].generate(tmp_path, "demo")
    with pytest.raises(ChError) as exc:
        ALL["console"].generate(tmp_path, "demo")
    assert exc.value.code == "CH4008" and "demo.charpente" in str(exc.value)


def test_template_metadata_is_validated(tmp_path):
    for text in ("[template]\nname = 'Bad Name'\n", "[other]\n", "[template]\nname = 'x'\ncolour = 1\n", "not toml ["):
        with pytest.raises(ChError):
            templates.parse_info(text, "t.toml")


def test_a_project_can_add_templates_but_not_replace_bundled_ones(tmp_path):
    mine = tmp_path / "templates" / "mine"
    (mine / "files").mkdir(parents=True)
    (mine / "template.toml").write_text('[template]\nname = "mine"\ndescription = "x"\n')
    (mine / "files" / "@IDENT@.txt").write_text("hello @TITLE@")
    found = templates.load_all(tmp_path / "templates")
    assert "mine" in found
    written = found["mine"].generate(tmp_path / "out", "my-tool")
    assert written[0].name == "my_tool.txt" and written[0].read_text() == "hello My Tool"
    clash = tmp_path / "clash" / "console"
    (clash / "files").mkdir(parents=True)
    (clash / "template.toml").write_text('[template]\nname = "console"\ndescription = "x"\n')
    with pytest.raises(ChError):
        templates.load_all(tmp_path / "clash")


# ------------------------------------------------------------------ the init command
def test_init_list_names_every_template_and_flags_unverified_ones(capsys):
    assert init_cmd.execute(["--list"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in NAMES)
    esp = next(line for line in out.splitlines() if line.strip().startswith("firmware-esp32"))
    assert "[not verified]" in esp
    console = next(line for line in out.splitlines() if line.strip().startswith("console"))
    assert "[not verified]" not in console


def test_init_with_a_template_creates_a_folder_and_suggests_next_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert init_cmd.execute(["hello-cli", "--template", "console"]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "hello-cli" / "hello-cli.charpente").is_file() and "cd hello-cli" in out
    assert init_cmd.execute(["other", "--template", "bibliotheque", "--dir", str(tmp_path / "elsewhere")]) == 0
    assert (tmp_path / "elsewhere" / "other.charpente").is_file()


def test_init_with_an_unknown_template_lists_the_known_ones(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ChError) as exc:
        init_cmd.execute(["x", "--template", "nope"])
    assert exc.value.code == "CH4009" and "console" in str(exc.value)


def test_init_without_a_template_is_the_v010_behaviour(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert init_cmd.execute(["classic"]) == 0
    assert (tmp_path / "classic.charpente").is_file() and (tmp_path / "src" / "main.cpp").is_file()
    assert not (tmp_path / "classic" / "classic.charpente").exists()


def test_templates_that_need_packages_say_so(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert init_cmd.execute(["gui", "--template", "app-gui"]) == 0
    assert "charpente pkg install" in capsys.readouterr().out
    assert (tmp_path / "gui" / "gui.charpente").is_file()


def test_bundled_templates_are_registered_through_the_module_extension_point():
    from charpente.modules.runtime import get_registry

    names = {e.name for e in get_registry().all("template")}
    assert set(NAMES) <= names


# ------------------------------------------------------------------ real builds (no network, no special toolchain)
needs_compiler = pytest.mark.skipif(not HAVE_GXX, reason="needs a C++ compiler")


def _run(args, cwd, monkeypatch):
    import os

    from charpente.cli import main

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    if _REAL_ZIG:
        monkeypatch.setenv("PATH", str(Path(_REAL_ZIG).parent) + os.pathsep + os.environ.get("PATH", ""))
    return main(args)


@needs_compiler
def test_the_console_template_builds_tests_and_runs(tmp_path, monkeypatch, capfd):
    ALL["console"].generate(tmp_path, "demo-cli")
    assert _run(["test"], tmp_path, monkeypatch) == 0
    assert "1/1 test target(s) passed" in capfd.readouterr().out
    assert _run(["run", "--target", "demo-cli", "--", "Ada"], tmp_path, monkeypatch) == 0
    assert "Hello, Ada!" in capfd.readouterr().out


@needs_compiler
def test_the_library_template_builds_tests_and_runs_its_example(tmp_path, monkeypatch, capfd):
    ALL["bibliotheque"].generate(tmp_path, "stats")
    assert _run(["test"], tmp_path, monkeypatch) == 0
    capfd.readouterr()
    assert _run(["run", "--target", "stats_example"], tmp_path, monkeypatch) == 0
    assert "mean=2.50 argmax=1" in capfd.readouterr().out


@pytest.mark.skipif(not HAVE_ZIG, reason="needs zig (charpente toolchain install zig)")
def test_the_stm32_and_raspberry_pi_templates_cross_build_with_zig(tmp_path, monkeypatch, capfd):
    ALL["firmware-stm32"].generate(tmp_path / "fw", "blinker")
    assert _run(["build", "--platform", "cortexm4-arm"], tmp_path / "fw", monkeypatch) == 0
    built = tmp_path / "fw" / "build" / "Debug-cortexm4-arm" / "blinker"
    assert (built / "blinker.elf").is_file() and (built / "blinker.bin").is_file() and (built / "blinker.hex").is_file()
    assert int.from_bytes((built / "blinker.elf").read_bytes()[18:20], "little") == 40           # EM_ARM
    ALL["linux-embarque-rpi"].generate(tmp_path / "rpi", "sensor")
    assert _run(["build", "--platform", "linux-arm64"], tmp_path / "rpi", monkeypatch) == 0
    binary = tmp_path / "rpi" / "build" / "Debug-linux-arm64" / "sensor" / "sensor"
    assert binary.read_bytes()[:4] == b"\x7fELF" and int.from_bytes(binary.read_bytes()[18:20], "little") == 183   # EM_AARCH64


@pytest.mark.skipif(not HAVE_ZIG or shutil.which("node") is None, reason="needs zig and Node")
def test_the_wasi_template_builds_and_runs_under_node(tmp_path, monkeypatch, capfd):
    ALL["wasi-plugin"].generate(tmp_path, "counter")
    assert _run(["run", "--platform", "wasm32-wasi"], tmp_path, monkeypatch) == 0
    assert "words" in capfd.readouterr().out


def test_the_module_template_passes_the_module_conformance_check(tmp_path):
    from charpente.modules import conformance

    ALL["module-charpente"].generate(tmp_path, "my-plugin")
    issues = conformance.check_module(tmp_path)
    assert not conformance.has_errors(issues), issues


def test_the_python_plugin_template_names_its_output_like_a_python_extension(tmp_path):
    ALL["plugin-python"].generate(tmp_path, "fastmath")
    text = (tmp_path / "fastmath.charpente").read_text()
    assert 'output_prefix("")' in text and 'output_extension(".pyd" if IS_WINDOWS else ".so")' in text
    assert sys.platform  # the file itself imports sysconfig: it is loaded by the trusted .charpente machinery
