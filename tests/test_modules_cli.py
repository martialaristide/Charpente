import http.server
import json
import smtplib
import threading
from pathlib import Path

import pytest

from charpente.cli import main
from charpente.commands import module as module_cmd
from charpente.errors import ChError
from charpente.events import EventBus
from charpente.modules import runtime, signing
from charpente.modules.capabilities import ModuleContext
from charpente.modules.official import bundled_manifest
from charpente.modules.official import notify as notify_mod
from charpente.modules.store import ModuleStore

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "modules" / "charpente-hello"


# ================================================================== module CLI
def test_scaffold_check_install_run_remove(tmp_path, capsys):
    assert main(["module", "new", "charpente-demo", "--dir", str(tmp_path)]) == 0
    folder = tmp_path / "charpente-demo"
    assert (folder / "charpente-module.toml").exists()
    assert main(["module", "check", str(folder)]) == 0
    assert "0 error(s)" in capsys.readouterr().out

    assert main(["module", "add", str(folder), "--allow-unsigned", "--yes"]) == 0
    assert main(["module", "list"]) == 0
    listing = capsys.readouterr().out
    assert "charpente-demo" in listing and "enabled" in listing and "unsigned" in listing

    assert main(["demo", "there"]) == 0                          # the module's command, discovered by name
    assert "Hello from charpente-demo! there" in capsys.readouterr().out
    assert main(["--help"]) == 0
    assert "demo" in capsys.readouterr().out                      # listed under module commands

    assert main(["module", "info", "charpente-demo"]) == 0
    assert "asks to" in capsys.readouterr().out
    assert main(["module", "disable", "charpente-demo"]) == 0
    assert main(["demo"]) == 1                                    # disabled: no longer a command
    assert main(["module", "remove", "charpente-demo"]) == 0
    assert main(["module", "remove", "charpente-demo"]) == 1


def test_scaffold_refuses_bad_names_and_existing_folders(tmp_path, capsys):
    assert main(["module", "new", "Bad Name", "--dir", str(tmp_path)]) == 1
    assert "CH4005" in capsys.readouterr().err
    assert main(["module", "new", "ok-name", "--dir", str(tmp_path)]) == 0
    assert main(["module", "new", "ok-name", "--dir", str(tmp_path)]) == 1


def test_unsigned_install_without_confirmation_is_refused_non_interactively(tmp_path, capsys):
    assert main(["module", "add", str(EXAMPLE)]) == 1
    err = capsys.readouterr()
    assert "CH7010" in err.err and "asks to" in err.out                # it showed what it wants first
    assert ModuleStore().list() == []


def test_interactive_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(module_cmd, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert main(["module", "add", str(EXAMPLE), "--allow-unsigned"]) == 1
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert main(["module", "add", str(EXAMPLE), "--allow-unsigned"]) == 0
    assert ModuleStore().get("charpente-hello") is not None


def test_key_generation_signing_and_trusted_install(tmp_path, capsys):
    key = tmp_path / "author.key"
    assert main(["module", "keygen", "--out", str(key)]) == 0
    out = capsys.readouterr().out
    public = next(line.split(": ")[1] for line in out.splitlines() if line.startswith("Public key"))
    assert main(["module", "keygen", "--out", str(key)]) == 1              # never overwrites a key

    assert main(["module", "new", "signed-mod", "--dir", str(tmp_path)]) == 0
    folder = tmp_path / "signed-mod"
    assert main(["module", "sign", str(folder), "--key", str(key)]) == 0
    assert main(["module", "trust-key", public]) == 0
    assert main(["module", "add", str(folder), "--yes"]) == 0               # signed: no --allow-unsigned needed
    assert ModuleStore().get("signed-mod").signature.startswith("signed:")

    (folder / "signed_mod" / "__init__.py").write_text("# tampered after signing")
    ModuleStore().remove("signed-mod")
    assert main(["module", "add", str(folder), "--yes", "--allow-unsigned"]) == 1
    assert "CH7007" in capsys.readouterr().err


def test_trust_key_rejects_garbage(capsys):
    assert main(["module", "trust-key", "not-hex"]) == 1


def test_registry_commands(tmp_path, capsys):
    assert main(["module", "registry", "add", "https://example.org/index.json"]) == 0
    assert main(["module", "registry", "list"]) == 0
    assert "https://example.org/index.json" in capsys.readouterr().out
    assert main(["module", "registry", "remove", "https://example.org/index.json"]) == 0
    assert main(["module", "registry", "remove", "https://example.org/index.json"]) == 1
    assert main(["module", "registry", "add"]) == 1


def test_check_reports_errors_with_a_failing_exit_code(tmp_path, capsys):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "charpente-module.toml").write_text("[module]\nname = 'x'\n")
    assert main(["module", "check", str(folder)]) == 1
    assert "ERROR" in capsys.readouterr().out
    assert main(["module", "check", "no-such-installed-module"]) == 1


