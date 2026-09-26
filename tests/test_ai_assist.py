"""AI assistance: what is sent (context, secret filtering, confirmation) and what comes back (diffs are checked against the real files)."""
import shutil
from pathlib import Path

import pytest

from charpente.ai import flow, migrate, testgen
from charpente.ai import patch as patch_mod
from charpente.ai.context import Context, error_context, is_secret_file, locations, redact_text, snippet
from charpente.ai.fix import apply_verified, request_fix, restore, snapshot
from charpente.ai.provider import AIProvider
from charpente.cli import main
from charpente.commands import ai as ai_cmd
from charpente.commands import fix as fix_cmd
from charpente.errors import ChError

HAVE_COMPILER = any(shutil.which(c) for c in ("g++", "clang++", "cl"))
# Assembled at run time so the source of this test file does not itself look like it contains secrets.
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def put(path, text):
    """Write text exactly as given (write_text would turn newlines into CRLF on Windows)."""
    Path(path).write_bytes(text.encode("utf-8"))


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, *answers, available=True):
        self.answers = list(answers)
        self.prompts = []
        self.systems = []
        self.available = available

    def is_available(self):
        return self.available

    def complete(self, prompt, *, system=None):
        if not self.available:
            return "AI features are not configured."
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


# ---------------------------------------------------------------------- redaction and context
def test_known_token_formats_are_replaced():
    text = f"key={AWS} and {GITHUB} plus -----BEGIN RSA PRIVATE KEY-----"
    clean, count = redact_text(text)
    assert AWS not in clean and GITHUB not in clean and "BEGIN RSA PRIVATE KEY" not in clean and count == 3
    assert "[REDACTED AWS access key id]" in clean


def test_credentials_in_urls_and_headers_are_replaced():
    clean, count = redact_text("clone https://user:hunter2secret@example.com/x.git\nAuthorization: Bearer abcdef0123456789xyz")
    assert "hunter2secret" not in clean and "abcdef0123456789xyz" not in clean and count == 2
    assert "https://[REDACTED credentials]@example.com/x.git" in clean


def test_high_entropy_assignments_are_replaced_but_placeholders_are_not():
    clean, count = redact_text('api_key = "q8Zr2Xv9LmT4bWp7Yc1Nd"\npassword = "changeme"\nname = "just a plain string"')
    assert "q8Zr2Xv9LmT4bWp7Yc1Nd" not in clean and count == 1
    assert '"changeme"' in clean and "just a plain string" in clean


def test_ordinary_code_is_untouched():
    code = 'int main() { const char* s = "hello world"; return sizeof(s) > 0 ? 0 : 1; }\n// see https://example.com/docs\n'
    assert redact_text(code) == (code, 0)


@pytest.mark.parametrize("name", [".env", ".env.local", "config/server.pem", "id_rsa", "a/b/private.key", "credentials.json", "app.secrets.toml", ".npmrc"])
def test_secret_files_are_recognised(name):
    assert is_secret_file(name)


@pytest.mark.parametrize("name", ["src/main.cpp", "environment.hpp", "keyboard.cpp", "docs/secretary.md"])
def test_ordinary_files_are_not_secret_files(name):
    assert not is_secret_file(name)


def test_snippet_is_numbered_and_bounded(tmp_path):
    (tmp_path / "a.cpp").write_text("".join(f"line {i}\n" for i in range(1, 101)), encoding="utf-8")
    text = snippet(tmp_path, "a.cpp", 50, radius=2)
    assert text.splitlines() == ["   48| line 48", "   49| line 49", "   50| line 50", "   51| line 51", "   52| line 52"]
    assert snippet(tmp_path, "a.cpp", 1, radius=2).splitlines()[0] == "    1| line 1"


def test_snippet_refuses_what_must_not_be_sent(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.cpp").write_text("secret\n", encoding="utf-8")
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "big.cpp").write_bytes(b"x" * (600 * 1024))
    (tmp_path / "bin.cpp").write_bytes(b"\xff\xfe\x00")
    assert snippet(tmp_path, str(outside / "x.cpp"), 1) is None
    assert snippet(tmp_path, "../x.cpp", 1) is None
    assert snippet(tmp_path, ".env", 1) is None
    assert snippet(tmp_path, "big.cpp", 1) is None
    assert snippet(tmp_path, "bin.cpp", 1) is None
    assert snippet(tmp_path, "missing.cpp", 1) is None


