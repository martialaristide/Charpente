"""`charpente setup`: what to do on a fresh machine, as a list of steps computed from `charpente doctor`'s report.

`steps(report)` is a pure function: given what the machine has, it returns what would help. A step either has a `command` (a Charpente command Charpente can run for you after asking)
or is only advice (installing git or a debugger is your system's business, and Charpente never runs an installer it does not own). Downloads are never started without a yes
(`--yes` counts as one), and vendor licences are never accepted on your behalf: a step that needs one says so and leaves it to you (`charpente toolchain install ndk --accept-license`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    why: str
    command: Optional[List[str]] = None                 # a `charpente ...` argument list; None: advice only
    download: bool = False
    advice: str = ""
    options: List[str] = field(default_factory=list)


def steps(report: Mapping[str, Any], *, lang_chosen: Optional[str]) -> List[Step]:
    out: List[Step] = []
    if not report.get("toolchains"):
        out.append(Step("compiler", "Install a C/C++ compiler (zig)", "no C/C++ compiler was found, so nothing can be built yet",
                        command=["toolchain", "install", "zig"], download=True,
                        advice="or install GCC, Clang or MSVC yourself, then run `charpente doctor`"))
    tools: Dict[str, Optional[str]] = dict(report.get("tools", {}))
    if not tools.get("git"):
        out.append(Step("git", "Install git", "git is used by `charpente commit/push/pr`, by dependencies fetched from repositories and by releases",
                        advice="https://git-scm.com/downloads (or your package manager)"))
    if not tools.get("clangd"):
        out.append(Step("clangd", "Install clangd (optional)", "code completion and diagnostics in `charpente studio` and the VS Code extension",
                        advice="it ships with LLVM/Clang (https://clang.llvm.org)"))
    if not report.get("debuggers"):
        out.append(Step("debugger", "Install a debugger (optional)", "`charpente debug` needs gdb 14+ or lldb-dap",
                        advice="gdb 14+ (MSYS2: `pacman -S mingw-w64-ucrt-x86_64-gdb`) or LLVM's lldb-dap"))
    if lang_chosen is None:
        out.append(Step("language", "Choose the language of messages", "errors and hints exist in English and French", options=["en", "fr"]))
    return out


def describe(step: Step) -> List[str]:
    lines = [f"{step.title}", f"    why: {step.why}"]
    if step.command:
        lines.append("    command: charpente " + " ".join(step.command) + ("   (downloads files)" if step.download else ""))
    if step.advice:
        lines.append(f"    {step.advice}")
    return lines