def test_a_broken_installed_module_is_reported_by_list_but_the_cli_still_works(tmp_path, capsys):
    assert main(["module", "add", str(EXAMPLE), "--allow-unsigned", "--yes"]) == 0
    store = ModuleStore()
    record = store.get("charpente-hello")
    (Path(record.path) / "charpente_hello" / "__init__.py").write_text("raise RuntimeError('broken')")
    runtime.reset()
    assert main(["module", "list"]) == 0
    assert "broken" in capsys.readouterr().out
    assert main(["explain", "CH7009"]) == 0


def test_toolchain_list_includes_module_toolchains(tmp_path, monkeypatch, capsys):
    assert main(["module", "add", str(EXAMPLE), "--allow-unsigned", "--yes"]) == 0
    import shutil
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/opt/example-cc" if n == "example-cc" else real_which(n, *a, **k))
    runtime.reset()
    main(["toolchain", "list"])
    assert "example-cc" in capsys.readouterr().out


# ==================================================================== bundled
def test_bundled_notify_is_available_but_disabled_until_enabled(monkeypatch, capsys):
    assert main(["module", "list"]) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "charpente-notify" in ln)
    assert "disabled" in line and "bundled" in line
    monkeypatch.setattr(module_cmd, "_interactive", lambda: False)
    assert main(["module", "enable", "charpente-notify"]) == 1               # cannot approve non-interactively
    assert ModuleStore().get("charpente-notify") is None
    monkeypatch.setattr(module_cmd, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert main(["module", "enable", "charpente-notify"]) == 0
    assert ModuleStore().get("charpente-notify").enabled
    runtime.reset()
    assert runtime.get_registry().get("notifier", "discord") is not None
    assert main(["module", "disable", "charpente-notify"]) == 0
    assert runtime.get_registry().get("notifier", "discord") is None


def test_enabling_an_unknown_module_is_an_error():
    with pytest.raises(ChError) as exc:
        module_cmd._manifest_for(ModuleStore(), "ghost")
    assert exc.value.code == "CH7006"


# ==================================================================== notify
class _Sink(http.server.BaseHTTPRequestHandler):
    received: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Sink.received.append((self.path, json.loads(self.rfile.read(length) or b"{}")))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


@pytest.fixture
def sink():
    _Sink.received = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def notify_ctx(tmp_path, network=True):
    from charpente.modules.api import Capabilities
    manifest = bundled_manifest("charpente-notify")
    caps = Capabilities(process=("notify-send", "osascript", "powershell"), filesystem="workspace",
                        network=network)
    return ModuleContext(manifest, caps, data_dir=tmp_path / "d", workspace_root=tmp_path)


def write_config(root, text):
    (root / ".charpente").mkdir(exist_ok=True)
    (root / ".charpente" / "notify.toml").write_text(text)


def test_secrets_must_come_from_environment_variables(tmp_path):
    write_config(tmp_path, '[[notify]]\ntype = "discord"\nurl = "https://discord.com/api/webhooks/1/secret"\n')
    with pytest.raises(notify_mod.NotifyConfigError) as exc:
        notify_mod.load_config(tmp_path)
    assert "url_env" in str(exc.value) and "discord.com/api/webhooks/1/secret" not in str(exc.value)


def test_config_validation(tmp_path):
    assert notify_mod.load_config(tmp_path) == [] and notify_mod.load_config(None) == []
    write_config(tmp_path, '[[notify]]\ntype = "pigeon"\n')
    with pytest.raises(notify_mod.NotifyConfigError):
        notify_mod.load_config(tmp_path)
    write_config(tmp_path, "this is not toml [")
    with pytest.raises(notify_mod.NotifyConfigError):
        notify_mod.load_config(tmp_path)


@pytest.mark.parametrize("kind,check", [
    ("webhook", lambda body: body["ok"] is True and "message" in body),
    ("discord", lambda body: "content" in body and "Build succeeded" in body["content"]),
    ("slack", lambda body: "text" in body and "Build succeeded" in body["text"]),
])
def test_http_notifiers(tmp_path, sink, monkeypatch, kind, check):
    monkeypatch.setenv("HOOK_URL", sink + "/hook")
    write_config(tmp_path, f'[[notify]]\ntype = "{kind}"\nurl_env = "HOOK_URL"\n')
    disp = notify_mod.Dispatcher(notify_ctx(tmp_path), notify_mod.load_config(tmp_path))
    title, body, ok = notify_mod.compose({"ok": True, "command": "build", "config": "Release", "duration": 3.2})
    assert disp.send(title, body, ok) == 1
    path, payload = _Sink.received[0]
    assert path == "/hook" and check(payload)


def test_telegram_notifier(tmp_path, sink, monkeypatch):
    monkeypatch.setenv("TG", "TOKEN123")
    write_config(tmp_path, f'[[notify]]\ntype = "telegram"\ntoken_env = "TG"\nchat_id = "42"\napi_base = "{sink}"\n')
    disp = notify_mod.Dispatcher(notify_ctx(tmp_path), notify_mod.load_config(tmp_path))
    assert disp.send("t", "m", False) == 1
    path, payload = _Sink.received[0]
    assert path == "/botTOKEN123/sendMessage" and payload["chat_id"] == "42" and payload["text"].startswith("❌")


def test_when_filter_and_missing_environment(tmp_path, sink, monkeypatch):
    monkeypatch.setenv("HOOK_URL", sink)
    errors = []
    write_config(tmp_path, '[[notify]]\ntype = "webhook"\nurl_env = "HOOK_URL"\nwhen = "failure"\n'
                           '[[notify]]\ntype = "webhook"\nurl_env = "NOT_SET_ANYWHERE"\n')
    disp = notify_mod.Dispatcher(notify_ctx(tmp_path), notify_mod.load_config(tmp_path), on_error=errors.append)
    assert disp.send("t", "m", True) == 0                    # 1st only on failure; 2nd misconfigured
    assert len(errors) == 1 and "NOT_SET_ANYWHERE" in errors[0]
    assert disp.send("t", "m", False) == 1 and len(_Sink.received) == 1


def test_notifier_without_network_capability_is_refused(tmp_path, sink, monkeypatch):
    monkeypatch.setenv("HOOK_URL", sink)
    write_config(tmp_path, '[[notify]]\ntype = "webhook"\nurl_env = "HOOK_URL"\n')
    errors = []
    disp = notify_mod.Dispatcher(notify_ctx(tmp_path, network=False), notify_mod.load_config(tmp_path),
                                 on_error=errors.append)
    assert disp.send("t", "m", True) == 0 and "CH7005" in errors[0] or "did not declare" in errors[0]
    assert _Sink.received == []


def test_email_notifier(tmp_path, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append("starttls")

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, msg):
            sent.append(("msg", msg["Subject"], msg["To"], msg.get_content().strip()))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("U", "user")
    monkeypatch.setenv("P", "pass")
    write_config(tmp_path, '[[notify]]\ntype = "email"\nsmtp_host = "smtp.example.org"\nsmtp_port = 2525\n'
                           'username_env = "U"\npassword_env = "P"\nfrom = "b@x.org"\nto = ["a@x.org", "c@x.org"]\n')
    disp = notify_mod.Dispatcher(notify_ctx(tmp_path), notify_mod.load_config(tmp_path))
    assert disp.send("Build failed", "3 failed", False) == 1
    assert sent[0] == ("connect", "smtp.example.org", 2525) and "starttls" in sent
    assert ("login", "user", "pass") in sent
    assert sent[-1][:3] == ("msg", "Build failed", "a@x.org, c@x.org")


def test_desktop_notifier_uses_the_guarded_process_service(tmp_path, monkeypatch):
    ran = []
    ctx = notify_ctx(tmp_path)
    monkeypatch.setattr(ctx.process, "run", lambda argv, **kw: ran.append(argv))
    notify_mod.DesktopNotifier(ctx).notify("Title", "Body")
    assert ran and ran[0][0] in ("powershell", "osascript", "notify-send")


def test_compose_is_localised_and_has_no_source_code(monkeypatch):
    monkeypatch.setenv("CHARPENTE_LANG", "fr")
    title, body, ok = notify_mod.compose({"ok": False, "failed_actions": 3, "command": "build",
                                          "config": "Release", "host": "labo", "duration": 4.0})
    assert title == "Build en échec" and "labo" in body and "3 action(s) en échec" in body and not ok
    monkeypatch.setenv("CHARPENTE_LANG", "en")
    title, body, ok = notify_mod.compose({"ok": True, "command": "test", "host": "h", "duration": 1.0})
    assert title == "Build succeeded" and "no failures" in body


def test_session_subscriber_notifies_on_session_finished(tmp_path, sink, monkeypatch):
    monkeypatch.setenv("HOOK_URL", sink)
    write_config(tmp_path, '[[notify]]\ntype = "webhook"\nurl_env = "HOOK_URL"\n')
    sub = notify_mod.SessionSubscriber(notify_ctx(tmp_path))
    bus = EventBus(strict=True)
    bus.subscribe(sub, sync=True, name=sub.name, types=sub.patterns)
    bus.emit("session.started", command="build", argv=[], cwd="", version="x", config="Release")
    bus.emit("action.failed", action="a", target="t", kind="compile", returncode=1, duration=0.1, output="x")
    bus.emit("action.failed", action="b", target="t", kind="compile", returncode=1, duration=0.1, output="x")
    bus.emit("session.finished", ok=False, duration=2.5)
    payload = _Sink.received[0][1]
    assert payload["ok"] is False and "2 failed action(s)" in payload["message"] and "Release" in payload["message"]


def test_notify_command(tmp_path, sink, monkeypatch, capsys):
    monkeypatch.setenv("HOOK_URL", sink)
    monkeypatch.chdir(tmp_path)
    cmd = notify_mod.NotifyCommand(notify_ctx(tmp_path))
    assert cmd(["nonsense"]) == 1
    assert cmd(["test"]) == 1 and "No notifiers configured" in capsys.readouterr().out
    write_config(tmp_path, '[[notify]]\ntype = "webhook"\nurl_env = "HOOK_URL"\n')
    assert cmd(["test"]) == 0 and "Sent 1 of 1" in capsys.readouterr().out


def test_builds_notify_through_the_enabled_module_end_to_end(tmp_path, sink, monkeypatch):
    from charpente.platform import host_os
    from charpente.toolchains import NoToolchainFoundError, pick_default
    try:
        pick_default(host_os())
    except NoToolchainFoundError:
        pytest.skip("no compiler")
    monkeypatch.setattr(module_cmd, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert main(["module", "enable", "charpente-notify"]) == 0
    monkeypatch.setenv("CHARPENTE_TRUST_ALL", "1")
    monkeypatch.setenv("HOOK_URL", sink)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.cpp").write_text("int main(){return 0;}")
    (tmp_path / "w.charpente").write_text('from charpente import *\nwith Workspace("W") as ws:\n'
                                          '    with Target("app") as t:\n        t.sources(["a.cpp"])\n')
    write_config(tmp_path, '[[notify]]\ntype = "webhook"\nurl_env = "HOOK_URL"\n')
    runtime.reset()
    assert main(["build"]) == 0
    import time
    for _ in range(50):                       # the subscriber is asynchronous
        if _Sink.received:
            break
        time.sleep(0.05)
    assert _Sink.received and _Sink.received[0][1]["ok"] is True
    assert signing  # keep the import used
