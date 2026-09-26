"""Git and GitHub integration: the Git wrapper (real repositories), hooks, commit rules, PR bodies, the commands."""
import io
import json
import shutil
import subprocess
import urllib.error

import pytest

from charpente.core import process
from charpente.errors import ChError
from charpente.quality import gate
from charpente.vcs import git as git_mod
from charpente.vcs import hooks as hooks_mod
from charpente.vcs import pr as pr_mod

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def sh(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t.t", "-c", "user.name=Tester", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    sh(root, "init", "-q", "-b", "main")
    sh(root, "config", "core.autocrlf", "false")
    (root / "a.txt").write_text("one\n")
    sh(root, "add", "a.txt")
    sh(root, "commit", "-qm", "chore: init")
    return root


# ------------------------------------------------------------------ messages
@pytest.mark.parametrize("message", [
    "feat: add cross compilation", "fix(engine): reset the stat cache", "docs!: rewrite the guide",
    "refactor(core/graph): split", "chore: x\n\nlonger body"])
def test_conventional_commits_are_accepted(message):
    assert git_mod.check_message(message) is None


@pytest.mark.parametrize("message", ["", "updated stuff", "Feat: caps", "feat:no space", "feat(): empty scope", "wip"])
def test_other_messages_are_explained(message):
    problem = git_mod.check_message(message)
    assert problem and ("empty" in problem or "Conventional Commit" in problem)


def test_message_drafts_follow_what_changed():
    assert git_mod.propose_message(["docs/a.md", "README.md"]).startswith("docs")
    assert git_mod.propose_message(["tests/test_x.py"]).startswith("test")
    assert git_mod.propose_message([".github/workflows/ci.yml"]).startswith("ci")
    assert git_mod.propose_message(["pyproject.toml"]).startswith("build")
    assert git_mod.propose_message(["charpente/engine.py"]) == "feat(charpente): update charpente/engine.py"
    assert git_mod.propose_message(["a/x.py", "b/y.py"]) == "feat: update 2 files"
    assert git_mod.propose_message([]) == "chore: update"
    for files in (["docs/a.md"], ["src/a.cpp", "src/b.cpp"], ["x.py"]):
        assert git_mod.check_message(git_mod.propose_message(files)) is None      # a draft is always valid


def test_github_remote_urls():
    for url in ("https://github.com/acme/tool.git", "git@github.com:acme/tool.git", "https://github.com/acme/tool",
                "https://user@github.com/acme/tool.git", "ssh://git@github.com/acme/tool.git"):
        assert git_mod.parse_remote(url) == ("acme", "tool")
    assert git_mod.parse_remote("https://gitlab.com/acme/tool.git") is None and git_mod.parse_remote("/local/path") is None


# ------------------------------------------------------------------ the wrapper on a real repository
@needs_git
def test_status_reflects_staged_modified_untracked_and_branch(repo):
    g = git_mod.Git(repo)
    assert g.is_repo() and g.branch() == "main" and g.status().clean
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("b\n")
    (repo / "c.txt").write_text("c\n")
    sh(repo, "add", "b.txt")
    status = g.status()
    assert status.staged == ("b.txt",) and status.modified == ("a.txt",) and status.untracked == ("c.txt",)
    assert not status.clean and status.upstream == "" and status.branch == "main"
    assert g.staged_files() == ["b.txt"] and "b.txt" in g.staged_diff(stat=True)


@needs_git
def test_commit_log_trees_and_no_repo_errors(repo, tmp_path):
    g = git_mod.Git(repo)
    (repo / "a.txt").write_text("two\n")
    g.add_all_tracked()
    sha = g.commit("fix: change a")
    commits = g.log("HEAD~1..HEAD")
    assert [c.subject for c in commits] == ["fix: change a"] and commits[0].sha == sha and commits[0].tree == g.tree_of("HEAD")
    assert g.head() == sha and g.tree_of("nonexistent") is None
    outside = git_mod.Git(tmp_path)
    assert not outside.is_repo()
    with pytest.raises(ChError) as exc:
        outside.require_repo()
    assert exc.value.code == "CH8013"
    with pytest.raises(ChError):
        g.commit("fix: nothing to commit")


@needs_git
def test_upstream_ahead_behind_and_default_base(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    sh(repo, "remote", "add", "origin", str(remote))
    g = git_mod.Git(repo)
    g.push("origin", "main", set_upstream=True)
    (repo / "a.txt").write_text("three\n")
    g.add_all_tracked()
    g.commit("feat: local only")
    status = g.status()
    assert status.upstream == "origin/main" and status.ahead == 1 and status.behind == 0
    assert g.default_base() == "main" and g.remote_url() == str(remote)
    assert g.latest_tag() is None
    g.tag("v0.1.0", "first")
    assert g.latest_tag() == "v0.1.0"


def test_a_missing_git_is_reported_with_advice(tmp_path):
    with pytest.raises(ChError) as exc:
        git_mod.Git(tmp_path, which=lambda n: None).is_repo()
    assert exc.value.code == "CH8007" and "git" in str(exc.value)


# ------------------------------------------------------------------ hooks
@needs_git
def test_hooks_install_update_and_uninstall(repo):
    hooks = git_mod.Git(repo).hooks_dir()
    assert not any(s.installed for s in hooks_mod.state(hooks))
    assert dict(hooks_mod.install(hooks)) == {"pre-commit": "installed", "pre-push": "installed"}
    text = (hooks / "pre-commit").read_text()
    assert text.startswith("#!/bin/sh\n") and hooks_mod.MARKER in text and "check --level rapide --changed --hook pre-commit" in text
    assert "--level standard" in (hooks / "pre-push").read_text()
    assert dict(hooks_mod.install(hooks))["pre-commit"] == "updated"
    assert all(v.startswith("removed") for v in dict(hooks_mod.uninstall(hooks)).values())
    assert not (hooks / "pre-commit").exists()


@needs_git
def test_a_foreign_hook_is_never_overwritten_without_force(repo):
    hooks = git_mod.Git(repo).hooks_dir()
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(ChError) as exc:
        hooks_mod.install(hooks)
    assert "not written by Charpente" in str(exc.value) and (hooks / "pre-commit").read_text().endswith("mine\n")
    hooks_mod.install(hooks, force=True)
    assert hooks_mod.MARKER in (hooks / "pre-commit").read_text() and (hooks / "pre-commit.pre-charpente").is_file()
    assert dict(hooks_mod.uninstall(hooks))["pre-commit"].endswith("restored")
    assert (hooks / "pre-commit").read_text().endswith("mine\n")
    assert dict(hooks_mod.uninstall(hooks))["pre-commit"].startswith("not managed")


@needs_git
def test_the_installed_hook_really_blocks_a_commit_that_fails_the_gate(repo):
    sh(repo, "config", "core.hooksPath", str(repo / ".git" / "hooks"))
    hooks = git_mod.Git(repo).hooks_dir()
    hooks_mod.install(hooks)
    # a hook that always fails, standing in for `charpente check` finding a problem
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (repo / "a.txt").write_text("changed\n")
    sh(repo, "add", "a.txt")
    blocked = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t.t", "-c", "user.name=T", "commit", "-m", "x: y"],
                             capture_output=True, text=True)
    assert blocked.returncode != 0
    ok = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t.t", "-c", "user.name=T", "commit", "--no-verify", "-m", "x: y"],
                        capture_output=True, text=True)
    assert ok.returncode == 0                                            # Git allows it: which is why PRs flag such commits


