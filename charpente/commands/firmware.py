"""`charpente size` and `charpente flash` -- firmware targets (Kind.FIRMWARE) on microcontrollers."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import List, Tuple

from .. import embedded
from ..builder import build_dir, build_workspace, dependency_closure
from ..core import process
from ..dsl.model import Kind, Target, Workspace
from ..errors import ChError
from ..flags import output_filename
from ..toolchains import Toolchain
from ._common import CommandError, load, resolve_target, toolchain_for
from ._session import Session, add_engine_args


def _parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--target", help="Firmware target (default: the only one, if unambiguous)")
    parser.add_argument("--config", default="Release", choices=["Debug", "Release"])
    add_engine_args(parser, output=False)
    return parser


def _firmware(parsed: argparse.Namespace) -> Tuple[Workspace, Target, Toolchain, Path]:
    if not parsed.platform:
        raise ChError("CH8006", platform="embedded", detail="give the microcontroller with --platform (e.g. cortexm4-arm)")
    workspace = load(parsed.file, parsed.opt)
    target = resolve_target(workspace, parsed.target)
    if target.kind != Kind.FIRMWARE:
        raise ChError("CH8006", platform="embedded",
                      detail=f"target {target.name!r} is a {target.kind.value}, not Kind.FIRMWARE")
    target_os, toolchain = toolchain_for(parsed, workspace)
    with Session("build", parsed, workspace, toolchain=toolchain.name, config=parsed.config) as session:
        result = build_workspace(workspace, toolchain, target_os, config=parsed.config,
                                 only=dependency_closure(workspace, target.name), jobs=parsed.jobs,
                                 bus=session.bus, use_cache=not parsed.no_cache, eco=getattr(parsed, "eco", False))
        session.flush()
        built = result.target(target.name)
        ok = built is not None and built.ok
        session.finish(ok, 0 if ok else 1)
    if result.interrupted:
        raise KeyboardInterrupt
    if not ok:
        raise CommandError("CH4001", detail=built.error if built else "unknown target build failure")
    return workspace, target, toolchain, build_dir(workspace, parsed.config, target, toolchain) / output_filename(
        target, target_os, toolchain)


def execute_size(args: List[str]) -> int:
    parsed = _parser("charpente size", "Build a firmware target and report its flash and RAM use.").parse_args(args)
    workspace, target, _toolchain, elf = _firmware(parsed)
    settings = embedded.settings_from(target.name, target.platform_settings.get("embedded", {}))
    regions = {}
    if settings.linker_script and (workspace.root / settings.linker_script).is_file():
        regions = embedded.memory_regions((workspace.root / settings.linker_script).read_text(encoding="utf-8"))
    print(embedded.size_report(embedded.elf_sizes(elf), regions))
    return 0


def execute_flash(args: List[str]) -> int:
    parser = _parser("charpente flash", "Build a firmware target and program the board.")
    parser.add_argument("--tool", choices=embedded.FLASH_TOOLS, help="Flashing tool (default: the target's `flash` setting)")
    parser.add_argument("--dry-run", action="store_true", help="Print the command instead of running it")
    parsed = parser.parse_args(args)
    _workspace, target, _toolchain, elf = _firmware(parsed)
    settings = embedded.settings_from(target.name, target.platform_settings.get("embedded", {}))
    tool = parsed.tool or settings.flash
    if not tool:
        raise ChError("CH8006", platform="embedded",
                      detail='say how to flash: platform_settings("embedded", flash="openocd", flash_args=[...]) or --tool')
    image = elf.with_suffix(".hex" if tool == "avrdude" else ".bin")
    argv = embedded.flash_argv(tool, elf, settings.flash_args, image=image)
    if parsed.dry_run:
        print(" ".join(argv))
        return 0
    if not shutil.which(argv[0]):
        raise ChError("CH8007", what=argv[0], hint="install it and put it on PATH")
    print(f"Flashing with {tool} ...")
    return process.run(argv, capture=False).returncode
