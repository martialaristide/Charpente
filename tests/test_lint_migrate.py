import textwrap

import pytest

from charpente.cli import main
from charpente.dsl.loader import load_workspace
from charpente.lint import lint_source
from charpente.migrate import migrate_source


def codes(source):
    return [i.code for i in lint_source(textwrap.dedent(source))]


def messages(source):
    return " | ".join(i.message for i in lint_source(textwrap.dedent(source)))


CLEAN = """
    from charpente import *
    with Workspace("W") as ws:
        ws.requires("fmt")
        with Target("core") as t:
            t.kind(Kind.STATIC_LIBRARY)
            t.sources(["core/**/*.cpp"])
        with Target("app") as t:
            t.sources(["app/**/*.cpp"])
            t.uses("core", "fmt")
"""


def test_a_clean_workspace_has_no_findings():
    assert lint_source(textwrap.dedent(CLEAN)) == []


def test_it_analyses_without_executing():
    marker = "should-never-run"
    source = f"import os\nos.system('echo {marker}')\nraise SystemExit(1)\n"
    assert lint_source(source) == []                     # nothing executed, nothing crashed


def test_syntax_errors_are_reported_with_a_line():
    issues = lint_source("with Workspace(:\n")
    assert issues[0].code == "CH1101" and issues[0].severity == "error" and issues[0].line == 1


def test_invalid_and_absolute_patterns():
    assert "CH1102" in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["src/**.cpp"])
    """)
    text = messages("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["/abs/x.cpp", "C:\\\\abs\\\\y.cpp"])
    """)
    assert text.count("absolute") == 2


def test_valid_patterns_are_not_flagged():
    assert lint_source(textwrap.dedent(CLEAN)) == [] and "CH1102" not in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["**/*.cpp", "src/*.c", "a/b/**"])
    """)


def test_unknown_depends_on_and_uses():
    out = codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("app") as t:
                t.sources(["a.cpp"])
                t.depends_on(["ghost"])
                t.uses("phantom")
    """)
    assert "CH1103" in out and "CH1109" in out


def test_uses_of_a_required_package_is_fine():
    assert "CH1109" not in codes("""
        from charpente import *
        with Workspace("W") as ws:
            ws.requires("fmt@^10")
            with Target("app") as t:
                t.sources(["a.cpp"])
                t.uses("fmt")
    """)


def test_dynamic_names_are_skipped_not_guessed():
    assert codes("""
        from charpente import *
        with Workspace("W") as ws:
            for name in ["a", "b"]:
                with Target(name) as t:
                    t.sources(["x.cpp"])
            with Target("app") as t:
                t.sources(["m.cpp"])
                t.depends_on(["a"])
    """) == []


def test_depends_on_without_links_is_the_classic_trap():
    text = messages("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("core") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
            with Target("app") as t:
                t.sources(["m.cpp"])
                t.depends_on(["core"])
    """)
    assert "does not link it" in text and 'uses("core")' in text
    linked = codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("core") as t:
                t.kind(Kind.STATIC_LIBRARY)
                t.sources(["a.cpp"])
            with Target("app") as t:
                t.sources(["m.cpp"])
                t.depends_on(["core"])
                t.links(["core"])
    """)
    assert "CH1105" not in linked


def test_cycles_duplicates_and_misplaced_targets():
    assert "CH1104" in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["a.cpp"]); t.uses("b")
            with Target("b") as t:
                t.sources(["b.cpp"]); t.depends_on(["a"])
    """)
    assert "CH1107" in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["a.cpp"])
            with Target("a") as t:
                t.sources(["b.cpp"])
    """)
    assert "CH1108" in codes("""
        from charpente import *
        with Target("a") as t:
            t.sources(["a.cpp"])
    """)


def test_typos_in_method_names_get_a_suggestion():
    issues = lint_source(textwrap.dedent("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sourcess(["a.cpp"])
                t.include_dir(["x"])
    """))
    bad = [i for i in issues if i.code == "CH1106"]
    assert len(bad) == 2 and "sources" in bad[0].message and bad[0].severity == "error"


def test_condition_blocks_and_rules_are_checked_too():
    assert "CH1106" in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Rule("r") as r:
                r.comand(["x"])
            with Target("a") as t:
                t.sources(["a.cpp"])
                with t.on_config("Release") as c:
                    c.definez(["X"])
    """) and codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.sources(["a.cpp"])
                with t.on_platform("android-*") as p:
                    p.android(package="x")
    """) == []


def test_missing_sources_warning():
    assert "CH1110" in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("a") as t:
                t.kind(Kind.EXECUTABLE)
    """)
    assert "CH1110" not in codes("""
        from charpente import *
        with Workspace("W") as ws:
            with Target("h") as t:
                t.kind(Kind.HEADER_ONLY)
    """)


# ==================================================================== migrate
V1 = """from charpente import *

with Workspace("Demo") as ws:
    with Target("core") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.sources(["core.cpp"])

    with Target("app") as t:
        t.sources(["app.cpp"])
        t.depends_on(["core", "extra"])
        t.links(["core", "m"])
"""


