"""The console interface: what `charpente` shows when you type it alone in a terminal.

A guided, menu-driven front end for people who prefer the terminal to Charpente Studio. It does nothing the command line cannot do: every choice ends as an
ordinary `charpente ...` command, shown before it runs, so using the menu also teaches the commands. It runs commands through `charpente.cli.main`, the same code
path as the command line (never a shell), and asks before anything that removes files.

Keys (on a terminal that has them): arrows or the shortcut shown beside each row, Enter to choose, Esc to go back, Ctrl+C to leave. Anywhere else (a pipe,
`CHARPENTE_CONSOLE=plain`, a terminal that cannot be driven) the same menus work with numbers and Enter.

Everything that touches the world is passed in (`read_line`, `write`, `run_cli`, `gather`, ...), so the whole interface is tested with scripted input.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import _version, settings
from ..ui import banner as banner_mod
from . import dashboard as dash_mod
from . import text, view
from .dashboard import Dashboard
from .term import Caps, Keys, Style, glyphs_for, visible_len
from .view import Entry, group, selectable, with_hotkeys

RunCli = Callable[[List[str]], int]
_ARG = re.compile(r'"([^"]*)"|(\S+)')
_CODE = re.compile(r"^CH\d{4}$", re.IGNORECASE)
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
CONFIGS = ("Debug", "Release")
TIGHT_HEIGHT = 42          # below this many rows the summary is two lines and the tip is left out


def default_run_cli(argv: List[str]) -> int:
    from ..cli import main

    try:
        return int(main(argv))
    except SystemExit as exc:                                # argparse ends a bad or `--help` call this way
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


def display_command(argv: Sequence[str]) -> str:
    """`charpente build --config Debug`, with an argument that has spaces in quotes (for reading, not for a shell)."""
    def quote(arg: str) -> str:
        return '"' + arg.replace('"', '\\"') + '"' if not arg or re.search(r'[\s"\']', arg) else arg
    return "charpente " + " ".join(quote(a) for a in argv)


def split_args(line: str) -> List[str]:
    """Program arguments as typed: words, with "double quotes" keeping spaces together."""
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _ARG.finditer(line)]


def default_templates() -> List[Tuple[str, str, bool]]:
    from ..modules.runtime import get_registry

    out = []
    for extension in sorted(get_registry().all("template"), key=lambda e: e.name):
        template = extension.obj
        info = getattr(template, "info", None)
        out.append((template.name, template.description, info is None or bool(info.verified)))
    return out


def default_platform_report() -> Dict[str, Any]:
    from .. import platforms
    from ..commands import doctor

    report = doctor.gather()
    return {"host": report.get("host", ""), "buildable": list(report.get("buildable", [])), "missing": dict(report.get("missing", {})),
            "platforms": [(p.name, p.family, p.tier) for p in platforms.all_platforms()]}


def default_kits(root: Optional[Path]) -> List[Tuple[str, str]]:
    from ..pkg import kits as kits_mod

    extra = (root / ".charpente" / "kits") if root else None
    return [(k.name, k.description) for k in kits_mod.load_all(extra).values()]


class Console:
    def __init__(self, *, caps: Caps, keys: Optional[Keys], read_line: Callable[[str], str], write: Callable[[str], None],
                 run_cli: RunCli = default_run_cli, cwd: Optional[Path] = None, gather: Callable[[Path], Dashboard] = dash_mod.gather,
                 lang: Optional[str] = None, clock: Callable[[], float] = time.time,
                 templates: Callable[[], List[Tuple[str, str, bool]]] = default_templates,
                 platform_report: Callable[[], Dict[str, Any]] = default_platform_report,
                 kits: Callable[[Optional[Path]], List[Tuple[str, str]]] = default_kits,
                 logo: Optional[Callable[[], str]] = None) -> None:
        self.caps = caps
        self.keys = keys if caps.interactive and caps.ansi else None
        self.read_line = read_line
        self.write = write
        self.run_cli = run_cli
        self.cwd = cwd or Path.cwd()
        self.gather = gather
        self.lang = lang or _current_lang()
        self.clock = clock
        self.templates = templates
        self.platform_report = platform_report
        self.kits = kits
        self.logo = logo                                     # the big banner (charpente/ui/banner.py), shown on the first menu screen when there is room
        self.style = Style(caps.color)
        self.glyphs = glyphs_for(caps)
        self.config = "Debug"
        self.platform: Optional[str] = None
        self.notice = ""
        self.tip = 0
        self._report: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ small helpers
    def tr(self, key: str, **values: Any) -> str:
        return text.lookup(self.lang, key).format(**values)

    def out(self, line: str = "") -> None:
        self.write(line + "\n")

    def width(self) -> int:
        return min(self.caps.width, 100)

    def clear(self) -> None:
        if self.caps.ansi:
            self.write("\x1b[2J\x1b[H")
        else:
            self.out()

    def rule(self) -> str:
        return self.style.muted(" " + self.glyphs.h * min(self.width() - 2, 78))

    def mode_args(self, platform: bool = True) -> List[str]:
        args = ["--config", self.config]
        if platform and self.platform:
            args += ["--platform", self.platform]
        return args

    # ------------------------------------------------------------------ drawing and choosing
    def tight(self) -> bool:
        """A small terminal: the summary shrinks to two lines and the tip goes, so the menu keeps its room."""
        return (self.keys is not None and self.caps.height < TIGHT_HEIGHT) or self.width() < view.DASHBOARD_MIN_WIDTH

    def header(self, dash: Optional[Dashboard] = None, title: str = "", subtitle: str = "", big: Optional[List[str]] = None) -> List[str]:
        width = self.width()
        tight = self.tight()
        if big:                                              # the big banner takes the place of the one-line title
            lines = [""] + big + [""]
        else:
            lines = ([] if tight else [""]) + view.banner(self.tr, _version.__version__, self.style, self.glyphs, width) + ([] if tight else [""])
        if dash is not None:
            if tight:
                lines += view.compact_dashboard(dash, str(self.cwd), self.config, self.platform, self.tr, self.style, self.glyphs, width, self.clock())
            else:
                lines += view.dashboard(dash, str(self.cwd), self.config, self.platform, self.tr, self.style, self.glyphs, width, self.clock())
            lines.append("")
        if title:
            lines.append(" " + self.style.bold(title))
        if subtitle:
            lines.append(" " + self.style.muted(subtitle))
        if title or subtitle:
            lines.append("")
        return lines

    def page(self, title: str, subtitle: str = "") -> None:
        """Before a question: on a terminal, clear the menu that led here and show what the question is about."""
        if self.keys is not None:
            self.clear()
            self.write("\n".join(self.header(None, title, subtitle)) + "\n")

    def choose(self, header: List[str], entries: Sequence[Entry], *, initial: str = "", tip: bool = False) -> Optional[str]:
        """Show a menu and return the chosen entry's key, or None when the user goes back (Esc, Left, `q`/`b`)."""
        entries = with_hotkeys(entries)
        picks = selectable(entries)
        if not picks:
            return None
        start = next((i for i in picks if entries[i].key == initial and entries[i].enabled), None)
        if start is None:
            start = next((i for i in picks if entries[i].enabled), picks[0])
        return self._choose_keys(header, entries, picks, start, tip) if self.keys else self._choose_line(header, entries, tip)

    def _screen(self, header: List[str], entries: Sequence[Entry], selected: int, tip: bool) -> List[str]:
        width = self.width()
        tail: List[str] = []
        if 0 <= selected < len(entries):
            tail.append(view.detail(entries[selected], self.style, width))
        if tip and not self.tight():
            tail += ["", self._tip_line(width)]
        footer = view.footer(self.tr, self.glyphs, self.keys is not None, width, self.style)
        tail += [footer] if self.tight() else ["", footer]
        rows = max(5, self.caps.height - len(header) - len(tail) - 1)
        body, _hidden = view.menu(entries, selected, self.style, self.glyphs, width, rows)
        return header + body + tail

    def _tip_line(self, width: int) -> str:
        return view.tip_line(self.tr("tip.label"), self.tr(f"tip.{self.tip % text.TIP_COUNT + 1}"), self.style, width, self.glyphs)

    def _choose_keys(self, header: List[str], entries: Sequence[Entry], picks: List[int], selected: int, tip: bool) -> Optional[str]:
        assert self.keys is not None
        self.write("\x1b[?25l")                              # hide the cursor while a menu is shown
        try:
            while True:
                self.clear()
                self.write("\n".join(self._screen(header, entries, selected, tip)) + "\n")
                key = self.keys.read()
                position = picks.index(selected)
                if key in ("down", "up"):
                    step = 1 if key == "down" else -1
                    for offset in range(1, len(picks) + 1):                  # the next row that can be used (disabled rows are skipped)
                        candidate = picks[(position + step * offset) % len(picks)]
                        if entries[candidate].enabled:
                            selected = candidate
                            break
                elif key in ("home", "pgup"):
                    selected = picks[0] if key == "home" else picks[max(0, position - 5)]
                elif key in ("end", "pgdn"):
                    selected = picks[-1] if key == "end" else picks[min(len(picks) - 1, position + 5)]
                elif key == "enter":
                    if entries[selected].enabled:
                        return entries[selected].key
                elif key in ("esc", "left", "backspace"):
                    return None
                elif key in ("ctrl-c", "ctrl-d"):
                    raise KeyboardInterrupt
                elif len(key) == 1:
                    match = next((i for i in picks if entries[i].hotkey.lower() == key.lower()), None)
                    if match is not None:
                        selected = match
                        if entries[match].enabled:
                            return entries[match].key
                    elif key.lower() in ("q", "b"):
                        return None
        finally:
            self.write("\x1b[?25h")

    def _choose_line(self, header: List[str], entries: Sequence[Entry], tip: bool) -> Optional[str]:
        picks = selectable(entries)
        width = self.width()
        body, _ = view.menu(entries, -1, self.style, self.glyphs, width, 10_000)
        self.write("\n".join(header + body) + "\n")
        if tip:
            self.out(self._tip_line(width))
        self.out(view.footer(self.tr, self.glyphs, False, width, self.style))
        while True:
            answer = self.read_line(" " + self.tr("prompt.choice")).strip().lower()
            if not answer:
                continue
            match = next((i for i in picks if entries[i].hotkey.lower() == answer), None)
            if match is not None:
                if entries[match].enabled:
                    return entries[match].key
                self.out(" " + self.style.warn(entries[match].reason))
                continue
            if answer in ("q", "b", "back", "quit"):
                return None
            self.out(" " + self.style.warn(self.tr("prompt.unknown", answer=answer)))

    # ------------------------------------------------------------------ asking
    def _line(self, prompt: str) -> Optional[str]:
        """One line typed by the user; None when they cancel it. Ctrl+C cancels, and so does the end-of-input a terminal reports for Ctrl+C on some systems
        (Windows): on a real terminal that is a cancellation, not a closed input. With a pipe, a closed input still ends the program."""
        try:
            return self.read_line(prompt)
        except KeyboardInterrupt:
            self.out()
            return None
        except EOFError:
            if not self.caps.interactive:
                raise
            self.out()
            return None

    def ask(self, question: str, default: str = "", validate: Optional[Callable[[str], str]] = None) -> Optional[str]:
        """A line of text. Enter alone gives the default; Ctrl+C cancels (None). `validate` returns an error message, or "" when the answer is fine."""
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self._line(f" {self.style.bold(question)}{suffix}: ")
            if answer is None:
                return None
            answer = answer.strip() or default
            problem = validate(answer) if validate else ""
            if not problem:
                return answer
            self.out(" " + self.style.warn(problem))

    def confirm(self, question: str, default: bool = False) -> bool:
        hint = self.tr("prompt.yes_no_default_yes") if default else self.tr("prompt.yes_no_default_no")
        while True:
            answer = self._line(f" {self.style.bold(question)} {hint} ")
            if answer is None:
                return False
            answer = answer.strip().lower()
            if not answer:
                return default
            if answer in text.YES[self.lang]:
                return True
            if answer in text.NO[self.lang]:
                return False

    def pause(self) -> None:
        self._line(" " + self.style.muted(self.tr("prompt.press_enter")))

    # ------------------------------------------------------------------ running commands
    def run_command(self, argv: List[str]) -> int:
        self.clear()
        self.out()
        self.out(self.rule())
        self.out(f" {self.style.accent(self.glyphs.marker)} {self.style.bold(display_command(argv))}")
        self.out(" " + self.style.muted(self.tr("cmd.equivalent")))
        self.out(self.rule())
        try:
            code = self.run_cli(argv)
        except KeyboardInterrupt:
            code = 130
        except Exception as exc:                             # a bug in a command must not close the menu
            self.out(f"charpente: {type(exc).__name__}: {exc}")
            code = 70
        self.out(self.rule())
        if code == 0:
            self.out(" " + self.style.ok(self.glyphs.dot + " " + self.tr("cmd.done")))
        elif code == 130:
            self.out(" " + self.style.warn(self.glyphs.dot + " " + self.tr("cmd.interrupted")))
        else:
            self.out(" " + self.style.err(self.glyphs.dot + " " + self.tr("cmd.failed", code=code)))
            self.out(" " + self.style.muted(self.tr("cmd.failed_tip")))
        self.out()
        self.pause()
        return code

    def show(self, title: str, lines: Sequence[str]) -> None:
        """A page of information (no command)."""
        self.clear()
        self.write("\n".join(self.header(None, title) + [" " + line if line else "" for line in lines]) + "\n\n")
        self.pause()

    # ------------------------------------------------------------------ the main loop
    def _splash(self, dash: Dashboard, entries: Sequence[Entry]) -> Optional[List[str]]:
        """The lines of the big banner when the first screen has room for it above the whole menu (a real terminal with arrow keys, and tall enough); else None."""
        if self.logo is None or self.keys is None:
            return None
        try:
            text = self.logo()
        except Exception:                                    # a picture must never stop the menu
            return None
        big = text.split("\n") if text else []
        if not big or max(visible_len(x) for x in big) > self.width():
            return None
        plain = self.header(dash, big=big)
        menu_lines, _ = view.menu(with_hotkeys(entries), -1, self.style, self.glyphs, self.width(), 10_000)
        needed = len(plain) + len(menu_lines) + 4            # the detail line, the footer and a margin
        return big if needed <= self.caps.height else None

    def run(self) -> int:
        initial = ""
        first = True
        try:
            while True:
                dash = self.gather(self.cwd)
                entries = self.project_entries(dash) if dash.has_project else self.start_entries(dash)
                big = self._splash(dash, entries) if first else None
                if first:
                    first = False
                    if self.logo is not None:
                        banner_mod.mark_shown()              # whether or not it fitted, this screen has its own title: commands run from here do not print another
                header = self.header(dash, big=big)
                if self.notice:
                    header += [" " + self.style.ok(self.notice), ""]
                    self.notice = ""
                choice = self.choose(header, entries, initial=initial, tip=True)
                self.tip += 1
                if choice is None or choice == "quit":
                    break
                initial = choice
                handler = getattr(self, "do_" + choice)
                argv = handler(dash)
                if argv:
                    self.run_command(argv)
        except (KeyboardInterrupt, EOFError):
            self.out()
        self.out(" " + self.style.muted(self.tr("bye")))
        return 0

    # ------------------------------------------------------------------ menus
    def start_entries(self, dash: Dashboard) -> List[Entry]:
        t = self.tr
        recommend = t("hint.recommended") if not dash.compiler else ""
        return [
            group(t("group.start")),
            Entry("create", t("item.create"), t("hint.create"), "1"),
            Entry("open", t("item.open"), t("hint.open"), "2"),
            Entry("setup", t("item.setup"), (recommend + " " if recommend else "") + t("hint.setup"), "3"),
            Entry("doctor_check", t("item.check_machine"), t("hint.check_machine"), "4"),
            Entry("guide", t("item.guide"), t("hint.guide"), "5"),
            group(t("group.more")),
            Entry("studio", t("item.studio"), t("hint.studio"), "s"),
            Entry("lang", t("item.lang", other=self._other_lang_name()), "", "l"),
            Entry("help", t("item.help"), t("hint.help"), "?"),
            Entry("quit", t("item.quit"), "", "q"),
        ]

    def project_entries(self, dash: Dashboard) -> List[Entry]:
        t = self.tr
        broken = dash.state == "error"
        why = t("reason.fix_project") if broken else ""
        cross = bool(self.platform) and self.platform != dash.host
        return [
            group(t("group.build")),
            Entry("build", t("item.build"), t("hint.build", mode=self._mode_label()), "1", enabled=not broken, reason=why),
            Entry("run", t("item.run"), t("hint.run"), "2", enabled=not broken and not cross, reason=why or t("reason.cross_run", platform=self.platform or "")),
            Entry("test", t("item.test"), t("hint.test"), "3", enabled=not broken, reason=why),
            Entry("watch", t("item.watch"), t("hint.watch"), "4", enabled=not broken, reason=why),
            group(t("group.project")),
            Entry("targets", t("item.targets"), t("hint.targets"), "5"),
            Entry("platform", t("item.platform"), t("hint.platform", platform=self.platform or t("dash.native")), "6"),
            Entry("package", t("item.package"), t("hint.package"), "7", enabled=not broken, reason=why),
            Entry("check", t("item.check"), t("hint.check"), "8", enabled=not broken, reason=why),
            group(t("group.tools")),
            Entry("doctor", t("item.doctor"), t("hint.doctor"), "9"),
            Entry("git", t("item.git"), t("hint.git"), "g"),
            Entry("cache", t("item.cache"), t("hint.cache"), "x"),
            Entry("studio", t("item.studio"), t("hint.studio"), "s"),
            Entry("tui", t("item.tui"), t("hint.tui"), "t"),
            group(t("group.session")),
            Entry("mode", t("item.mode", mode=self._other_config()), t("hint.mode", mode=self.config), "m"),
            Entry("lang", t("item.lang", other=self._other_lang_name()), "", "l"),
            Entry("help", t("item.help"), t("hint.help"), "?"),
            Entry("quit", t("item.quit"), "", "q"),
        ]

    def _other_config(self) -> str:
        return CONFIGS[1] if self.config == CONFIGS[0] else CONFIGS[0]

    def _mode_label(self) -> str:
        return f"{self.config}, {self.platform or self.tr('dash.native')}"

    def _other_lang_name(self) -> str:
        return "Français" if self.lang == "en" else "English"

    # ------------------------------------------------------------------ actions of the start menu
    def do_create(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        templates = self.templates()
        entries = [Entry(name, name, description + ("" if verified else " " + t("tag.unverified"))) for name, description, verified in templates]
        chosen = self.choose(self.header(None, t("create.title"), t("create.subtitle")), entries)
        if chosen is None:
            return None
        self.page(t("create.title"), t("create.template", template=chosen))
        name = self.ask(t("create.name"), t("create.default_name"), self._validate_project_name)
        if name is None:
            return None
        target = self.cwd / name
        self.out()
        self.out(" " + t("create.summary", template=chosen, name=name, folder=str(target)))
        if not self.confirm(t("create.confirm"), True):
            return None
        argv = ["init", name, "--template", chosen]
        if self._needs_install(chosen):
            argv.append("--install")
        self.run_command(argv)
        if (target).is_dir():
            self.cwd = target
            os.chdir(target)
            self.notice = t("create.opened", name=name)
        return None

    def _needs_install(self, template: str) -> bool:
        from ..modules.runtime import get_registry

        extension = get_registry().get("template", template)
        info = getattr(getattr(extension, "obj", None), "info", None)
        return bool(info is not None and info.install)

    def _validate_project_name(self, name: str) -> str:
        if not _NAME.match(name):
            return self.tr("create.bad_name")
        if (self.cwd / name).exists():
            return self.tr("create.exists", folder=str(self.cwd / name))
        return ""

    def do_open(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        found = _projects_below(self.cwd)
        entries = [Entry(str(path), path.parent.name, str(path.parent)) for path in found] + [Entry("__path__", t("open.other"), t("open.other_hint"))]
        chosen = self.choose(self.header(None, t("open.title")), entries)
        if chosen is None:
            return None
        if chosen == "__path__":
            self.page(t("open.title"))
            answer = self.ask(t("open.path"), "", lambda p: "" if not p or Path(p).expanduser().is_dir() else t("open.not_a_folder", path=p))
            if not answer:
                return None
            folder = Path(answer).expanduser().resolve()
        else:
            folder = Path(chosen).parent
        os.chdir(folder)
        self.cwd = folder
        self.notice = t("open.opened", folder=str(folder))
        return None

    def do_setup(self, dash: Dashboard) -> Optional[List[str]]:
        return ["setup"]

    def do_doctor_check(self, dash: Dashboard) -> Optional[List[str]]:
        return ["doctor"]

    def do_guide(self, dash: Dashboard) -> Optional[List[str]]:
        self.show(self.tr("guide.title"), [self.tr(f"guide.{i}") for i in range(1, text.GUIDE_LINES + 1)])
        return None

    # ------------------------------------------------------------------ actions of the project menu
    def do_build(self, dash: Dashboard) -> Optional[List[str]]:
        return ["build", *self.mode_args()]

    def _pick_target(self, dash: Dashboard, kinds: Optional[Sequence[str]] = None) -> Tuple[bool, Optional[str]]:
        """(went ahead, target name or None). With one candidate it is used without asking; with several the user picks."""
        candidates = [x for x in dash.targets if kinds is None or x.kind in kinds]
        if len(candidates) <= 1:
            return True, candidates[0].name if candidates else None
        entries = [Entry(x.name, x.name, x.kind) for x in candidates]
        chosen = self.choose(self.header(None, self.tr("pick.target")), entries)
        return (chosen is not None), chosen

    def do_run(self, dash: Dashboard) -> Optional[List[str]]:
        ok, target = self._pick_target(dash, ("executable", "xr_app", "web_app"))
        if not ok:
            return None
        self.page(self.tr("item.run"))
        arguments = self.ask(self.tr("run.args"), "")
        if arguments is None:
            return None
        argv = ["run", *(["--target", target] if target else []), *self.mode_args()]
        given = split_args(arguments)
        return argv + (["--", *given] if given else [])

    def do_test(self, dash: Dashboard) -> Optional[List[str]]:
        return ["test", *self.mode_args()]

    def do_watch(self, dash: Dashboard) -> Optional[List[str]]:
        self.out()
        self.out(" " + self.style.muted(self.tr("watch.note")))
        return ["dev", *self.mode_args()]

    def do_check(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        entries = [Entry("rapide", t("check.fast"), t("check.fast_hint")), Entry("standard", t("check.standard"), t("check.standard_hint")),
                   Entry("strict", t("check.strict"), t("check.strict_hint"))]
        level = self.choose(self.header(None, t("check.title")), entries, initial="standard")
        return ["check", "--level", level] if level else None

    def do_package(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        formats = [Entry("zip", "zip", t("package.zip")), Entry("installer", t("package.installer"), t("package.installer_hint"))]
        if (self.platform or "").startswith("android"):
            formats.append(Entry("apk", "apk", t("package.apk")))
        chosen = self.choose(self.header(None, t("package.title")), formats)
        if chosen is None:
            return None
        ok, target = self._pick_target(dash, ("executable", "mobile_app", "xr_app", "web_app"))
        if not ok:
            return None
        return ["package", "--format", chosen, *(["--target", target] if target else []), *self.mode_args()]

    def do_targets(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        entries = [Entry("list", t("targets.list"), t("targets.list_hint")), Entry("search", t("targets.search"), t("targets.search_hint")),
                   Entry("install", t("targets.install"), t("targets.install_hint")), Entry("kits", t("targets.kits"), t("targets.kits_hint")),
                   Entry("addkit", t("targets.addkit"), t("targets.addkit_hint"))]
        chosen = self.choose(self.header(None, t("targets.title")), entries)
        if chosen == "list":
            if not dash.targets:
                self.show(t("targets.title"), [t("targets.none")])
            else:
                width = max(len(x.name) for x in dash.targets) + 2
                self.show(t("targets.title"), [f"{x.name:<{width}}{x.kind}" for x in dash.targets])
            return None
        if chosen == "search":
            self.page(t("targets.search"))
            query = self.ask(t("targets.query"), "", lambda q: "" if q else t("prompt.required"))
            return ["pkg", "search", query] if query else None
        if chosen == "install":
            return ["pkg", "install"]
        if chosen == "kits":
            return ["kit", "list"]
        if chosen == "addkit":
            available = self.kits(dash.root)
            kit = self.choose(self.header(None, t("targets.addkit")), [Entry(name, name, description) for name, description in available])
            return ["kit", "add", kit] if kit else None
        return None

    def platform_info(self) -> Dict[str, Any]:
        if self._report is None:
            self.out(" " + self.style.muted(self.tr("platform.checking")))
            self._report = self.platform_report()
        return self._report

    def do_platform(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        report = self.platform_info()
        buildable = set(report["buildable"])
        missing = report["missing"]
        entries: List[Entry] = []
        if any(name.startswith("android") for name in buildable):
            entries += [group(t("platform.actions")), Entry("__deploy__", t("platform.deploy"), t("platform.deploy_hint"))]
        entries += [group(t("platform.choose")), Entry("__native__", t("platform.native", host=report["host"]), t("platform.native_hint"))]
        for name, family, tier in report["platforms"]:
            if name == report["host"]:
                continue
            if name in buildable:
                entries.append(Entry(name, name, f"{family} {self.glyphs.dot} {t('platform.tier', tier=tier)}"))
            else:
                entries.append(Entry(name, name, "", enabled=False, reason=missing.get(name) or t("platform.needs_toolchain")))
        chosen = self.choose(self.header(None, t("platform.title"), t("platform.subtitle")), entries, initial=self.platform or "__native__")
        if chosen is None:
            return None
        if chosen == "__deploy__":
            return ["deploy", "--device", "all", "--config", self.config]
        self.platform = None if chosen == "__native__" else chosen
        self.notice = t("platform.now", platform=self.platform or t("dash.native"))
        return None

    def do_doctor(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        entries = [Entry("doctor", t("doctor.machine"), t("doctor.machine_hint")), Entry("explain", t("doctor.explain"), t("doctor.explain_hint")),
                   Entry("why", t("doctor.why"), t("doctor.why_hint")), Entry("history", t("doctor.history"), t("doctor.history_hint")),
                   Entry("headers", t("doctor.headers"), t("doctor.headers_hint"))]
        chosen = self.choose(self.header(None, t("doctor.title")), entries)
        if chosen is None:
            return None
        if chosen == "explain":
            self.page(t("doctor.explain"))
            code = self.ask(t("doctor.code"), "", lambda c: "" if _CODE.match(c) else t("doctor.bad_code"))
            return ["explain", code.upper(), "--lang", self.lang] if code else None
        if chosen == "why":
            self.page(t("doctor.why"))
            subject = self.ask(t("doctor.subject"), "", lambda s: "" if s else t("prompt.required"))
            return ["why", subject] if subject else None
        return [chosen]

    def do_git(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        entries = [Entry("status", t("git.status"), t("git.status_hint")), Entry("commit", t("git.commit"), t("git.commit_hint")),
                   Entry("push", t("git.push"), t("git.push_hint")), Entry("hooks", t("git.hooks"), t("git.hooks_hint"))]
        chosen = self.choose(self.header(None, t("git.title")), entries)
        if chosen == "status":
            return ["status"]
        if chosen == "commit":
            self.page(t("git.commit"))
            message = self.ask(t("git.message"), "", lambda m: "" if m else t("prompt.required"))
            if not message:
                return None
            argv = ["commit", "-m", message]
            if self.confirm(t("git.stage_all"), False):
                argv.append("-a")
            return argv
        if chosen == "push":
            self.page(t("git.push"))
            return ["push"] if self.confirm(t("git.confirm_push"), False) else None
        if chosen == "hooks":
            return ["hooks", "install"]
        return None

    def do_cache(self, dash: Dashboard) -> Optional[List[str]]:
        t = self.tr
        entries = [Entry("stats", t("cache.stats"), t("cache.stats_hint")), Entry("gc", t("cache.gc"), t("cache.gc_hint")),
                   Entry("clean", t("cache.clean"), t("cache.clean_hint")), Entry("clear", t("cache.clear"), t("cache.clear_hint")),
                   Entry("uninstall", t("cache.uninstall"), t("cache.uninstall_hint"))]
        chosen = self.choose(self.header(None, t("cache.title")), entries)
        if chosen == "stats":
            return ["cache", "stats"]
        if chosen == "gc":
            return ["cache", "gc"]
        if chosen == "clean":
            self.page(t("cache.clean"))
            return ["clean"] if self.confirm(t("cache.confirm_clean"), False) else None
        if chosen == "clear":
            self.page(t("cache.clear"))
            return ["cache", "clear"] if self.confirm(t("cache.confirm_clear"), False) else None
        if chosen == "uninstall":
            return ["self", "uninstall"]
        return None

    def do_studio(self, dash: Dashboard) -> Optional[List[str]]:
        return ["studio"]

    def do_tui(self, dash: Dashboard) -> Optional[List[str]]:
        return ["tui"]

    def do_mode(self, dash: Dashboard) -> Optional[List[str]]:
        self.config = self._other_config()
        self.notice = self.tr("mode.now", mode=self.config)
        return None

    def do_lang(self, dash: Dashboard) -> Optional[List[str]]:
        self.lang = "fr" if self.lang == "en" else "en"
        os.environ["CHARPENTE_LANG"] = self.lang             # the commands started from here answer in the same language
        try:
            settings.set_value("lang", self.lang)
        except (OSError, ValueError):
            pass
        self.notice = self.tr("lang.now")
        return None

    def do_help(self, dash: Dashboard) -> Optional[List[str]]:
        self.show(self.tr("help.title"), [self.tr(f"help.{i}") for i in range(1, text.HELP_LINES + 1)])
        return None


# ---------------------------------------------------------------------- helpers
def _current_lang() -> str:
    from .. import i18n

    return i18n.current_lang()


def _projects_below(folder: Path) -> List[Path]:
    """`.charpente` files in the sub-folders of `folder` (one level), so a folder of projects can be browsed."""
    found: List[Path] = []
    try:
        for child in sorted(folder.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                found += sorted(p for p in child.glob("*.charpente") if p.is_file())
    except OSError:
        pass
    return found[:30]


def detect_ui_caps(stdout: Any) -> Any:
    from ..ui.term import detect as detect_ui

    return detect_ui(None, stdout)


def real_console(stdin: Any = None, stdout: Any = None) -> Console:
    """The console wired to the real terminal."""
    from .term import detect, native_keys

    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    caps = detect(stdin, stdout)

    def write(chunk: str) -> None:
        stdout.write(chunk)
        stdout.flush()

    def read_line(prompt: str) -> str:
        write(prompt)
        line: str = stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")

    def logo() -> str:
        from ..ui.term import detect as detect_ui

        ui_caps = detect_ui(None, stdout)
        return banner_mod.render_banner(ui_caps, banner_mod.theme_named(os.environ.get("CHARPENTE_THEME")), None, None)

    return Console(caps=caps, keys=native_keys() if caps.interactive else None, read_line=read_line, write=write,
                   logo=logo if banner_mod.should_show_banner(None, detect_ui_caps(stdout)) else None)