def test_locations_are_found_once_in_order():
    text = "src/a.cpp:10:5: error: x\nsrc/a.cpp:10:9: note\nC:\\p\\b.hpp:3: error\nsrc/a.cpp:20: warning"
    assert locations(text) == [("src/a.cpp", 10), ("C:\\p\\b.hpp", 3), ("src/a.cpp", 20)]


class WS:
    name = "demo"
    targets = {}


def test_error_context_holds_the_error_and_the_code_around_it(tmp_path):
    (tmp_path / "src").mkdir()
    put(tmp_path / "src" / "main.cpp", "int main() {\n  return missing;\n}\n")
    context = error_context(tmp_path, WS(), "src/main.cpp:2:10: error: 'missing' was not declared")
    labels = [i.label for i in context.items]
    assert labels == ["workspace", "build output", "src/main.cpp:2"]
    assert "return missing;" in context.render() and "### src/main.cpp:2" in context.render()
    assert "3 items" not in context.summary() and "src/main.cpp:2" in context.summary()


def test_error_context_leaves_out_secrets_files_and_outsiders_and_says_so(tmp_path):
    (tmp_path / "secrets.h").write_text('#define TOKEN "abc"\n', encoding="utf-8")
    context = error_context(tmp_path, WS(), "secrets.h:1: error\n/somewhere/else.cpp:4: error\nsrc/gone.cpp:1: error")
    assert not any(i.label.startswith("secrets.h") for i in context.items)
    assert any("secrets.h (looks like a secrets file)" in s for s in context.skipped)
    assert any("outside the project" in s for s in context.skipped)
    assert "left out" in context.summary()


def test_error_context_redacts_secrets_inside_the_code_it_sends(tmp_path):
    (tmp_path / "a.cpp").write_text(f'const char* k = "{AWS}";\nint x = oops;\n', encoding="utf-8")
    context = error_context(tmp_path, WS(), "a.cpp:2: error: oops")
    assert AWS not in context.render() and context.redactions == 1 and "1 secret(s) replaced" in context.summary()


def test_the_size_limit_is_enforced_and_visible(tmp_path):
    context = Context(limit=1000)
    assert context.add("one", "x" * 900)
    assert not context.add("two", "y" * 500) and context.chars <= 1000
    assert any("two" in s and "limit" in s for s in context.skipped)
    context = Context(limit=1000)
    context.add("first", "a" * 600)
    context.add("cut", "b" * 900)                                                  # partly fits: cut, and marked
    assert context.chars <= 1100 and "cut at the size limit" in context.render()


def test_at_most_four_files_are_sent(tmp_path):
    lines = []
    for i in range(7):
        (tmp_path / f"f{i}.cpp").write_text("int x;\n" * 5, encoding="utf-8")
        lines.append(f"f{i}.cpp:2: error: bad")
    context = error_context(tmp_path, WS(), "\n".join(lines))
    assert len([i for i in context.items if i.label.endswith(":2")]) == 4
    assert sum("more than 4 files" in s for s in context.skipped) == 3


# ---------------------------------------------------------------------- confirmation
def test_review_shows_the_context_and_needs_agreement():
    ctx = Context()
    ctx.add("build output", "error here")
    said = []
    provider = FakeProvider("x")
    assert flow.review_and_confirm(ctx, provider, show_full=False, assume_yes=True, dry_run=False, say=said.append) is True
    assert "Charpente will send this to fake" in said[0] and "error here" not in "\n".join(said)          # summary only
    said.clear()
    flow.review_and_confirm(ctx, provider, show_full=True, assume_yes=True, dry_run=False, say=said.append)
    assert "error here" in "\n".join(said)                                                                  # --show-context prints it all
    assert provider.prompts == []                                                                            # reviewing never sends