# ------------------------------------------------------------------ pull requests
def commits(*subjects):
    return [git_mod.Commit(f"{i + 1:07x}".ljust(40, "0"), s, "", f"tree{i}") for i, s in enumerate(subjects)]


def test_pr_body_reports_the_gate_and_flags_unverified_commits():
    record = {"level": "standard", "ok": True, "when": "2026-09-26T10:00:00",
              "results": [{"check": "build", "status": "passed", "message": "built"},
                          {"check": "clang-tidy", "status": "skipped", "message": "clang-tidy not found"}]}
    cs = commits("feat: a", "fix: b")
    body = pr_mod.build_body(cs, record, {"tree0": {"level": "rapide"}})
    assert "## Summary" in body and "2 commits: feat: a; fix: b" in body
    assert "- `0000001` feat: a" in body and "passed" in body and "skipped: clang-tidy" in body
    assert "1 commit(s) have no passing quality-gate record" in body and "> - `0000002` fix: b" in body
    assert "--no-verify" in body
    clean = pr_mod.build_body(cs, record, {"tree0": {}, "tree1": {}})
    assert "Warning" not in clean
    assert "`charpente check` was not run" in pr_mod.build_body(cs, None, {})


def test_pr_body_lists_sbom_components_and_uses_a_given_summary():
    body = pr_mod.build_body(commits("feat: a"), None, {}, [("fmt", "10.2.1", "MIT")], summary="Adds fmt.")
    assert "Adds fmt." in body and "- fmt 10.2.1 (MIT)" in body and "<details>" in body
    assert "- none" in pr_mod.build_body(commits("feat: a"), None, {}, [])
    assert pr_mod.title_for(commits("feat: a"), "topic") == "feat: a"
    assert pr_mod.title_for(commits("feat: a", "fix: b"), "topic") == "fix: b"
    assert pr_mod.title_for([], "topic") == "topic"


