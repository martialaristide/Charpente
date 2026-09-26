"""`charpente fix` -- ask the configured AI for a fix to a failing build, as a diff you approve. Never automatic, never applied without your agreement."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple

from ..ai import flow
from ..ai import patch as patch_mod
from ..ai.context import error_context
from ..ai.fix import Proposal, apply_verified, request_fix
from ..ai.provider import select_provider
from ..builder import build_workspace
from ..errors import ChError
from ..quality import gate
from ._common import CommandError, find_root, load, toolchain_for
from ._session import add_engine_args


def build_errors(parsed: argparse.Namespace, workspace: object) -> Tuple[bool, str]:
    """Build everything; (ok, the error text of the targets that failed)."""
    target_os, toolchain = toolchain_for(parsed, workspace)  # type: ignore[arg-type]
    result = build_workspace(workspace, toolchain, target_os, config=parsed.config, keep_going=True, jobs=parsed.jobs, use_cache=not parsed.no_cache)  # type: ignore[arg-type]
    if result.ok:
        return True, ""
    return False, "\n\n".join(f"[{t.target_name}] {t.error}" for t in result.targets if not t.ok and t.error)


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente fix", description="Propose a fix for a failing build with the configured AI provider.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Debug", choices=["Debug", "Release"])
    parser.add_argument("--show-context", action="store_true", help="Print exactly what would be sent, and ask before sending it")
    parser.add_argument("--dry-run", action="store_true", help="Print exactly what would be sent, and send nothing")
    parser.add_argument("--yes", action="store_true", help="Agree in advance to send the context shown (needed when not interactive)")
    parser.add_argument("--apply", action="store_true", help="Apply the proposed diff (after showing it), rebuild, and run the quality gate")
    add_engine_args(parser, output=False)
    parsed = parser.parse_args(args)

    workspace = load(parsed.file, parsed.opt)
    ok, errors = build_errors(parsed, workspace)
    if ok:
        print("Nothing to fix: the build succeeds.")
        return 0
    provider = select_provider()
    flow.require_provider(provider)
    root = Path(workspace.location or find_root())
    context = error_context(root, workspace, errors)
    try:
        send = flow.review_and_confirm(context, provider, show_full=parsed.show_context, assume_yes=parsed.yes, dry_run=parsed.dry_run)
    except flow.NotConfirmed as exc:
        raise CommandError("CH8022", reason=str(exc)) from exc
    if not send:
        return 0
    print(f"(asking {provider.name}...)")
    try:
        proposal = request_fix(provider, context, root)
    except patch_mod.PatchError as exc:
        raise CommandError("CH8021", reason=str(exc)) from exc
    show(root, proposal)
    if not parsed.apply:
        if flow.interactive() and flow.ask_yes_no("Apply this change, rebuild and run the quality gate?", False):
            parsed.apply = True
        else:
            print("Not applied. Re-run with --apply to apply it (the files are restored if the build still fails).")
            return 0

    def verify() -> Tuple[bool, str]:
        again = load(parsed.file, parsed.opt)
        return build_errors(parsed, again)

    kept, output = apply_verified(root, proposal, verify)
    if not kept:
        print("The build still fails with this change, so it was reverted. Your files are as they were.")
        print(output[-1500:])
        return 1
    print("Applied: the build succeeds. Running the quality gate...")
    return run_gate(root)


def show(root: Path, proposal: Proposal) -> None:
    if proposal.explanation:
        print(proposal.explanation)
    print("--- proposed change ---")
    print(patch_mod.unified(root, proposal.contents), end="")
    print("--- end ---")


def run_gate(root: Path) -> int:
    try:
        result = gate.run_gate(root, level="rapide", say=print)
    except ChError as exc:
        print(f"charpente: the quality gate could not run: {exc.message}")
        return 1
    print(gate.render(result))
    return 0 if result.ok else 1