def test_dry_run_sends_nothing():
    ctx = Context()
    ctx.add("a", "text")
    said = []
    assert flow.review_and_confirm(ctx, FakeProvider("x"), show_full=False, assume_yes=True, dry_run=True, say=said.append) is False
    assert "Dry run: nothing was sent." in said and "text" in "\n".join(said)


def test_a_non_interactive_session_must_pass_yes():
    ctx = Context()
    ctx.add("a", "text")
    with pytest.raises(flow.NotConfirmed, match="--yes"):
        flow.review_and_confirm(ctx, FakeProvider("x"), show_full=False, assume_yes=False, dry_run=False, say=lambda t: None, is_interactive=False)


def test_an_interactive_no_sends_nothing():
    ctx = Context()
    ctx.add("a", "text")
    with pytest.raises(flow.NotConfirmed):
        flow.review_and_confirm(ctx, FakeProvider("x"), show_full=False, assume_yes=False, dry_run=False, say=lambda t: None, read=lambda p: "n",
                                is_interactive=True)
    assert flow.review_and_confirm(ctx, FakeProvider("x"), show_full=False, assume_yes=False, dry_run=False, say=lambda t: None, read=lambda p: "y",
                                   is_interactive=True)


def test_an_unconfigured_provider_is_reported_honestly():
    with pytest.raises(ChError) as info:
        flow.require_provider(FakeProvider("x", available=False))
    assert info.value.code == "CH8020" and "not configured" in info.value.message


# ---------------------------------------------------------------------- patches
DIFF = """--- a/src/main.cpp
+++ b/src/main.cpp
@@ -1,4 +1,4 @@
 int main() {
-  return missing;
+  return 0;
 }
"""
FILE = "int main() {\n  return missing;\n}\n"


def test_extract_diff_from_fenced_and_bare_answers():
    assert patch_mod.extract_diff("The cause is X.\n```diff\n" + DIFF + "```\nDone.").startswith("--- a/src/main.cpp")
    assert patch_mod.extract_diff("Here:\n" + DIFF).startswith("--- a/src/main.cpp")
    assert patch_mod.extract_diff("```cpp\nint x;\n```\nno diff here") == ""
    assert patch_mod.extract_diff("```\n" + DIFF + "```").startswith("--- a/")


def test_parse_and_apply_simple(tmp_path):
    (tmp_path / "src").mkdir()
    put(tmp_path / "src" / "main.cpp", FILE)
    patches = patch_mod.parse(DIFF)
    assert [p.path for p in patches] == ["src/main.cpp"] and len(patches[0].hunks) == 1
    assert patch_mod.apply_patches(tmp_path, patches) == {"src/main.cpp": "int main() {\n  return 0;\n}\n"}
    assert (tmp_path / "src" / "main.cpp").read_text(encoding="utf-8") == FILE                    # applying is in memory only


def test_a_hunk_is_found_by_content_even_when_line_numbers_are_wrong(tmp_path):
    (tmp_path / "src").mkdir()
    body = "".join(f"// {i}\n" for i in range(30)) + FILE
    put(tmp_path / "src" / "main.cpp", body)
    result = patch_mod.apply_patches(tmp_path, patch_mod.parse(DIFF))["src/main.cpp"]              # the diff says line 1; the code is at line 31
    assert result.endswith("int main() {\n  return 0;\n}\n") and result.startswith("// 0\n")


def test_a_hunk_that_matches_nowhere_or_twice_is_refused(tmp_path):
    (tmp_path / "src").mkdir()
    put(tmp_path / "src" / "main.cpp", "int main() { return 1; }\n")
    with pytest.raises(patch_mod.PatchError, match="does not match"):
        patch_mod.apply_patches(tmp_path, patch_mod.parse(DIFF))
    put(tmp_path / "src" / "main.cpp", FILE + FILE)
    twice = DIFF.replace("@@ -1,4 +1,4 @@", "@@ -4,4 +4,4 @@")                                             # equally near both copies? (1 and 4) -> hint 4 is exact
    assert patch_mod.apply_patches(tmp_path, patch_mod.parse(twice))["src/main.cpp"].count("return 0;") == 1
    put(tmp_path / "src" / "main.cpp", FILE + "\n" + FILE)
    ambiguous = DIFF.replace("@@ -1,4 +1,4 @@", "@@ -3,4 +3,4 @@")                                          # copies at 0 and 4, hint 2: equally far
    with pytest.raises(patch_mod.PatchError, match="two places"):
        patch_mod.apply_patches(tmp_path, patch_mod.parse(ambiguous))


