import textwrap

import pytest
from helpers import GCC, FakeToolchain

from charpente import builder
from charpente.cli import main
from charpente.core.planner import plan_workspace
from charpente.dsl.loader import load_workspace
from charpente.dsl.model import OS, Kind
from charpente.dsl.resolve import BuildContext, host_platform
from charpente.errors import ChError
from charpente.platform import host_os
from charpente.toolchains import NoToolchainFoundError, pick_default


def _has_compiler() -> bool:
    try:
        pick_default(host_os())
        return True
    except NoToolchainFoundError:
        return False


requires_compiler = pytest.mark.skipif(not _has_compiler(), reason="no C/C++ compiler on PATH")


@pytest.fixture(autouse=True)
def trust(monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")


def workspace(tmp_path, dsl, files=None, options=None, name="w.charpente"):
    for rel, text in (files or {"a.cpp": "x", "b.cpp": "y", "c.cpp": "z", "main.cpp": "int main(){}"}).items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    (tmp_path / name).write_text(textwrap.dedent(dsl))
    return load_workspace(str(tmp_path / name), options=options)


def plan(ws, config="Debug", **kw):
    return plan_workspace(ws, GCC, OS.LINUX, config=config, **kw)


def argv_of(p, action_id):
    return list(p.graph.actions[action_id].argv)


# ============================================================== uses
def test_uses_links_orders_and_shares_public_settings(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("engine") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.public_include_dirs(["engine/include"])
                t.include_dirs(["engine/private"])
                t.public_defines(["ENGINE=1"])
                t.defines(["ENGINE_INTERNAL"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("engine")
    """)
    p = plan(ws)
    app_compile = argv_of(p, "compile:app:main.cpp")
    assert "-Iengine/include" in app_compile and "-DENGINE=1" in app_compile
    assert "-Iengine/private" not in app_compile and "-DENGINE_INTERNAL" not in app_compile
    engine_compile = argv_of(p, "compile:engine:a.cpp")
    assert "-Iengine/private" in engine_compile and "-Iengine/include" in engine_compile
    link = argv_of(p, "link:app")
    assert "-lengine" in link and any(a.startswith("-L") and a.endswith("engine") for a in link)
    assert "archive:engine" in p.graph.deps["link:app"]
    assert p.outputs["engine"] in p.graph.actions["link:app"].inputs
    assert p.order.index("engine") < p.order.index("app")


def test_interface_settings_go_to_users_only(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("lib") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.interface_include_dirs(["only_for_users"])
                t.interface_defines(["USERS_ONLY"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("lib")
    """)
    p = plan(ws)
    assert "-Ionly_for_users" not in argv_of(p, "compile:lib:a.cpp")
    assert "-Ionly_for_users" in argv_of(p, "compile:app:main.cpp")
    assert "-DUSERS_ONLY" in argv_of(p, "compile:app:main.cpp")


def test_transitive_linking_but_not_transitive_includes(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("base") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.public_include_dirs(["base/include"])
                t.links(["m"])
            with Target("mid") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["b.cpp"])
                t.public_include_dirs(["mid/include"])
                t.uses("base")
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("mid")
    """)
    p = plan(ws)
    compile_app = argv_of(p, "compile:app:main.cpp")
    assert "-Imid/include" in compile_app and "-Ibase/include" not in compile_app   # private use: not re-exported
    link = argv_of(p, "link:app")
    assert link.index("-lmid") < link.index("-lbase")            # dependents first
    assert "-lm" in link                                          # a static library's system libs travel along
    assert link.index("-lbase") < link.index("-lm")
    assert {"archive:base", "archive:mid"} <= p.graph.deps["link:app"] | p.graph.closure(["link:app"])


def test_uses_public_re_exports_to_dependents(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("base") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.public_include_dirs(["base/include"])
                t.public_defines(["BASE"])
            with Target("mid") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["b.cpp"])
                t.uses_public("base")
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("mid")
    """)
    p = plan(ws)
    compile_app = argv_of(p, "compile:app:main.cpp")
    assert "-Ibase/include" in compile_app and "-DBASE" in compile_app


def test_header_only_targets_share_settings_but_build_nothing(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("headers") as t:
                t.kind(Kind.HEADER_ONLY)
                t.public_include_dirs(["third_party/include"])
                t.public_defines(["HEADERS_OK"])
                t.public_links(["dl"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("headers")
    """)
    p = plan(ws)
    assert "headers" not in p.target_actions and "headers" not in p.errors
    assert "-Ithird_party/include" in argv_of(p, "compile:app:main.cpp")
    link = argv_of(p, "link:app")
    assert "-ldl" in link and "-lheaders" not in link
    assert not [a for a in p.graph.actions if a.endswith(":headers")]


def test_uses_cycles_and_unknown_targets_are_reported(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.uses("b")
            with Target("b") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["b.cpp"])
                t.uses("a")
    """)
    with pytest.raises(ChError) as exc:
        plan(ws)
    assert exc.value.code == "CH3004" and "a" in str(exc.value)
    ws2 = workspace(tmp_path / "x", """
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["a.cpp"])
                t.uses("ghost")
    """)
    with pytest.raises(ChError) as exc:
        plan(ws2)
    assert exc.value.code == "CH3005" and "ghost" in str(exc.value)


def test_a_used_target_restricted_to_other_platforms_is_an_error(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("android_only") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.platforms(["android-*"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("android_only")
    """)
    with pytest.raises(ChError) as exc:
        plan(ws)
    assert exc.value.code == "CH3014"


def test_platform_restricted_targets_are_skipped_not_failed(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("phone") as t:
                t.sources(["a.cpp"])
                t.platforms(["harmonyos-*"])
            with Target("app") as t:
                t.sources(["main.cpp"])
    """)
    p = plan(ws)
    assert list(p.target_actions) == ["app"] and p.errors == {}


def test_dependency_closure_follows_uses(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("base") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
            with Target("mid") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["b.cpp"])
                t.uses("base")
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("mid")
            with Target("other") as t:
                t.sources(["c.cpp"])
    """)
    assert builder.dependency_closure(ws, "app") == {"app", "mid", "base"}


def test_unbuildable_kinds_are_refused_with_a_clear_error_and_block_users(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("phone_app") as t:
                t.kind(Kind.MOBILE_APP)
                t.sources(["a.cpp"])
            with Target("tool") as t:
                t.sources(["main.cpp"])
                t.depends_on(["phone_app"])
    """)
    p = plan(ws)
    assert p.errors["phone_app"].code == "CH3007" and "mobile_app" in str(p.errors["phone_app"])
    assert p.errors["tool"].code == "CH3006"


def test_plugin_kind_builds_like_a_shared_library(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("plug") as t:
                t.kind(Kind.PLUGIN)
                t.sources(["a.cpp"])
    """)
    p = plan(ws)
    link = argv_of(p, "link:plug")
    assert "-shared" in link and p.outputs["plug"].name == "libplug.so" or p.outputs["plug"].suffix in (".so", ".dll", ".dylib")


# ================================================================ overlays
def test_config_overlays(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("app") as t:
                t.sources(["main.cpp"])
                with t.on_config("Release") as c:
                    c.defines(["NDEBUG_ONLY"])
                    c.compile_flags(["-fno-rtti"])
                with t.on_config("Debug") as c:
                    c.defines("DEBUG_ONLY")
    """)
    debug = argv_of(plan(ws, "Debug"), "compile:app:main.cpp")
    release = argv_of(plan(ws, "Release"), "compile:app:main.cpp")
    assert "-DDEBUG_ONLY" in debug and "-DNDEBUG_ONLY" not in debug and "-fno-rtti" not in debug
    assert "-DNDEBUG_ONLY" in release and "-fno-rtti" in release and "-DDEBUG_ONLY" not in release


def test_platform_and_toolchain_overlays(tmp_path):
    host = host_platform()
    ws = workspace(tmp_path, f"""
        from charpente import *
        with Workspace("W") as ws:
            with Target("app") as t:
                t.sources(["main.cpp"])
                with t.on_platform("{host}") as p:
                    p.defines(["HOST_PLATFORM"])
                with t.on_platform("android-*") as p:
                    p.defines(["ANDROID_ONLY"])
                    p.android(package="cm.nka.app", min_sdk=29)
                with t.on_toolchain("gcc") as tc:
                    tc.include_dirs(["gcc_inc"])
                with t.on_toolchain("msvc") as tc:
                    tc.include_dirs(["msvc_inc"])
                with t.when(config="Release", platform="{host}") as c:
                    c.defines(["BOTH"])
    """)
    args = argv_of(plan(ws, "Debug"), "compile:app:main.cpp")
    assert "-DHOST_PLATFORM" in args and "-DANDROID_ONLY" not in args
    assert "-Igcc_inc" in args and "-Imsvc_inc" not in args and "-DBOTH" not in args
    assert "-DBOTH" in argv_of(plan(ws, "Release"), "compile:app:main.cpp")
    assert ws.targets["app"].overlays[1].platform_settings["android"]["min_sdk"] == 29


def test_overlay_uses_and_sources(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("extra") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["c.cpp"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                with t.on_config("Release") as c:
                    c.sources(["a.cpp"])
                    c.uses("extra")
    """)
    debug, release = plan(ws, "Debug"), plan(ws, "Release")
    assert "compile:app:a.cpp" not in debug.graph.actions and "-lextra" not in argv_of(debug, "link:app")
    assert "compile:app:a.cpp" in release.graph.actions and "-lextra" in argv_of(release, "link:app")


def test_a_condition_block_rejects_unknown_settings(tmp_path):
    with pytest.raises(ChError) as exc:
        workspace(tmp_path, """
            from charpente import *
            with Workspace("W") as ws:
                with Target("app") as t:
                    with t.on_config("Release") as c:
                        c.nonsense(["x"])
        """)
    assert "nonsense" in str(exc.value)


def test_overlays_and_uses_are_part_of_the_target_definition(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("app") as t:
                t.sources(["main.cpp"])
                with t.on_config("Release") as c:
                    c.defines(["X"])
    """)
    a = repr(ws.targets["app"])
    ws.targets["app"].overlays[0].define_macros.append("Y")
    assert repr(ws.targets["app"]) != a


# ================================================================ options
OPTIONS_DSL = """
    from charpente import *
    with Workspace("W") as ws:
        fx = ws.option("hand_tracking", default=True, help="Track hands")
        level = ws.option("level", default=2)
        mode = ws.option("mode", choices=["fast", "safe"], default="safe")
        name = ws.option("label", default="none")
        with Target("app") as t:
            t.sources(["main.cpp"])
            if fx:
                t.defines(["WITH_HAND_TRACKING=1"])
            t.defines([f"LEVEL={level}", f"MODE_{mode}", f"LABEL_{name}"])
"""


def test_options_defaults_and_overrides(tmp_path):
    ws = workspace(tmp_path, OPTIONS_DSL)
    assert ws.option_values == {"hand_tracking": True, "level": 2, "mode": "safe", "label": "none"}
    assert "WITH_HAND_TRACKING=1" in ws.targets["app"].define_macros
    assert ws.options["mode"].choices == ("fast", "safe") and ws.options["hand_tracking"].help == "Track hands"
    assert ws.options["level"].kind == "int" and ws.options["hand_tracking"].kind == "bool"

    ws2 = workspace(tmp_path / "b", OPTIONS_DSL, options={"hand_tracking": "false", "level": "5", "mode": "fast",
                                                          "label": "x y"})
    assert ws2.option_values == {"hand_tracking": False, "level": 5, "mode": "fast", "label": "x y"}
    assert "WITH_HAND_TRACKING=1" not in ws2.targets["app"].define_macros
    assert "LEVEL=5" in ws2.targets["app"].define_macros


@pytest.mark.parametrize("options,fragment", [
    ({"hand_tracking": "maybe"}, "true or false"), ({"level": "many"}, "an integer"), ({"mode": "turbo"}, "fast, safe"),
])
def test_invalid_option_values(tmp_path, options, fragment):
    with pytest.raises(ChError) as exc:
        workspace(tmp_path, OPTIONS_DSL, options=options)
    assert "CH1021" in str(exc.value) and fragment in str(exc.value)


def test_unknown_option_is_reported_with_the_declared_ones(tmp_path):
    with pytest.raises(ChError) as exc:
        workspace(tmp_path, OPTIONS_DSL, options={"hand_trackin": "1"})
    assert exc.value.code == "CH1022" and "hand_tracking" in str(exc.value)


def test_option_values_change_the_effective_build(tmp_path, capsys):
    (tmp_path / "main.cpp").write_text("int main(){}")
    (tmp_path / "w.charpente").write_text(textwrap.dedent(OPTIONS_DSL))
    from charpente.commands._common import load
    a = load(str(tmp_path / "w.charpente"), ["level=7"])
    assert a.option_values["level"] == 7
    with pytest.raises(ChError) as exc:
        load(str(tmp_path / "w.charpente"), ["level"])
    assert exc.value.code == "CH4005"


# =========================================================== requires, strings
def test_requires_validation_and_deduplication(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            ws.requires("fmt@^10", "glm", ["spdlog@>=1.9,<2"])
            ws.requires("fmt@^10")
    """)
    assert ws.requires == ["fmt@^10", "glm", "spdlog@>=1.9,<2"]
    with pytest.raises(ChError) as exc:
        workspace(tmp_path / "b", 'from charpente import *\nwith Workspace("W") as ws:\n    ws.requires("bad name")\n')
    assert "CH1023" in str(exc.value)
    with pytest.raises(ChError) as exc:
        workspace(tmp_path / "c", 'from charpente import *\nwith Workspace("W") as ws:\n    ws.requires("fmt@^x")\n')
    assert "CH7002" in str(exc.value)


def test_a_single_string_is_one_item_not_a_list_of_characters(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            ws.platforms("windows-x64")
            with Target("app") as t:
                t.sources("*.cpp")
                t.defines("A")
                t.links("m")
    """)
    t = ws.targets["app"]
    assert t.source_patterns == ["*.cpp"] and t.define_macros == ["A"] and t.link_libraries == ["m"]
    assert ws.platforms == ["windows-x64"]


def test_workspace_version(tmp_path):
    ws = workspace(tmp_path, 'from charpente import *\nwith Workspace("W", version="0.3.0") as ws:\n    pass\n')
    assert ws.version == "0.3.0"


# ================================================================== rules
RULE_DSL = """
    from charpente import *
    with Workspace("W") as ws:
        with Rule("gen") as r:
            r.command(["tool", "make", "gen/version.h", "gen/generated.cpp"])
            r.inputs(["VERSION"])
            r.outputs(["gen/version.h", "gen/generated.cpp"])
            r.description("Generating version files")
        with Target("app") as t:
            t.sources(["main.cpp"])
            t.rules(["gen"])
"""


def test_rule_outputs_feed_compilations_and_generated_sources_are_compiled(tmp_path):
    ws = workspace(tmp_path, RULE_DSL, files={"main.cpp": "int main(){}", "VERSION": "1"})
    p = plan(ws)
    rule = p.graph.actions["rule:gen"]
    assert rule.argv[0] == "tool" and rule.cwd == tmp_path and rule.description == "Generating version files"
    assert set(rule.outputs) == {tmp_path / "gen" / "version.h", tmp_path / "gen" / "generated.cpp"}
    main_compile = p.graph.actions["compile:app:main.cpp"]
    assert tmp_path / "gen" / "version.h" in main_compile.inputs
    assert "rule:gen" in p.graph.deps["compile:app:main.cpp"]
    assert "compile:app:gen/generated.cpp" in p.graph.actions          # a generated source is compiled
    assert "rule:gen" in p.target_actions["app"]


def test_rule_runs_before_its_consumers_and_is_cached(tmp_path):
    ws = workspace(tmp_path, RULE_DSL, files={"main.cpp": "int main(){}", "VERSION": "1"})
    calls = []
    real = FakeToolchain()

    def runner(argv, **kw):
        if argv[0] == "tool":
            calls.append(list(argv))
            for out in argv[2:]:
                (tmp_path / out).parent.mkdir(exist_ok=True)
                (tmp_path / out).write_text("generated")
            import subprocess
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real(argv, **kw)

    result = builder.build_workspace(ws, GCC, OS.LINUX, run=runner)
    assert result.ok and len(calls) == 1
    order = [i for i in real.compiles]
    assert "generated" in order and "main" in order
    (tmp_path / "main.cpp").write_text("int main(){return 1;}")
    builder.build_workspace(ws, GCC, OS.LINUX, run=runner)
    assert len(calls) == 1                                    # inputs of the rule unchanged: not rerun
    (tmp_path / "VERSION").write_text("2")
    builder.build_workspace(ws, GCC, OS.LINUX, run=runner)
    assert len(calls) == 2                                    # its input changed: rerun


def test_unknown_and_incomplete_rules(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.rules(["ghost"])
    """)
    with pytest.raises(ChError) as exc:
        plan(ws)
    assert exc.value.code == "CH3015"
    with pytest.raises(ChError) as exc:
        workspace(tmp_path / "b", 'from charpente import *\nwith Workspace("W") as ws:\n'
                                  '    with Rule("r") as r:\n        r.command(["x"])\n')
    assert "CH1024" in str(exc.value)
    with pytest.raises(ChError) as exc:
        workspace(tmp_path / "c", 'from charpente import *\nwith Workspace("W") as ws:\n'
                                  '    with Rule("r") as r:\n        r.command("gcc -c a.c")\n')
    assert "CH9001" in str(exc.value)


# ============================================================ v0.1.0 unchanged
def test_a_v010_style_workspace_behaves_exactly_as_before(tmp_path):
    ws = workspace(tmp_path, """
        from charpente import *
        with Workspace("W") as ws:
            ws.configurations(["Debug", "Release"])
            with Target("core") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
                t.include_dirs(["core/include"])
            with Target("app") as t:
                t.depends_on(["core"])
                t.links(["core"])
                t.include_dirs(["core/include"])
                t.sources(["main.cpp"])
    """)
    p = plan(ws)
    assert "-Icore/include" in argv_of(p, "compile:app:main.cpp")
    link = argv_of(p, "link:app")
    assert link.count("-lcore") == 1 and "archive:core" in p.graph.deps["link:app"]
    assert ws.targets["app"].overlays == [] and ws.targets["app"].uses == []


# =============================================================== declarative TOML
TOML = """
[workspace]
name = "Demo"
version = "1.0.0"
configurations = ["Debug", "Release"]
requires = ["fmt@^10"]

[options.fast]
default = false
help = "Fast math"

[[rule]]
name = "gen"
command = ["tool", "out.h"]
inputs = ["VERSION"]
outputs = ["out.h"]

[[target]]
name = "engine"
kind = "static_library"
standard = "c++20"
sources = ["a.cpp"]
public_include_dirs = ["engine/include"]

[[target]]
name = "app"
uses = ["engine"]
sources = "main.cpp"
rules = ["gen"]

  [[target.when]]
  config = "Release"
  defines = ["RELEASE_ONLY"]

  [[target.when]]
  option = "fast=true"
  compile_flags = ["-ffast-math"]
"""


def toml_workspace(tmp_path, text=TOML, options=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "charpente.toml").write_text(text)
    for f in ("a.cpp", "main.cpp", "VERSION"):
        (tmp_path / f).write_text("x")
    return load_workspace(str(tmp_path / "charpente.toml"), options=options)


def test_toml_workspace_loads_without_any_trust(tmp_path, monkeypatch):
    monkeypatch.delenv("CHARPENTE_TRUST_ALL")
    ws = toml_workspace(tmp_path)               # no approval asked, none needed: it is data
    assert ws.name == "Demo" and ws.version == "1.0.0" and ws.requires == ["fmt@^10"]
    assert ws.targets["engine"].kind == Kind.STATIC_LIBRARY and ws.targets["engine"].standard == "c++20"
    assert ws.targets["app"].uses == ["engine"] and ws.targets["app"].source_patterns == ["main.cpp"]
    assert ws.rules["gen"].outputs == ["out.h"] and ws.options["fast"].kind == "bool"


def test_toml_overlays_and_options_drive_the_effective_build(tmp_path):
    ws = toml_workspace(tmp_path)
    p = plan(ws, "Debug")
    assert "-DRELEASE_ONLY" not in argv_of(p, "compile:app:main.cpp") and "-ffast-math" not in argv_of(p, "compile:app:main.cpp")
    assert "-DRELEASE_ONLY" in argv_of(plan(ws, "Release"), "compile:app:main.cpp")
    ws2 = toml_workspace(tmp_path / "opt", options={"fast": "true"})
    assert "-ffast-math" in argv_of(plan(ws2), "compile:app:main.cpp")
    assert "-Iengine/include" in argv_of(plan(ws2), "compile:app:main.cpp")


@pytest.mark.parametrize("text,fragment", [
    ("[workspace]\nname = 'x'\ntypo = 1\n", "unknown key"),
    ("[workspace]\nname = 'x'\n[[target]]\nname = 'a'\nsourcess = ['a.cpp']\n", "sourcess"),
    ("[workspace]\nname = 'x'\n[[target]]\nname = 'a'\nkind = 'spaceship'\n", "kind"),
    ("[[target]]\nname = 'a'\n", "[workspace]"),
    ("[workspace]\nname = 'x'\n[[target]]\nname = 'a'\nsources = 3\n", "string"),
    ("[workspace]\nname = 'x'\n[[rule]]\nname = 'r'\ncommand = 'gcc x'\noutputs = ['o']\n", "list"),
    ("[workspace]\nname = 'x'\n[[target]]\nname = 'a'\n[[target.when]]\nplatfrom = 'x'\n", "platfrom"),
    ("not toml [", "TOML"),
])
def test_toml_errors_are_specific(tmp_path, text, fragment):
    (tmp_path / "charpente.toml").write_text(text)
    with pytest.raises(ChError) as exc:
        load_workspace(str(tmp_path / "charpente.toml"))
    assert exc.value.code == "CH1025" and fragment in str(exc.value)


def test_toml_unknown_option_override(tmp_path):
    with pytest.raises(ChError) as exc:
        toml_workspace(tmp_path, options={"nope": "1"})
    assert exc.value.code == "CH1022"


def test_toml_is_found_when_there_is_no_dot_charpente_file(tmp_path, monkeypatch):
    from charpente.workspace_finder import find_workspace_file
    (tmp_path / "charpente.toml").write_text("")
    assert find_workspace_file(tmp_path).name == "charpente.toml"
    (tmp_path / "w.charpente").write_text("")
    assert find_workspace_file(tmp_path).name == "w.charpente"          # the DSL file wins


# ====================================================== real compiler, end to end
V2_PROJECT = """
from charpente import *
with Workspace("Demo") as ws:
    verbose = ws.option("verbose", default=False)

    with Target("greeter") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.sources(["greeter/greeter.cpp"])
        t.public_include_dirs(["greeter/include"])
        t.public_defines(["GREETING=\\"hello\\""])

    with Target("app") as t:
        t.sources(["app/main.cpp"])
        t.uses("greeter")
        if verbose:
            t.defines(["VERBOSE=1"])
        with t.on_config("Release") as c:
            c.defines(["MODE_RELEASE"])
"""


@requires_compiler
def test_v2_project_builds_and_runs_for_real(tmp_path, monkeypatch, capfd):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "greeter" / "include").mkdir(parents=True)
    (tmp_path / "app").mkdir()
    (tmp_path / "greeter" / "include" / "greeter.h").write_text("#pragma once\nconst char* greet();\n")
    (tmp_path / "greeter" / "greeter.cpp").write_text('#include "greeter.h"\nconst char* greet() { return GREETING; }\n')
    (tmp_path / "app" / "main.cpp").write_text(
        '#include <cstdio>\n#include "greeter.h"\n'
        "int main() {\n  std::printf(\"%s\", greet());\n"
        "#ifdef VERBOSE\n  std::printf(\"!\");\n#endif\n#ifdef MODE_RELEASE\n  std::printf(\" (release)\");\n#endif\n"
        "  std::printf(\"\\n\");\n}\n")
    (tmp_path / "w.charpente").write_text(V2_PROJECT)
    assert main(["run", "--target", "app"]) == 0
    assert capfd.readouterr().out.strip().endswith("hello")
    assert main(["run", "--target", "app", "--config", "Release", "--opt", "verbose=true"]) == 0
    out = capfd.readouterr().out
    assert "hello! (release)" in out


@requires_compiler
def test_toml_project_builds_and_runs_for_real(tmp_path, monkeypatch, capfd):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CHARPENTE_TRUST_ALL")                   # a toml workspace needs no approval
    (tmp_path / "main.cpp").write_text('#include <cstdio>\nint main() { std::printf("toml ok\\n"); }\n')
    (tmp_path / "charpente.toml").write_text('[workspace]\nname = "T"\n[[target]]\nname = "t"\nsources = ["main.cpp"]\n')
    assert main(["run"]) == 0
    assert "toml ok" in capfd.readouterr().out


@requires_compiler
def test_changing_a_used_librarys_public_define_rebuilds_the_user(tmp_path):
    (tmp_path / "lib.cpp").write_text("int lib(){return 1;}")
    (tmp_path / "main.cpp").write_text("int main(){return 0;}")
    dsl = """
        from charpente import *
        with Workspace("W") as ws:
            with Target("lib") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["lib.cpp"])
                t.public_defines(["FLAG=%d"])
            with Target("app") as t:
                t.sources(["main.cpp"])
                t.uses("lib")
    """
    from charpente.toolchains import pick_default
    tc = pick_default(host_os())
    ws1 = workspace(tmp_path, dsl % 1, files={})
    r1 = builder.build_workspace(ws1, tc, host_os())
    assert r1.ok
    ws2 = workspace(tmp_path, dsl % 2, files={})
    r2 = builder.build_workspace(ws2, tc, host_os())
    assert r2.ok and not r2.target("app").skipped                 # the fast path noticed the changed definition
    assert BuildContext().config == "Debug"
