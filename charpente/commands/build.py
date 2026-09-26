from __future__ import annotations

import argparse
import sys
from typing import List

from ..builder import BuildResult, build_workspace
from ..ui import render as ui_render
from ._common import load, toolchain_for
from ._session import Session, add_engine_args


def print_result_lines(session: Session, result: BuildResult, *, ai_diagnose: bool = False,
                       toolchain_name: str = "") -> None:
    """The per-target lines shown after a build (unchanged since v0.1.0), then a one-line summary.

    With the styled display (`session.fancy`) the renderer has already shown every target and will show the summary box, so only the AI diagnosis (asked for
    explicitly) is printed here.
    """
    session.flush()
    if session.machine:
        return
    if session.fancy:
        if result.interrupted:                               # the engine handled Ctrl+C itself (no exception reached the session): tell the display
            session.bus.emit("session.interrupted", reason="keyboard")
        if ai_diagnose:
            for t in result.targets:
                if not (t.skipped or t.ok):
                    _print_ai_diagnosis(t.target_name, toolchain_name, t.error)
        return
    for t in result.targets:
        if t.skipped:
            print(f"  [up to date] {t.target_name}")
        elif t.ok:
            print(f"  [ok]         {t.target_name} -> {t.output_path}")
        else:
            print(f"  [FAILED]     {t.target_name}: {t.error}")
            if ai_diagnose:
                _print_ai_diagnosis(t.target_name, toolchain_name, t.error)
    counts = {"executed": 0, "cached": 0, "up_to_date": 0}
    for t in result.targets:
        counts["executed"] += t.executed
        counts["cached"] += t.cached
        counts["up_to_date"] += t.up_to_date
    if result.interrupted:
        print("Build interrupted.")
    elif any(counts.values()):
        print(f"Done in {result.duration:.1f}s: {counts['executed']} run, {counts['cached']} from cache, "
              f"{counts['up_to_date']} up to date.")


def _styled(parsed: argparse.Namespace) -> bool:
    """Whether this run will use the styled display (only then is the tool's version worth asking for)."""
    return getattr(parsed, "output", "plain") == "auto" and not getattr(parsed, "verbose", False) and ui_render.styled_wanted()


def check_budgets(session: Session, workspace: object, result: BuildResult) -> int:
    """Print and emit the budget findings of a finished build; 1 when any is exceeded, else 0."""
    from .. import budgets

    outputs = {t.target_name: t.output_path for t in result.targets if t.output_path is not None}
    findings = budgets.evaluate(workspace, outputs, result.duration)  # type: ignore[arg-type]
    exceeded = 0
    for finding in findings:
        kind = "budget.checked" if finding.ok else "budget.exceeded"
        session.bus.emit(kind, scope=finding.scope, kind=finding.kind, limit=float(finding.limit), actual=float(finding.actual))
        if not finding.ok:
            exceeded += 1
        if not session.machine:
            print(f"  [{'budget ok' if finding.ok else 'OVER BUDGET'}] {finding.describe()}")
    session.flush()
    if not session.machine:
        for name, target in workspace.targets.items():  # type: ignore[attr-defined]
            if "size" in target.budgets and name not in outputs:
                print(f"  [budget skipped] {name}: its size budget was not checked: the target produced no output file to measure in this run", file=sys.stderr)
    if exceeded and not session.machine:
        from ..errors import ChError

        print(f"charpente: [CH8024] {ChError('CH8024', detail=f'{exceeded} budget(s) over their limit').message}", file=sys.stderr)
    return 1 if exceeded else 0


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente build", description="Compile the workspace.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--keep-going", action="store_true",
                        help="Keep building unrelated targets after a failure")
    parser.add_argument("--no-budget", action="store_true", help="Do not check the budgets declared with ws.budget()/t.budget()")
    parser.add_argument("--ai-diagnose", action="store_true",
                        help="On failure, ask the configured AI provider to diagnose the error "
                             "(never automatic: costs a request and sends the error text to "
                             "whichever provider is configured)")
    add_engine_args(parser)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file, parsed.opt)
    target_os, toolchain = toolchain_for(parsed, workspace)

    with Session("build", parsed, workspace, toolchain=toolchain.name, config=parsed.config,
                 tools=ui_render.resolve_tool_label(toolchain) if _styled(parsed) else "") as session:
        if not session.fancy:
            session.say(f"Building {workspace.name} ({parsed.config}, {toolchain.name})...")
        result = build_workspace(workspace, toolchain, target_os, config=parsed.config,
                                 keep_going=parsed.keep_going, jobs=parsed.jobs, bus=session.bus,
                                 use_cache=not parsed.no_cache, eco=parsed.eco)
        print_result_lines(session, result, ai_diagnose=parsed.ai_diagnose, toolchain_name=toolchain.name)
        code = 130 if result.interrupted else (0 if result.ok else 1)
        if result.ok and not parsed.no_budget:
            code = check_budgets(session, workspace, result) or code
        session.finish(code == 0, code)
    return code


def _print_ai_diagnosis(target_name: str, toolchain_name: str, error_text: str) -> None:
    from ..ai import diagnose, select_provider

    provider = select_provider()
    print(f"               (asking {provider.name} to diagnose...)")
    print("               " + diagnose(
        provider, target_name=target_name, toolchain_name=toolchain_name, error_text=error_text
    ).replace("\n", "\n               "))
