"""`charpente ai status | tests | migrate` -- optional AI helpers. Each shows what it sends, asks first, and checks what comes back."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ..ai import flow, migrate, testgen
from ..ai.provider import select_provider
from ..builder import build_workspace, dependency_closure
from ..core import process
from ..dsl.model import Kind
from ..errors import ChError
from ._common import CommandError, find_root, load, program_argv, toolchain_for
from ._session import add_engine_args


def _add_privacy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--show-context", action="store_true", help="Print exactly what would be sent, and ask before sending it")
    parser.add_argument("--dry-run", action="store_true", help="Print exactly what would be sent, and send nothing")
    parser.add_argument("--yes", action="store_true", help="Agree in advance to send the context shown (needed when not interactive)")


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente ai", description="Optional AI helpers (never automatic).")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="Which provider is configured, and what is (and is not) ever sent")
    tests = sub.add_parser("tests", help="Write unit tests for a target; proposed only if they compile and pass")
    tests.add_argument("target")
    tests.add_argument("--file", help="Path to the .charpente workspace file")
    tests.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    tests.add_argument("--attempts", type=int, default=3, help="How many times the assistant may fix its own test (default 3)")
    tests.add_argument("--write", action="store_true", help="Write the passing test to tests/<target>_ai_test.cpp")
    tests.add_argument("--out", help="Where to write it instead")
    tests.add_argument("--force", action="store_true", help="Overwrite the destination if it exists")
    _add_privacy_args(tests)
    add_engine_args(tests, output=False)
    mig = sub.add_parser("migrate", help="Draft a .charpente file from CMakeLists.txt or a Makefile (checked, never executed)")
    mig.add_argument("folder", nargs="?", default=".")
    mig.add_argument("--write", action="store_true", help="Write the draft as NAME.charpente (or NAME.charpente.proposed when it exists)")
    _add_privacy_args(mig)
    parsed = parser.parse_args(args)

    if parsed.action == "status":
        return _status()
    if parsed.action == "tests":
        return _tests(parsed)
    return _migrate(parsed)


def _status() -> int:
    provider = select_provider()
    if provider.is_available():
        print(f"AI provider: {provider.name} (configured). Nothing is sent unless you run an AI command and agree.")
    else:
        print("AI provider: none configured. Everything else in Charpente works without one.")
        print("  To enable: set ANTHROPIC_API_KEY or OPENAI_API_KEY, or CHARPENTE_AI_URL for a local OpenAI-compatible server.")
    print("Rules: opt-in per command; the context is shown first (`--show-context`, `--dry-run`); probable secrets are replaced before sending;\n"
          "a proposed change is a diff you approve, checked against your files, and the quality gate runs after it.")
    return 0


def _confirm(context: object, provider: object, parsed: argparse.Namespace) -> bool:
    try:
        return flow.review_and_confirm(context, provider, show_full=parsed.show_context, assume_yes=parsed.yes, dry_run=parsed.dry_run)  # type: ignore[arg-type]
    except flow.NotConfirmed as exc:
        raise CommandError("CH8022", reason=str(exc)) from exc


def _tests(parsed: argparse.Namespace) -> int:
    workspace = load(parsed.file, parsed.opt)
    if parsed.target not in workspace.targets or workspace.targets[parsed.target].external:
        raise CommandError("CH1008", name=parsed.target, workspace=workspace.name,
                           known=", ".join(sorted(n for n, t in workspace.targets.items() if not t.external)) or "(none)")
    base = workspace.targets[parsed.target]
    if base.kind == Kind.TEST:
        raise CommandError("CH8021", reason=f"{base.name} is itself a test target")
    provider = select_provider()
    flow.require_provider(provider)
    root = Path(workspace.location or find_root())
    context = testgen.context_for(root, workspace, base, 12000)
    if not _confirm(context, provider, parsed):
        return 0
    target_os, toolchain = toolchain_for(parsed, workspace)
    scratch = root / "build" / "ai-tests"
    scratch.mkdir(parents=True, exist_ok=True)
    source = scratch / f"{base.name}_ai_test.cpp"
    code, failure = "", ""
    for attempt in range(1, max(parsed.attempts, 1) + 1):
        print(f"(attempt {attempt}: asking {provider.name}...)")
        code = testgen.request_tests(provider, context, previous_code=code if failure else "", failure=failure)
        if not code.strip():
            failure = "the answer contained no C++ code"
            print(f"  {failure}")
            continue
        source.write_text(code, encoding="utf-8")
        try:
            workspace = load(parsed.file, parsed.opt)                 # a fresh model each time: the test target is added in memory only
            target = testgen.ephemeral_target(workspace, workspace.targets[base.name], source)
            built = build_workspace(workspace, toolchain, target_os, config=parsed.config, only=dependency_closure(workspace, target.name), keep_going=True,
                                    jobs=parsed.jobs, use_cache=False)
        except ChError as exc:
            failure = f"the test could not be built: {exc.message}"
            print(f"  {failure}")
            continue
        result = built.target(target.name)
        if result is None or not result.ok or result.output_path is None:
            failure = (result.error if result else "build failed") or "build failed"
            print("  it does not compile; sending the compiler output back")
            continue
        ran = process.run(program_argv(toolchain, result.output_path), timeout=120)
        if ran.returncode != 0:
            failure = f"the test program exited with code {ran.returncode}\n{ran.output}"
            print(f"  it compiles but fails (exit {ran.returncode}); sending the output back")
            continue
        print(f"The test compiles and passes ({attempt} attempt(s)).")
        break
    else:
        print("No attempt produced a test that compiles and passes, so none is proposed.")
        print(failure[-800:])
        return 1
    print("--- proposed test ---")
    print(code, end="")
    print("--- end ---")
    destination = Path(parsed.out) if parsed.out else testgen.suggested_path(root, base)
    assert destination is not None
    if not parsed.write:
        print(f"Not written. Re-run with --write to save it as {destination}.")
        return 0
    if destination.exists() and not parsed.force:
        raise CommandError("CH8021", reason=f"{destination} already exists (use --force to overwrite it)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(code, encoding="utf-8")
    print(f"Wrote {destination}. Add it to a Kind.TEST target (a `tests/*.cpp` glob picks it up) and run `charpente test`.")
    return 0


def _migrate(parsed: argparse.Namespace) -> int:
    folder = Path(parsed.folder).resolve()
    build_file = migrate.find_build_file(folder)
    if build_file is None:
        raise CommandError("CH8021", reason=f"no CMakeLists.txt or Makefile in {folder}")
    provider = select_provider()
    flow.require_provider(provider)
    context = migrate.context_for(folder, build_file, 20000)
    if not _confirm(context, provider, parsed):
        return 0
    print(f"(asking {provider.name}...)")
    draft = migrate.request(provider, context)
    if not draft:
        raise CommandError("CH8021", reason="the assistant did not return a .charpente file")
    usable, problems = migrate.check(draft)
    print("--- proposed .charpente (not executed) ---")
    print(draft, end="")
    print("--- end ---")
    for problem in problems:
        print(f"  {problem}")
    if not usable:
        raise CommandError("CH8021", reason="the draft does not pass the checks above")
    name = folder.name or "project"
    target = folder / f"{name}.charpente"
    if not parsed.write:
        print(f"Not written. Re-run with --write to save it as {target.name}.")
        return 0
    if target.exists():
        target = folder / f"{name}.charpente.proposed"
    target.write_text(draft, encoding="utf-8")
    print(f"Wrote {target}. Read it, adjust it, then run `charpente lint` on it.")
    return 0
