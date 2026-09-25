"""English message catalogue. Keys: title, message, cause, fix, [explain].

`message` is a `str.format` template; the placeholders are the keyword
parameters given to `ChError(code, **params)`.

The 'message' texts of CH1xxx-CH4xxx are the v0.1.0 wording, kept word for
word: existing scripts and tests match on them.
"""
from __future__ import annotations

from typing import Dict

CATALOG: Dict[str, Dict[str, str]] = {
    # ------------------------------------------------------------------ 1xxx
    "CH1001": {
        "title": "Workspace file not found",
        "message": "No such file: {path}",
        "cause": "The path given with --file does not exist.",
        "fix": "Check the spelling of the path, or run the command from the folder containing the .charpente file.",
        "explain": "Commands that need a workspace accept --file PATH. Without it, Charpente looks for a single *.charpente file in the current folder, then in each parent folder.",
    },
    "CH1002": {
        "title": "No .charpente file found",
        "message": "No .charpente file found in {directory} or its parent directories.",
        "cause": "Neither the current folder nor any parent folder contains a .charpente file.",
        "fix": "Run `charpente init MyApp` to create one, or use --file PATH.",
    },
    "CH1003": {
        "title": "Several .charpente files",
        "message": "Multiple .charpente files in {directory}: {names}. Use --file to pick one.",
        "cause": "Charpente only auto-selects a workspace when a folder contains exactly one .charpente file.",
        "fix": "Pass --file PATH with the workspace you want.",
    },
    "CH1004": {
        "title": "The workspace file failed to load",
        "message": "Error loading {path}: {detail}",
        "cause": "The .charpente file is Python code, and running it raised an error (syntax error, unknown name, wrong argument...).",
        "fix": "Read the detail after the colon: it names the line and the problem. Run `charpente lint` for a static check.",
    },
    "CH1005": {
        "title": "No workspace defined",
        "message": "{path} did not define a workspace (no `with Workspace(...):` block).",
        "cause": "The file ran without error but never opened a `with Workspace(...)` block.",
        "fix": "Wrap your targets in `with Workspace(\"Name\") as ws:`.",
    },
    "CH1006": {
        "title": "Confirmation required before running the workspace file",
        "message": "Refusing to run this {label} without confirmation: {path}\n  A .charpente file executes as unrestricted Python code. This session cannot ask for confirmation (non-interactive).\n  Fix: run `charpente` once interactively to approve it, or set CHARPENTE_TRUST_ALL=1 in this environment (CI) if you trust the source of this repository.",
        "cause": "A .charpente file is executable code. Charpente asks once per file and per content before running it, and this terminal is not interactive.",
        "fix": "Run any command once in an interactive terminal and answer 'y', or set CHARPENTE_TRUST_ALL=1 in CI for repositories you trust.",
        "explain": "Approvals are stored by SHA-256 of the file content in ~/.charpente/trusted_files.json. Editing the file asks again. A declarative charpente.toml never needs approval because it contains no code.",
    },
    "CH1007": {
        "title": "Execution declined",
        "message": "Execution declined by user: {path}",
        "cause": "You answered 'no' when asked whether to run this .charpente file.",
        "fix": "Read the file, and run the command again if you trust it.",
    },
    "CH1008": {
        "title": "Unknown target",
        "message": "No target named {name!r} in workspace {workspace!r}. Known targets: {known}",
        "cause": "The name given to --target is not declared in the workspace.",
        "fix": "Use one of the listed target names.",
    },
    "CH1009": {
        "title": "Several targets: choose one",
        "message": "Workspace {workspace!r} has {count} targets; specify one with --target. Known targets: {known}",
        "cause": "The command works on one target and the workspace declares several.",
        "fix": "Add --target NAME.",
    },
    "CH1010": {
        "title": "Workspace has no targets",
        "message": "Workspace {workspace!r} has no targets to run.",
        "cause": "No `with Target(...)` block was declared.",
        "fix": "Declare at least one target.",
    },
    "CH1011": {
        "title": "Empty name",
        "message": "{field} cannot be empty.",
        "cause": "Workspace and target names become file names, so they cannot be blank.",
        "fix": "Give it a non-empty name.",
    },
    "CH1012": {
        "title": "Name contains '..'",
        "message": "{field} {name!r} contains '..', which is not allowed (it could make a generated file escape the output directory).",
        "cause": "A '..' in a name could make an output file land outside the build folder.",
        "fix": "Remove the '..' from the name.",
    },
    "CH1013": {
        "title": "Name contains a path separator or control character",
        "message": "{field} {name!r} contains a path separator or control character, which is not allowed.",
        "cause": "Names become file names; slashes, backslashes and control characters are not valid there.",
        "fix": "Use letters, digits, '-', '_' and '.'.",
    },
    "CH1014": {
        "title": "Target declared outside a workspace",
        "message": "Target {name!r} declared outside of any `with Workspace(...)` block.",
        "cause": "`Target(...)` must be used inside a `with Workspace(...)` block.",
        "fix": "Move the target inside the workspace block.",
    },
    "CH1015": {
        "title": "Nested workspaces",
        "message": "Workspace {name!r} opened while workspace {outer!r} is still open. Workspaces cannot be nested.",
        "cause": "A `with Workspace(...)` block was opened inside another one.",
        "fix": "Close the first workspace before opening another.",
    },
    "CH1016": {
        "title": "Duplicate target",
        "message": "Target {name!r} is already defined in workspace {workspace!r}.",
        "cause": "Two targets share a name.",
        "fix": "Rename one of them.",
    },
    "CH1017": {
        "title": "Target has no location",
        "message": "Target {name!r} has no location set; resolved_sources() must run after the loader attaches it.",
        "cause": "A target was built by hand without the workspace folder.",
        "fix": "Create targets through the DSL, or pass `location=`.",
    },
    "CH1018": {
        "title": "Workspace file not found",
        "message": "Workspace file not found: {path}",
        "cause": "The loader was given a path that does not exist.",
        "fix": "Check the path.",
    },
    # ------------------------------------------------------------------ 2xxx
    "CH2001": {
        "title": "No C/C++ compiler found",
        "message": "No C/C++ compiler found for {os}. Install one and make sure it's on PATH:\n  windows -> Visual Studio Build Tools (cl.exe), or LLVM (clang-cl.exe), or MSYS2/MinGW (gcc.exe + g++.exe)\n  linux   -> `apt install build-essential` (gcc/g++) or clang\n  macos   -> `xcode-select --install` (clang via Xcode CLT)",
        "cause": "Charpente searches PATH for a compiler and found none.",
        "fix": "Install a compiler for your system (see the message) and reopen your terminal. `charpente doctor` re-checks.",
    },
    "CH2002": {
        "title": "Program not found",
        "message": "Program not found: {tool!r}. It is not installed or not on PATH.",
        "cause": "Charpente tried to start a program that the system cannot locate.",
        "fix": "Install it, or add its folder to PATH. `charpente doctor` lists what is missing.",
    },
    "CH2003": {
        "title": "Unsupported host system",
        "message": "Unsupported host OS: {os!r}",
        "cause": "Charpente can only run builds from Windows, Linux or macOS hosts.",
        "fix": "Use a supported machine.",
    },
    "CH2004": {
        "title": "Permission denied starting a program",
        "message": "Permission denied when starting {tool!r}.",
        "cause": "The file exists but cannot be executed (missing execute bit, antivirus, or it is a folder).",
        "fix": "Check its permissions (chmod +x on Linux/macOS) or your security software.",
    },
    # ------------------------------------------------------------------ 3xxx
    "CH3001": {
        "title": "Target without source files",
        "message": "Target {target!r} has no source files (check its sources()/exclude() patterns).",
        "cause": "The glob patterns given to sources() matched no file, or exclude() removed all of them.",
        "fix": "Check the patterns relative to the folder of the .charpente file (e.g. \"src/**/*.cpp\").",
    },
    "CH3002": {
        "title": "Compilation failed",
        "message": "{detail}",
        "cause": "The compiler returned an error for a source file.",
        "fix": "Read the first error message: later ones are often consequences. `charpente build --ai-diagnose` can help (opt-in).",
    },
    "CH3003": {
        "title": "Link failed",
        "message": "{detail}",
        "cause": "Every file compiled, but the linker could not produce the output (missing library, undefined symbol, duplicate symbol).",
        "fix": "Check .links([...]) and the order of dependencies.",
    },
    "CH3004": {
        "title": "Dependency cycle",
        "message": "Dependency cycle detected: {cycle}",
        "cause": "Targets depend on each other in a loop, so no build order exists.",
        "fix": "Break the loop: move shared code to a third target that both depend on.",
    },
    "CH3005": {
        "title": "Unknown dependency",
        "message": "Target {target!r} depends on unknown target {dependency!r}.",
        "cause": "depends_on() names a target that is not declared.",
        "fix": "Fix the spelling or declare the target.",
    },
    "CH3006": {
        "title": "Skipped because a dependency failed",
        "message": "Skipped: depends on failed target(s) {targets}.",
        "cause": "A target this one needs did not build.",
        "fix": "Fix the failing target first.",
    },
    "CH3007": {
        "title": "Unhandled target kind",
        "message": "Unhandled target kind: {kind}",
        "cause": "The target kind is not supported by the selected toolchain/platform.",
        "fix": "Check `charpente platforms` and the kind support table.",
    },
    "CH3008": {
        "title": "Build interrupted",
        "message": "Build interrupted.",
        "cause": "The build was stopped (Ctrl+C or a signal).",
        "fix": "Run the build again: finished actions are kept in the cache and are not redone.",
    },
    "CH3009": {
        "title": "Action produced no output file",
        "message": "The command succeeded but did not create {path}.",
        "cause": "A build command exited with 0 yet the expected file is missing (wrong -o, or a tool that writes elsewhere).",
        "fix": "Check the command with `charpente build -v` and the tool's documentation.",
    },
    "CH3010": {
        "title": "Two actions write the same file",
        "message": "Two build actions write the same file {path}: {first} and {second}.",
        "cause": "Two targets (or two sources) would produce an output with the same path, so one would silently overwrite the other.",
        "fix": "Give the sources or targets distinct names, or exclude one of them.",
    },
    "CH3011": {
        "title": "Ordering constraint on an unknown action",
        "message": "Action {action!r} must run after {missing!r}, which does not exist.",
        "cause": "An internal ordering edge points at an action that is not in the build graph.",
        "fix": "This is a bug in a module or in Charpente; report it.",
    },
    "CH3012": {
        "title": "Cycle in the action graph",
        "message": "The build actions depend on each other in a cycle: {cycle}",
        "cause": "An action (directly or through others) needs its own output before it can run.",
        "fix": "Break the cycle: check generated files that are also inputs of the action producing them.",
    },
    "CH3013": {
        "title": "Duplicate action",
        "message": "The action {action!r} is defined twice.",
        "cause": "Two actions were given the same identifier.",
        "fix": "This is a bug in a module or in Charpente; report it.",
    },
    # ------------------------------------------------------------------ 4xxx
    "CH4001": {
        "title": "Nothing to package",
        "message": "Build failed, nothing to package: {detail}",
        "cause": "Packaging first builds the target; that build failed.",
        "fix": "Fix the build error above, then package again.",
    },
    "CH4002": {
        "title": "No installer format for this system",
        "message": "No installer format defined for {os}.",
        "cause": "--format installer exists for Windows, Linux and macOS only.",
        "fix": "Use --format zip.",
    },
    "CH4003": {
        "title": "Packaging tool failed",
        "message": "{tool} failed (exit code {code}).",
        "cause": "The platform installer tool returned an error.",
        "fix": "Read the tool's own output above this message.",
    },
    "CH4004": {
        "title": "Output not built yet",
        "message": "{path} does not exist. Build first (drop --no-build).",
        "cause": "--no-build was given but the target was never built in this configuration.",
        "fix": "Run without --no-build, or run `charpente build` first.",
    },
    "CH4005": {
        "title": "Usage error",
        "message": "{usage}",
        "cause": "The command line is incomplete or malformed.",
        "fix": "Run the command with --help.",
    },
    # ------------------------------------------------------------------ 5xxx
    "CH5001": {
        "title": "AI provider not configured",
        "message": "No AI provider is configured.",
        "cause": "AI features are optional and off until you choose a provider.",
        "fix": "Set ANTHROPIC_API_KEY, OPENAI_API_KEY or CHARPENTE_AI_URL (see docs/security.md).",
    },
    # ------------------------------------------------------------------ 9xxx
    "CH9001": {
        "title": "Command must be a list of arguments",
        "message": "Refusing to run {command!r}: a command must be a non-empty list of arguments, never a shell string.",
        "cause": "Charpente never passes commands through a shell (no shell=True), which prevents injection through file names.",
        "fix": "Internal rule: pass [\"program\", \"arg1\", ...]. If you see this from a module, report it to its author.",
    },
    "CH9002": {
        "title": "Internal error",
        "message": "Internal error: {detail}",
        "cause": "A bug in Charpente.",
        "fix": "Please report it with the output of `charpente doctor` at https://github.com/martialaristide/Charpente/issues",
    },
}