def test_depends_on_plus_links_become_uses():
    result = migrate_source(V1)
    assert result.changed and "uses" in result.changes[0]
    assert 't.uses(["core"])' in result.new_source or 't.uses("core")' in result.new_source.replace("['", '"').replace("']", '"')
    assert 't.depends_on(["extra"])' in result.new_source and 't.links(["m"])' in result.new_source
    assert 't.depends_on(["core"' not in result.new_source
    compile(result.new_source, "<migrated>", "exec")                       # still valid Python


def test_migrated_workspace_builds_the_same_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    from helpers import GCC

    from charpente.core.planner import plan_workspace
    from charpente.dsl.model import OS
    for name in ("core.cpp", "app.cpp"):
        (tmp_path / name).write_text("x")
    v1 = V1.replace(', "extra"', "")
    (tmp_path / "old.charpente").write_text(v1)
    (tmp_path / "new.charpente").write_text(migrate_source(v1).new_source)
    plans = []
    for name in ("old", "new"):
        ws = load_workspace(str(tmp_path / f"{name}.charpente"))
        plans.append(plan_workspace(ws, GCC, OS.LINUX))
    old_link, new_link = (list(p.graph.actions["link:app"].argv) for p in plans)
    assert sorted(old_link) == sorted(new_link) and old_link.count("-lcore") == new_link.count("-lcore") == 1
    assert plans[0].graph.deps["link:app"] == plans[1].graph.deps["link:app"]


def test_nothing_to_migrate_and_unsafe_cases_are_left_alone():
    assert not migrate_source('from charpente import *\nwith Workspace("W") as ws:\n    pass\n').changed
    only_deps = V1.replace('        t.links(["core", "m"])\n', "")
    assert not migrate_source(only_deps).changed
    dynamic = V1.replace('t.depends_on(["core", "extra"])', "t.depends_on(names)")
    assert not migrate_source(dynamic).changed
    disjoint = V1.replace('["core", "m"]', '["m"]')
    assert not migrate_source(disjoint).changed
    assert not migrate_source("this is not python (").changed


def test_migration_when_links_comes_first_and_everything_moves():
    source = ('from charpente import *\nwith Workspace("W") as ws:\n    with Target("a") as t:\n'
              '        t.links(["x"])\n        t.sources(["a.cpp"])\n        t.depends_on(["x"])\n')
    result = migrate_source(source)
    assert result.changed
    assert "depends_on" not in result.new_source and "links" not in result.new_source and "uses" in result.new_source
    compile(result.new_source, "<m>", "exec")


# ======================================================================== CLI
@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "w.charpente").write_text(V1.replace(', "extra"', ""))
    return tmp_path


def test_lint_command(project, capsys):
    assert main(["lint"]) == 0                                    # warnings only: the dsl trap
    out = capsys.readouterr().out
    assert "CH1105" not in out                                    # this v1 file links what it depends on
    (project / "w.charpente").write_text(V1.replace('        t.links(["core", "m"])\n', ""))
    assert main(["lint"]) == 0
    assert "CH1105" in capsys.readouterr().out
    assert main(["lint", "--strict"]) == 1
    (project / "w.charpente").write_text("with Workspace(:\n")
    assert main(["lint"]) == 1


def test_lint_on_toml(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "charpente.toml").write_text('[workspace]\nname = "x"\n')
    assert main(["lint"]) == 0 and "valid" in capsys.readouterr().out
    (tmp_path / "charpente.toml").write_text('[workspace]\nname = "x"\nbogus = 1\n')
    assert main(["lint"]) == 1


def test_migrate_command_dry_run_then_write(project, capsys):
    original = (project / "w.charpente").read_text()
    assert main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "-        t.depends_on" in out and "Dry run" in out
    assert (project / "w.charpente").read_text() == original
    assert main(["migrate", "--write"]) == 0
    assert (project / "w.charpente.bak").read_text() == original
    assert "uses" in (project / "w.charpente").read_text()
    assert main(["migrate"]) == 0 and "nothing to migrate" in capsys.readouterr().out


def test_migrate_refuses_toml(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "charpente.toml").write_text('[workspace]\nname = "x"\n')
    assert main(["migrate"]) == 1


def test_options_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "w.charpente").write_text(
        'from charpente import *\nwith Workspace("W") as ws:\n'
        '    ws.option("fast", default=False, help="Go fast")\n    ws.option("mode", choices=["a", "b"])\n')
    assert main(["options"]) == 0
    out = capsys.readouterr().out
    assert "fast = False" in out and "Go fast" in out and "choices: a, b" in out
    assert main(["options", "--opt", "fast=true"]) == 0
    assert "fast = True" in capsys.readouterr().out
    assert main(["options", "--opt", "fast=maybe"]) == 1
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n    pass\n')
    assert main(["options"]) == 0 and "no options" in capsys.readouterr().out