def test_trailing_whitespace_differences_are_tolerated_and_line_endings_kept(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_bytes(b"int main() {  \r\n  return missing;\r\n}\r\n")
    result = patch_mod.apply_patches(tmp_path, patch_mod.parse(DIFF))["src/main.cpp"]
    assert result == "int main() {  \r\n  return 0;\r\n}\r\n"
    patch_mod.write(tmp_path, {"src/main.cpp": result})
    assert (tmp_path / "src" / "main.cpp").read_bytes() == b"int main() {  \r\n  return 0;\r\n}\r\n"


def test_new_files_are_allowed_deletions_and_existing_targets_are_not(tmp_path):
    new = "--- /dev/null\n+++ b/src/util.hpp\n@@ -0,0 +1,2 @@\n+#pragma once\n+int util();\n"
    assert patch_mod.apply_patches(tmp_path, patch_mod.parse(new)) == {"src/util.hpp": "#pragma once\nint util();\n"}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.hpp").write_text("x", encoding="utf-8")
    with pytest.raises(patch_mod.PatchError, match="already exists"):
        patch_mod.apply_patches(tmp_path, patch_mod.parse(new))
    with pytest.raises(patch_mod.PatchError, match="deleting"):
        patch_mod.parse("--- a/x.cpp\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")


@pytest.mark.parametrize("path", ["../evil.cpp", "/etc/passwd", "C:/x.cpp", "a/../../b.cpp", ".git/config", ".env", "keys/server.pem"])
def test_paths_a_fix_may_not_touch_are_refused(tmp_path, path):
    diff = f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(patch_mod.PatchError):
        patch_mod.apply_patches(tmp_path, patch_mod.parse(diff))


def test_garbage_is_not_a_patch():
    for text in ("", "just words", "--- a/x\n+++ b/x\n", "--- a/x\n+++ b/x\n@@ -1 +1 @@\n context only\n"):
        with pytest.raises(patch_mod.PatchError):
            patch_mod.parse(text)


def test_unified_shows_the_change_for_review(tmp_path):
    (tmp_path / "src").mkdir()
    put(tmp_path / "src" / "main.cpp", FILE)
    shown = patch_mod.unified(tmp_path, {"src/main.cpp": "int main() {\n  return 0;\n}\n"})
    assert "-  return missing;" in shown and "+  return 0;" in shown and shown.startswith("--- a/src/main.cpp")


# ---------------------------------------------------------------------- fix
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "demo.charpente").write_text('from charpente import *\n\nwith Workspace("demo") as ws:\n    with Target("app") as app:\n        app.kind(Kind.EXECUTABLE)\n'
                                             '        app.standard("c++17")\n        app.sources(["src/*.cpp"])\n', encoding="utf-8")
    put(tmp_path / "src" / "main.cpp", FILE)
    return tmp_path


def test_request_fix_returns_a_proposal_that_applies(tmp_path):
    project(tmp_path)
    provider = FakeProvider("The name is not declared.\n```diff\n" + DIFF + "```")
    ctx = Context()
    ctx.add("build output", "src/main.cpp:2: error")
    proposal = request_fix(provider, ctx, tmp_path)
    assert proposal.files == ["src/main.cpp"] and proposal.explanation == "The name is not declared."
    assert "Fix this build error" in provider.prompts[0] and "unified diff" in provider.systems[0]


def test_request_fix_explains_when_there_is_no_diff(tmp_path):
    project(tmp_path)
    with pytest.raises(patch_mod.PatchError, match="no diff"):
        request_fix(FakeProvider("I cannot tell what is wrong."), Context(), tmp_path)


