"""`charpente docs`: the doc-comment extractor, the target graph, and the generated pages."""
import shutil
import xml.etree.ElementTree as ET

import pytest

from charpente import docsgen
from charpente.cli import main
from charpente.dsl.loader import load_workspace

HEADER = r'''#pragma once
#include <string>

/// A greeter.
/// It keeps no state.
class Greeter {
public:
    /**
     * @brief Build a greeting.
     * @param who  Who to greet;
     *             may be empty.
     * @param loud Shout it.
     * @return The greeting text.
     * @note Not thread safe.
     */
    std::string greet(const std::string& who, bool loud = false) const;

    /// Number of greetings so far.
    int count = 0;
};

//! Result codes.
enum class Status { Ok, Failed };

/** The default name. */
constexpr const char* kDefaultName = "world";

/// Add two numbers. Overflow wraps.
template <typename T>
T add(T a, T b);

/// A shorthand.
using Text = std::string;

/// Square a value.
#define SQUARE(x) ((x) * (x))

namespace util {
/// Trim spaces.
std::string trim(const std::string& s);
}

// An ordinary comment: not documentation.
int undocumented();

/// Documented, but not something we understand.
int main_like = if_you_like;
'''


def by_name(items):
    return {i.name: i for i in items}


def test_declarations_and_their_kinds_are_found():
    items = by_name(docsgen.extract(HEADER))
    assert {n: i.kind for n, i in items.items()} == {"Greeter": "class", "greet": "function", "count": "variable", "Status": "enum", "kDefaultName": "variable",
                                                     "add": "function", "Text": "alias", "SQUARE": "macro", "trim": "function", "main_like": "variable"}
    assert "undocumented" not in items                                                       # an ordinary comment documents nothing


def test_briefs_bodies_and_tags():
    items = by_name(docsgen.extract(HEADER))
    assert items["Greeter"].brief == "A greeter. It keeps no state." or items["Greeter"].brief == "A greeter."
    greet = items["greet"]
    assert greet.brief == "Build a greeting."
    assert greet.params == [("who", "Who to greet; may be empty."), ("loud", "Shout it.")]      # a continued line belongs to its parameter
    assert greet.returns == "The greeting text." and greet.notes == ["note: Not thread safe."]
    assert greet.signature == "std::string greet(const std::string& who, bool loud = false) const"
    assert items["kDefaultName"].brief == "The default name." and items["Status"].brief == "Result codes."


def test_templates_macros_and_namespaced_functions():
    items = by_name(docsgen.extract(HEADER))
    assert items["add"].signature.startswith("template <typename T>") and items["add"].brief == "Add two numbers. Overflow wraps."
    assert items["SQUARE"].signature == "#define SQUARE(x) ((x) * (x))" or items["SQUARE"].signature.startswith("#define SQUARE")
    assert items["trim"].brief == "Trim spaces."


def test_the_first_sentence_is_the_brief_without_a_tag():
    (item,) = docsgen.extract("/// First line.\n/// Second line.\n///\n/// More detail here.\nint f();\n")
    assert item.brief == "First line. Second line." and item.body == "More detail here."


def test_empty_and_odd_input_never_raises():
    assert docsgen.extract("") == []
    assert docsgen.extract("/// alone at the end of the file") == []
    assert docsgen.extract("/** unterminated") == []
    assert docsgen.extract("/// doc\n\n\n// nothing follows a blank gap that is a declaration\n") == []
    long = "/// x\n" + "int f(" + "int a, " * 400 + "int z);\n"
    assert docsgen.extract(long)[0].name == "f"                                                # a huge declaration is cut, not a hang


def test_classification():
    assert docsgen.classify("class Foo : public Bar") == ("class", "Foo")
    assert docsgen.classify("struct Vec3") == ("struct", "Vec3")
    assert docsgen.classify("enum class E : int") == ("enum", "E")
    assert docsgen.classify("namespace a::b") == ("namespace", "a::b")
    assert docsgen.classify("int compute(int x) const noexcept") == ("function", "compute")
    assert docsgen.classify("Widget::Widget(int x)") == ("function", "Widget::Widget")
    assert docsgen.classify("bool operator==(const A& o) const") == ("function", "operator==")
    assert docsgen.classify("typedef unsigned long ulong_t") == ("alias", "ulong_t")
    assert docsgen.classify("if (x)") is None or docsgen.classify("if (x)")[0] != "function"