def test_token_comes_from_the_environment_or_keyring_never_a_file():
    assert pr_mod.token({"GH_TOKEN": "a", "GITHUB_TOKEN": "b"}) == "a"
    assert pr_mod.token({"GITHUB_TOKEN": "b"}) == "b"

    class Ring:
        def get_password(self, service, user):
            assert (service, user) == ("charpente-github", "token")
            return "from-ring"

    class Broken:
        def get_password(self, *a):
            raise RuntimeError("no backend")

    assert pr_mod.token({}, Ring()) == "from-ring" and pr_mod.token({}, Broken()) is None


def test_gh_is_used_when_installed_and_its_failure_is_reported():
    seen = {}

    def run(argv, **kw):
        seen["argv"], seen["input"] = list(argv), kw.get("input")
        return process.ProcessResult(tuple(argv), 0, "Creating pull request\nhttps://github.com/acme/tool/pull/7\n", "")

    url = pr_mod.open_with_gh("t", "the body", "main", "topic", draft=True, run=run, which=lambda n: "/bin/gh")
    assert url == "https://github.com/acme/tool/pull/7" and seen["input"] == "the body"
    assert seen["argv"][:3] == ["/bin/gh", "pr", "create"] and "--draft" in seen["argv"] and "--body-file" in seen["argv"]
    assert pr_mod.open_with_gh("t", "b", "main", "topic", which=lambda n: None) is None
    with pytest.raises(ChError) as exc:
        pr_mod.open_with_gh("t", "b", "main", "topic", which=lambda n: "/bin/gh",
                            run=lambda argv, **kw: process.ProcessResult(tuple(argv), 1, "", "not logged in"))
    assert exc.value.code == "CH8015" and "not logged in" in str(exc.value)


def test_the_api_fallback_posts_json_with_a_bearer_token():
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout=0):
        captured["url"], captured["auth"] = request.full_url, request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        return Response(b'{"html_url": "https://github.com/acme/tool/pull/9"}')

    url = pr_mod.open_with_api("git@github.com:acme/tool.git", "T", "B", "main", "topic", auth="tok", opener=opener)
    assert url.endswith("/pull/9") and captured["url"] == "https://api.github.com/repos/acme/tool/pulls"
    assert captured["auth"] == "Bearer tok" and captured["body"] == {"title": "T", "body": "B", "base": "main", "head": "topic", "draft": False}
    with pytest.raises(ChError) as exc:
        pr_mod.open_with_api("git@github.com:acme/tool.git", "T", "B", "main", "topic", auth=None)
    assert "no GitHub token" in str(exc.value)
    with pytest.raises(ChError):
        pr_mod.open_with_api("https://gitlab.com/a/b.git", "T", "B", "main", "topic", auth="x")

    def denied(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 422, "Unprocessable", {}, io.BytesIO(b'{"message":"already exists"}'))

    with pytest.raises(ChError) as exc:
        pr_mod.open_with_api("git@github.com:acme/tool.git", "T", "B", "main", "topic", auth="tok", opener=denied)
    assert "422" in str(exc.value) and "already exists" in str(exc.value)


# ------------------------------------------------------------------ the commands (real repository, minimal gate)
def quiet_gate(root):
    """Only the checks that need no build or tool, so command tests exercise the wiring and stay fast."""
    (root / ".charpente").mkdir(exist_ok=True)
    disabled = "".join(f"[checks.{n}]\nenabled = false\n" for n in (
        "build", "format", "dsl-lint", "warnings", "clang-tidy", "cppcheck", "tests", "sanitizers", "coverage", "platforms",
        "audit", "licenses", "sbom"))
    (root / ".charpente" / "quality.toml").write_text(disabled)


@needs_git
def test_commit_runs_the_gate_then_commits_and_remembers_the_tree(repo, monkeypatch, capsys):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")
    (repo / "a.txt").write_text("two\n")
    assert vcs.execute_commit(["-a", "-m", "fix: change a"]) == 0
    out = capsys.readouterr().out
    assert "Quality gate (rapide, changed files only)" in out and "Committed" in out
    g = git_mod.Git(repo)
    assert g.log("HEAD~1..HEAD")[0].subject == "fix: change a"
    assert g.tree_of("HEAD") in gate.read_log(repo)                         # this tree passed the gate


