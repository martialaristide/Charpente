"""`charpente tui` -- a terminal interface on top of the same server state Studio and the editors use.

A table of targets with their last result, a log of what the engine does, and keys for the everyday actions:
build (b), build all (a), run (r), test (t), quality gate (c), reload (l), quit (q). It needs the optional `textual` package.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from .events import Event
from .serve.rpc import RpcError
from .serve.state import ServerState

PENDING, BUILDING, OK, FAILED, UP_TO_DATE = "-", "building...", "ok", "FAILED", "up to date"


class CharpenteApp(App[None]):
    TITLE = "Charpente"
    CSS = """
    #targets { width: 42; border: round $primary; }
    #log { border: round $secondary; }
    #status { height: 1; padding: 0 1; }
    """
    BINDINGS = [
        Binding("b", "build_selected", "Build"),
        Binding("a", "build_all", "Build all"),
        Binding("r", "run_selected", "Run"),
        Binding("t", "test_all", "Test"),
        Binding("c", "check", "Check"),
        Binding("l", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, state: ServerState, config: str = "Debug") -> None:
        super().__init__()
        self.state = state
        self.config = config
        self.results: Dict[str, str] = {}
        self.busy = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="targets", cursor_type="row", zebra_stripes=True)
            yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#targets", DataTable)
        table.add_columns("Target", "Kind", "Result")
        self.refresh_targets()

    # ------------------------------------------------------------------ helpers
    def log_line(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def refresh_targets(self) -> None:
        table = self.query_one("#targets", DataTable)
        table.clear()
        try:
            targets = self.state.own_targets()
        except RpcError as exc:
            self.log_line(f"Cannot load the workspace: {exc.message}")
            self.set_status("no workspace loaded -- fix the error above, then press l")
            return
        for name, target in targets.items():
            table.add_row(name, target.kind.value, self.results.get(name, PENDING), key=name)
        self.set_status(f"{self.state.require().name}: {len(targets)} target(s) -- {self.config}")

    def selected(self) -> Optional[str]:
        table = self.query_one("#targets", DataTable)
        if table.row_count == 0:
            return None
        try:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        except Exception:
            return None

    def mark(self, name: str, result: str) -> None:
        self.results[name] = result
        table = self.query_one("#targets", DataTable)
        try:
            table.update_cell(name, table.ordered_columns[2].key, result)
        except Exception:
            pass                                                       # the row is gone (workspace reloaded)

    def begin(self, what: str) -> bool:
        if self.busy:
            self.log_line("A task is already running; wait for it to finish.")
            return False
        self.busy = True
        self.set_status(what)
        return True

    def end(self, text: str) -> None:
        self.busy = False
        self.set_status(text)

    # ------------------------------------------------------------------ actions
    def action_build_selected(self) -> None:
        name = self.selected()
        if name is None:
            self.log_line("No target to build.")
        elif self.begin(f"Building {name}..."):
            self.do_build([name])

    def action_build_all(self) -> None:
        try:
            names = list(self.state.own_targets())
        except RpcError as exc:
            self.log_line(exc.message)
            return
        if names and self.begin("Building everything..."):
            self.do_build(names)

    def action_run_selected(self) -> None:
        name = self.selected()
        if name is None:
            self.log_line("No target to run.")
        elif self.begin(f"Running {name}..."):
            self.do_cli(["run", "--target", name, "--config", self.config], f"run {name}")

    def action_test_all(self) -> None:
        if self.begin("Testing..."):
            self.do_cli(["test", "--config", self.config], "test")

    def action_check(self) -> None:
        if self.begin("Running the quality gate..."):
            self.do_check()

    def action_reload(self) -> None:
        try:
            self.state.load()
            self.log_line("Workspace reloaded.")
        except RpcError as exc:
            self.log_line(f"Cannot load the workspace: {exc.message}")
        self.results.clear()
        self.refresh_targets()

    # ------------------------------------------------------------------ background work
    @work(thread=True, exclusive=False)
    def do_build(self, names: List[str]) -> None:
        def on_event(event: Event) -> None:
            data: Mapping[str, Any] = event.payload
            if event.type == "target.started":
                self.call_from_thread(self.mark, str(data.get("target")), BUILDING)
            elif event.type == "target.finished":
                self.call_from_thread(self.mark, str(data.get("target")), OK)
            elif event.type == "target.up_to_date":
                self.call_from_thread(self.mark, str(data.get("target")), UP_TO_DATE)
            elif event.type == "target.failed":
                self.call_from_thread(self.mark, str(data.get("target")), FAILED)
            elif event.type == "action.output" and data.get("text"):
                self.call_from_thread(self.log_line, str(data["text"]).rstrip())
            elif event.type == "diagnostic.emitted":
                where = f"{data.get('file')}:{data.get('line')}: " if data.get("file") else ""
                self.call_from_thread(self.log_line, f"{data.get('severity', 'error')}: {where}{data.get('message', '')}")

        try:
            ok, results, _ = self.state.compile(names, config=self.config, on_event=on_event)
        except RpcError as exc:
            self.call_from_thread(self.log_line, exc.message)
            self.call_from_thread(self.end, "build not started")
            return
        for result in results:
            if not result["ok"] and result["error"]:
                self.call_from_thread(self.log_line, str(result["error"]))
        self.call_from_thread(self.end, "Build succeeded" if ok else "Build FAILED")

    @work(thread=True, exclusive=False)
    def do_cli(self, args: List[str], label: str) -> None:
        code, output = self.state.run_cli(args)
        for line in output.splitlines():
            self.call_from_thread(self.log_line, line)
        self.call_from_thread(self.end, f"{label}: {'ok' if code == 0 else f'exit code {code}'}")

    @work(thread=True, exclusive=False)
    def do_check(self) -> None:
        try:
            outcome = self.state.check()
        except Exception as exc:
            self.call_from_thread(self.log_line, f"The gate could not run: {exc}")
            self.call_from_thread(self.end, "check: error")
            return
        for finding in outcome["findings"]:
            where = f"{finding['file']}:{finding['line']}: " if finding.get("file") else ""
            self.call_from_thread(self.log_line, f"[{finding['check']}] {where}{finding['message']}")
        self.call_from_thread(self.end, "check: " + ("passed" if outcome.get("ok") else "FAILED"))