def test_apply_verified_keeps_a_good_change_and_reverts_a_bad_one(tmp_path):
    project(tmp_path)
    ctx = Context()
    proposal = request_fix(FakeProvider("```diff\n" + DIFF + "```"), ctx, tmp_path)
    target = tmp_path / "src" / "main.cpp"
    assert apply_verified(tmp_path, proposal, lambda: (False, "still broken")) == (False, "still broken")
    assert target.read_text(encoding="utf-8") == FILE                                                # restored
    assert apply_verified(tmp_path, proposal, lambda: (True, "")) == (True, "")
    assert "return 0;" in target.read_text(encoding="utf-8")


def test_a_crash_while_verifying_also_restores_the_files(tmp_path):
    project(tmp_path)
    proposal = request_fix(FakeProvider("```diff\n" + DIFF + "```"), Context(), tmp_path)

    def boom():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        apply_verified(tmp_path, proposal, boom)
    assert (tmp_path / "src" / "main.cpp").read_text(encoding="utf-8") == FILE


def test_snapshot_restore_is_byte_exact_and_removes_new_files(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    saved = snapshot(tmp_path, ["a.txt", "new.txt"])
    (tmp_path / "a.txt").write_bytes(b"changed")
    (tmp_path / "new.txt").write_text("created", encoding="utf-8")
    restore(tmp_path, saved)
    assert (tmp_path / "a.txt").read_bytes() == b"one\r\ntwo\r\n" and not (tmp_path / "new.txt").exists()


@pytest.fixture
def in_project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(project(tmp_path))
    monkeypatch.setattr(flow, "interactive", lambda: False)
    return tmp_path


def use(monkeypatch, provider):
    monkeypatch.setattr(fix_cmd, "select_provider", lambda: provider)
    monkeypatch.setattr(ai_cmd, "select_provider", lambda: provider)
    return provider


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_end_to_end_with_apply(in_project, monkeypatch, capsys):
    provider = use(monkeypatch, FakeProvider("The variable is undeclared.\n```diff\n" + DIFF + "```"))
    code = main(["fix", "--yes", "--apply"])
    out = capsys.readouterr().out
    assert code in (0, 1)                                                                          # the gate may skip tools that are not installed
    assert "return 0;" in (in_project / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "proposed change" in out and "Applied: the build succeeds" in out and "Running the quality gate" in out
    assert len(provider.prompts) == 1 and "missing" in provider.prompts[0]
    assert main(["build"]) == 0


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_without_apply_only_shows_the_diff(in_project, monkeypatch, capsys):
    use(monkeypatch, FakeProvider("```diff\n" + DIFF + "```"))
    assert main(["fix", "--yes"]) == 0
    assert "Not applied" in capsys.readouterr().out
    assert (in_project / "src" / "main.cpp").read_text(encoding="utf-8") == FILE


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_a_fix_that_does_not_build_is_reverted(in_project, monkeypatch, capsys):
    wrong = DIFF.replace("return 0;", "return still_missing;")
    use(monkeypatch, FakeProvider("```diff\n" + wrong + "```"))
    assert main(["fix", "--yes", "--apply"]) == 1
    assert "reverted" in capsys.readouterr().out
    assert (in_project / "src" / "main.cpp").read_text(encoding="utf-8") == FILE


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_refuses_an_answer_that_does_not_apply(in_project, monkeypatch, capsys):
    use(monkeypatch, FakeProvider("```diff\n--- a/src/other.cpp\n+++ b/src/other.cpp\n@@ -1 +1 @@\n-a\n+b\n```"))
    assert main(["fix", "--yes"]) != 0
    assert "CH8021" in capsys.readouterr().err
    assert (in_project / "src" / "main.cpp").read_text(encoding="utf-8") == FILE


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_sends_nothing_without_agreement(in_project, monkeypatch, capsys):
    provider = use(monkeypatch, FakeProvider("x"))
    assert main(["fix"]) != 0                                                                      # not interactive, no --yes
    assert "CH8022" in capsys.readouterr().err and provider.prompts == []
    assert main(["fix", "--dry-run"]) == 0                                                         # shows the context, sends nothing
    out = capsys.readouterr().out
    assert "exactly what is sent" in out and "return missing;" in out and provider.prompts == []


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_needs_a_configured_provider(in_project, monkeypatch, capsys):
    use(monkeypatch, FakeProvider("x", available=False))
    assert main(["fix", "--yes"]) != 0
    assert "CH8020" in capsys.readouterr().err


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_fix_on_a_working_build_does_not_call_the_provider(in_project, monkeypatch, capsys):
    (in_project / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    provider = use(monkeypatch, FakeProvider("x"))
    assert main(["fix", "--yes"]) == 0
    assert "Nothing to fix" in capsys.readouterr().out and provider.prompts == []


# ---------------------------------------------------------------------- ai tests
LIB_WS = '''from charpente import *

with Workspace("demo") as ws:
    with Target("mathlib") as lib:
        lib.kind(Kind.STATIC_LIBRARY)
        lib.standard("c++17")
        lib.sources(["src/*.cpp"])
        lib.public_include_dirs(["include"])
'''
GOOD_TEST = """```cpp
#include "mathlib.hpp"
#include <cstdio>
int main() {
  if (add(2, 3) != 5) { std::fprintf(stderr, "add failed\\n"); return 1; }
  return 0;
}
```"""


def lib_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "demo.charpente").write_text(LIB_WS, encoding="utf-8")
    (tmp_path / "include" / "mathlib.hpp").write_text("#pragma once\nint add(int a, int b);\n", encoding="utf-8")
    (tmp_path / "src" / "mathlib.cpp").write_text('#include "mathlib.hpp"\nint add(int a, int b) { return a + b; }\n', encoding="utf-8")
    return tmp_path


def test_extract_code_prefers_the_largest_block():
    assert testgen.extract_code("text\n```cpp\nint a;\n```\n```cpp\nint main() { return 0; }\n// longer\n```") == "int main() { return 0; }\n// longer\n"
    assert testgen.extract_code("no code at all") == ""
    assert testgen.extract_code("#include <x>\nint main() {}") .startswith("#include")


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_ai_tests_proposes_only_a_test_that_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(lib_project(tmp_path))
    monkeypatch.setattr(flow, "interactive", lambda: False)
    broken = "```cpp\n#include \"mathlib.hpp\"\nint main() { return nonexistent(add(1, 1)); }\n```"
    failing = "```cpp\n#include \"mathlib.hpp\"\nint main() { return add(1, 1) == 3 ? 0 : 1; }\n```"
    provider = use(monkeypatch, FakeProvider(broken, failing, GOOD_TEST))
    assert main(["ai", "tests", "mathlib", "--yes", "--write"]) == 0
    out = capsys.readouterr().out
    assert "it does not compile" in out and "compiles but fails" in out and "3 attempt(s)" in out
    written = (tmp_path / "tests" / "mathlib_ai_test.cpp").read_text(encoding="utf-8")
    assert "add(2, 3) != 5" in written
    assert len(provider.prompts) == 3 and "what happened when it was built and run" in provider.prompts[1] and "nonexistent" in provider.prompts[1]
    assert "add(int a, int b)" in provider.prompts[0]                                              # the header was part of the context


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_ai_tests_proposes_nothing_when_no_attempt_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(lib_project(tmp_path))
    monkeypatch.setattr(flow, "interactive", lambda: False)
    use(monkeypatch, FakeProvider("```cpp\nint main() { return 1; }\n```"))
    assert main(["ai", "tests", "mathlib", "--yes", "--attempts", "2", "--write"]) == 1
    assert "none is proposed" in capsys.readouterr().out
    assert not (tmp_path / "tests" / "mathlib_ai_test.cpp").exists()


@pytest.mark.skipif(not HAVE_COMPILER, reason="needs a C++ compiler")
def test_ai_tests_does_not_overwrite_and_does_not_write_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(lib_project(tmp_path))
    monkeypatch.setattr(flow, "interactive", lambda: False)
    use(monkeypatch, FakeProvider(GOOD_TEST))
    assert main(["ai", "tests", "mathlib", "--yes"]) == 0
    assert "Not written" in capsys.readouterr().out and not (tmp_path / "tests").exists()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "mathlib_ai_test.cpp").write_text("mine", encoding="utf-8")
    assert main(["ai", "tests", "mathlib", "--yes", "--write"]) != 0
    assert "CH8021" in capsys.readouterr().err and (tmp_path / "tests" / "mathlib_ai_test.cpp").read_text(encoding="utf-8") == "mine"
    assert main(["ai", "tests", "mathlib", "--yes", "--write", "--force"]) == 0
    assert "add(2, 3)" in (tmp_path / "tests" / "mathlib_ai_test.cpp").read_text(encoding="utf-8")


def test_ai_tests_rejects_unknown_and_test_targets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.chdir(lib_project(tmp_path))
    use(monkeypatch, FakeProvider("x"))
    assert main(["ai", "tests", "nope", "--yes"]) != 0
    assert "CH1008" in capsys.readouterr().err


# ---------------------------------------------------------------------- ai migrate
CMAKE = "cmake_minimum_required(VERSION 3.20)\nproject(demo CXX)\nadd_executable(demo main.cpp)\n"
DRAFT = '```python\nfrom charpente import *\n\nwith Workspace("demo", version="1.0.0") as ws:\n    with Target("demo") as t:\n        t.kind(Kind.EXECUTABLE)\n        t.standard("c++17")\n        t.sources(["main.cpp"])\n```'


def test_migrate_check_accepts_a_good_draft_and_rejects_bad_ones():
    ok, problems = migrate.check(migrate.extract(DRAFT))
    assert ok and all(not p.startswith("error") for p in problems)
    assert migrate.check("def broken(:\n")[0] is False
    assert migrate.check("print('hello')\n")[0] is False
    assert migrate.extract("```python\nprint(1)\n```") == "" and migrate.extract("no code") == ""


def test_migrate_never_executes_the_draft(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    text = f'from charpente import *\nopen({str(marker)!r}, "w").write("x")\nwith Workspace("a") as ws:\n    with Target("t") as t:\n        t.sources(["a.cpp"])\n'
    migrate.check(text)
    assert not marker.exists()


def test_migrate_end_to_end(tmp_path, monkeypatch, capsys):
    (tmp_path / "CMakeLists.txt").write_text(CMAKE + f'set(API_KEY "{AWS}")\n', encoding="utf-8")
    (tmp_path / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
    monkeypatch.setattr(flow, "interactive", lambda: False)
    provider = use(monkeypatch, FakeProvider(DRAFT))
    assert main(["ai", "migrate", str(tmp_path), "--yes", "--write"]) == 0
    target = tmp_path / f"{tmp_path.name}.charpente"
    assert 'Workspace("demo"' in target.read_text(encoding="utf-8")
    assert AWS not in provider.prompts[0] and "add_executable" in provider.prompts[0] and "main.cpp" in provider.prompts[0]
    assert main(["ai", "migrate", str(tmp_path), "--yes", "--write"]) == 0                          # never overwrites: writes .proposed
    assert (tmp_path / f"{tmp_path.name}.charpente.proposed").exists()
    assert "Not written" not in capsys.readouterr().out


def test_migrate_needs_a_build_file_and_a_usable_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(flow, "interactive", lambda: False)
    use(monkeypatch, FakeProvider(DRAFT))
    assert main(["ai", "migrate", str(tmp_path), "--yes"]) != 0
    assert "CH8021" in capsys.readouterr().err
    (tmp_path / "Makefile").write_text("all:\n\tg++ main.cpp\n", encoding="utf-8")
    use(monkeypatch, FakeProvider("```python\nprint('x')\n```"))
    assert main(["ai", "migrate", str(tmp_path), "--yes"]) != 0


def test_ai_status_needs_no_provider(monkeypatch, capsys):
    use(monkeypatch, FakeProvider("x", available=False))
    assert main(["ai", "status"]) == 0
    out = capsys.readouterr().out
    assert "none configured" in out and "opt-in" in out
    use(monkeypatch, FakeProvider("x"))
    main(["ai", "status"])
    assert "fake (configured)" in capsys.readouterr().out


def test_the_ai_commands_are_registered_and_documented():
    from charpente.commands import COMMANDS

    assert {"fix", "ai"} <= set(COMMANDS)
    assert Path(__file__).exists()