@needs_git
def test_commit_is_blocked_by_a_failing_gate_and_by_a_bad_message(repo, monkeypatch):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    (repo / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    sh(repo, "add", "leak.txt")
    before = git_mod.Git(repo).head()
    with pytest.raises(ChError) as exc:
        vcs.execute_commit(["-m", "feat: leak"])
    assert exc.value.code == "CH8014" and "secrets" in str(exc.value)
    assert git_mod.Git(repo).head() == before                               # nothing was committed
    (repo / "leak.txt").write_text("harmless\n")
    sh(repo, "add", "leak.txt")
    with pytest.raises(ChError) as exc:
        vcs.execute_commit(["-m", "updated things"])
    assert "Conventional Commit" in str(exc.value)
    assert git_mod.Git(repo).head() == before


@needs_git
def test_commit_without_a_message_needs_an_interactive_session(repo, monkeypatch):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    (repo / "b.txt").write_text("b\n")
    sh(repo, "add", "b.txt")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(ChError) as exc:
        vcs.execute_commit([])
    assert "draft would be" in str(exc.value) and "feat" in str(exc.value)


@needs_git
def test_no_verify_skips_the_gate_and_says_so(repo, monkeypatch, capsys):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")
    (repo / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    sh(repo, "add", "leak.txt")
    assert vcs.execute_commit(["--no-verify", "-m", "feat: leak"]) == 0
    err = capsys.readouterr().err
    assert "gate is skipped" in err and "flagged in pull requests" in err
    tree = git_mod.Git(repo).tree_of("HEAD")
    assert tree not in gate.read_log(repo)                                  # so a PR will warn about this commit
    assert json.loads((repo / "build" / ".charpente" / "no-verify.json").read_text())


@needs_git
def test_push_runs_the_gate_and_pushes_to_a_local_remote(repo, tmp_path, monkeypatch, capsys):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    sh(repo, "remote", "add", "origin", str(remote))
    assert vcs.execute_push([]) == 0
    assert "Pushed main to origin" in capsys.readouterr().out
    assert sh(repo, "rev-parse", "origin/main") == git_mod.Git(repo).head()
    (repo / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE\n")
    sh(repo, "add", "leak.txt")
    sh(repo, "commit", "-qm", "feat: leak")
    with pytest.raises(ChError) as exc:
        vcs.execute_push([])
    assert exc.value.code == "CH8014"
    assert sh(repo, "rev-parse", "origin/main") != git_mod.Git(repo).head()      # the bad commit did not leave the machine


@needs_git
def test_a_forced_push_needs_typed_confirmation(repo, tmp_path, monkeypatch):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    sh(repo, "remote", "add", "origin", str(remote))
    with pytest.raises(ChError) as exc:
        vcs.execute_push(["--force-with-lease"])                           # stdin is not a terminal under pytest
    assert "interactive confirmation" in str(exc.value)
    assert subprocess.run(["git", "-C", str(remote), "rev-parse", "main"], capture_output=True).returncode != 0   # nothing pushed


@needs_git
def test_pr_dry_run_prints_the_description_and_refuses_on_the_base_branch(repo, monkeypatch, capsys):
    from charpente.commands import vcs

    quiet_gate(repo)
    monkeypatch.chdir(repo)
    with pytest.raises(ChError) as exc:
        vcs.execute_pr(["--dry-run"])
    assert "base branch" in str(exc.value)
    sh(repo, "checkout", "-qb", "topic")
    (repo / "b.txt").write_text("b\n")
    sh(repo, "add", "b.txt")
    sh(repo, "commit", "-qm", "feat: b")
    assert vcs.execute_pr(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Title: feat: b" in out and "Base:  main   Head: topic" in out and "## Quality gate" in out
    assert "no passing quality-gate record" in out                          # committed outside Charpente


@needs_git
def test_status_command_json_and_text(repo, monkeypatch, capsys):
    from charpente.commands import vcs

    monkeypatch.chdir(repo)
    (repo / "x.txt").write_text("x\n")
    assert vcs.execute_status(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["branch"] == "main" and data["untracked"] == ["x.txt"] and data["gate"] is None
    assert vcs.execute_status([]) == 0
    text = capsys.readouterr().out
    assert "Git:    main" in text and "1 untracked" in text and "`charpente check` has not been run" in text


@needs_git
def test_hooks_command(repo, monkeypatch, capsys):
    from charpente.commands import vcs

    monkeypatch.chdir(repo)
    assert vcs.execute_hooks(["install"]) == 0 and "pre-commit: installed" in capsys.readouterr().out
    assert vcs.execute_hooks(["status"]) == 0 and "installed (Charpente)" in capsys.readouterr().out
    assert vcs.execute_hooks(["uninstall"]) == 0 and "removed" in capsys.readouterr().out