WORKSPACE = '''from charpente import *

with Workspace("docs", version="3.1.0") as ws:
    with Target("core") as core:
        core.kind(Kind.STATIC_LIBRARY)
        core.standard("c++17")
        core.sources(["src/core/*.cpp"])
        core.public_include_dirs(["include"])
    with Target("plugin") as plugin:
        plugin.kind(Kind.PLUGIN)
        plugin.standard("c++17")
        plugin.sources(["src/plugin.cpp"])
        plugin.uses("core")
    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("core", "plugin")
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    for folder in ("src/core", "include"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "docs.charpente").write_text(WORKSPACE, encoding="utf-8")
    (tmp_path / "include" / "greeter.hpp").write_text(HEADER, encoding="utf-8")
    (tmp_path / "src" / "core" / "a.cpp").write_text("int x;\n", encoding="utf-8")
    (tmp_path / "src" / "plugin.cpp").write_text("int y;\n", encoding="utf-8")
    (tmp_path / "src" / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_graph_as_mermaid_and_svg(project):
    workspace = load_workspace(str(project / "docs.charpente"))
    text = docsgen.mermaid(workspace)
    assert text.startswith("graph LR") and "app --> core" in text and "app --> plugin" in text and "plugin --> core" in text and "app([app])" in text
    root = ET.fromstring(docsgen.svg(workspace))
    assert root.tag.endswith("svg") and len(list(root.iter("{http://www.w3.org/2000/svg}rect"))) == 3
    labels = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert {"core", "plugin", "app"} <= set(labels)
    assert len(list(root.iter("{http://www.w3.org/2000/svg}path"))) >= 3                       # the marker's arrow head plus three dependency edges


def test_names_in_the_svg_are_escaped(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("w") as ws:\n    with Target("a-b") as t:\n        t.sources(["*.cpp"])\n', encoding="utf-8")
    ET.fromstring(docsgen.svg(load_workspace(str(tmp_path / "w.charpente"))))                   # well-formed XML whatever the names


def test_the_command_writes_pages_for_every_target(project, capsys):
    assert main(["docs"]) == 0
    out = project / "docs" / "api"
    assert sorted(p.name for p in (out / "targets").iterdir()) == ["app.md", "core.md", "plugin.md"]
    index = (out / "index.md").read_text(encoding="utf-8")
    assert "# docs" in index and "Version 3.1.0" in index and "```mermaid" in index and "graph.svg" in index
    assert "| [core](targets/core.md) | static_library | cpp `c++17` | 10 |" in index
    core = (out / "targets" / "core.md").read_text(encoding="utf-8")
    assert "## `include/greeter.hpp`" in core and "### `Greeter` — class" in core and "**Parameters**" in core and "- `who`: Who to greet; may be empty." in core
    assert "**Returns:** The greeting text." in core and "> note: Not thread safe." in core
    assert "No documented declarations" in (out / "targets" / "app.md").read_text(encoding="utf-8")
    assert "Uses: [core](core.md)" in (out / "targets" / "plugin.md").read_text(encoding="utf-8")
    assert ET.parse(out / "graph.svg").getroot().tag.endswith("svg")
    assert "10 documented declaration(s)" in capsys.readouterr().out


def test_a_project_without_doc_comments_is_told_how_to_write_them(project, capsys):
    (project / "include" / "greeter.hpp").write_text("int plain();\n", encoding="utf-8")
    assert main(["docs", "--out", str(project / "elsewhere")]) == 0
    assert "documentation comments" in capsys.readouterr().out and (project / "elsewhere" / "index.md").is_file()


def test_the_doxyfile_lists_the_public_headers(project):
    text = docsgen.doxyfile(load_workspace(str(project / "docs.charpente")), project / "out")
    assert 'PROJECT_NAME = "docs"' in text and "PROJECT_NUMBER = 3.1.0" in text and "include" in text.split("INPUT = ")[1].splitlines()[0]
    assert "RECURSIVE = YES" in text and "GENERATE_HTML = YES" in text


def test_doxygen_is_used_only_when_asked_and_present(project, capsys, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    assert main(["docs", "--doxygen"]) != 0
    assert "CH8007" in capsys.readouterr().err
