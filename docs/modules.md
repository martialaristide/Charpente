# Modules

Everything that is not the core is a **module**: toolchains, platforms,
languages, package formats, quality checks, notifiers, AI providers, project
templates, commands, event subscribers. Charpente's own built-in toolchains and
the bundled official modules use exactly the API described here — there is no
private path.

Module API version: **2.0.0** (semantic versioning; a module states the range it
was written for, `api = "^2.0"`, and is refused outside it).

## Using modules

```bash
charpente module list                       # installed + bundled, with state and origin
charpente module add ./charpente-hello      # from a folder (also .zip, URL, or a registry name)
charpente module info charpente-hello       # what it provides, what it asks for
charpente hello world                       # modules add commands
charpente module disable charpente-hello
charpente module remove charpente-hello
```

**Installing shows what the module asks to be allowed to do, and asks you.** The
answer is remembered; if an update asks for more, the module stays disabled until
you approve again. **Installing never runs the module's code** — it is imported
only when loaded. An unsigned module needs `--allow-unsigned`; see
[`security.md`](security.md) for signatures and for the honest limits of the
capability system (a contract for well-behaved modules, **not** a sandbox).

Registries are JSON indexes (a file or a URL) — private ones work the same way:

```json
{"modules": {"charpente-hello": {"versions": {
   "1.0.0": {"url": "charpente-hello-1.0.0.zip", "sha256": "…"}}}}}
```

```bash
charpente module registry add https://modules.example.org/index.json
charpente module add charpente-hello@^1.0
charpente module update
```

Downloads are resumable, verified against the published SHA-256, and can be
capped (`--max-download 5MB`). `CHARPENTE_OFFLINE=1` forbids the network.

## Writing a module

```bash
charpente module new charpente-demo        # scaffolds a working module
charpente module check charpente-demo      # conformance checks
charpente module add charpente-demo --allow-unsigned --yes
charpente demo
```

A module is a folder with a manifest and Python code.

`charpente-module.toml`:

```toml
[module]
name = "charpente-demo"
version = "0.1.0"
api = "^2.0"                       # module API range
license = "Apache-2.0"
description = "What it does"
entry = "charpente_demo:register"  # package.module:function
python = ">=3.9"                   # optional

[provides]                         # everything it registers must be declared here
commands = ["demo"]
toolchains = ["my-cc"]
events = ["demo.done"]             # its own event types ("family.name")

[capabilities]
process = ["my-compiler"]          # programs it may start
filesystem = "workspace"           # none | workspace | build | home
network = false                    # true, or ["host.example.org"]
```

`charpente_demo/__init__.py`:

```python
class DemoCommand:
    name = "demo"
    help = "charpente demo -- an example"

    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, args):
        result = self.ctx.process.run(["my-compiler", "--version"])   # guarded by [capabilities]
        print(result.stdout)
        self.ctx.emit("demo.done", ok=True)                            # declared event
        return 0

def register(registry, ctx):
    registry.add_command(DemoCommand(ctx))
```

### Extension points

| `[provides]` key | Registered with | Interface |
|---|---|---|
| `commands` | `registry.add_command(obj)` | `name`, `help`, `__call__(args) -> int` |
| `toolchains` | `registry.add_toolchain(obj)` | `name`, `detect(host_os, which) -> [Toolchain]` |
| `notifiers` | `registry.add_notifier(obj)` | `name`, `notify(title, message, ok=…)` |
| `checks` | `registry.add_check(obj)` | `name`, `level`, `run(root, files, fix)` |
| `packagers` | `registry.add_packager(obj)` | `name`, `package(workspace, target, output, …)` |
| `templates` | `registry.add_template(obj)` | `name`, `description`, `generate(dest, project_name)` |
| `subscribers` | `registry.add_subscriber(obj)` | `name`, `patterns`, `__call__(event)` |
| `platforms`, `languages`, `kinds`, `ai_providers` | `add_platform`, `add_language`, `add_kind`, `add_ai_provider` | reserved; the interfaces are defined as those phases land |

Rules the registry enforces: a module registers only what it declared
(`CH7014`); names are unique across modules (`CH7008`); a module can add
commands but never replace a built-in one (`CH7013`).

### The context (`ctx`)

| | |
|---|---|
| `ctx.process.run(argv, …)` | starts a program from the approved `process` list; never a shell |
| `ctx.fs.read_text / write_text / …` | confined to the approved `filesystem` scope (plus the module's own `ctx.data_dir`); `..` and symlink escapes are refused |
| `ctx.net.request / post_json` | only http(s), only approved hosts |
| `ctx.emit(type, **payload)` | only event types declared in `[provides] events` |
| `ctx.manifest`, `ctx.workspace_root`, `ctx.data_dir` | metadata and paths |

Violations raise `CH7005`.

### Conformance

`charpente module check PATH` verifies: valid manifest, compatible API, importable
entry point, `register` works, everything registered is declared and everything
declared is registered, each extension implements its interface. It **warns** when a
module imports `subprocess`, `socket`, `ctypes` or calls `os.system` directly, which
bypasses the guarded services.

### Signing

```bash
charpente module keygen --out my.key       # keep the secret key private
charpente module sign ./charpente-demo --key my.key
# users:  charpente module trust-key <public key>   then   charpente module add ./charpente-demo
```

## The bundled module `charpente-notify`

Off until you run `charpente module enable charpente-notify`. It provides the
notifiers `desktop`, `webhook`, `discord`, `slack`, `telegram`, `email`, the command
`charpente notify test`, and a subscriber that notifies when a build finishes.
Configuration lives in `.charpente/notify.toml`; **secrets are only ever referenced by
environment variable name**:

```toml
[[notify]]
type = "discord"
url_env = "CHARPENTE_DISCORD_URL"
when = "failure"                 # always (default) | failure | success

[[notify]]
type = "telegram"
token_env = "TELEGRAM_TOKEN"
chat_id = "123456"

[[notify]]
type = "email"
smtp_host = "smtp.example.org"
smtp_port = 587
username_env = "SMTP_USER"
password_env = "SMTP_PASSWORD"
from = "builds@example.org"
to = ["me@example.org"]
```

Its e-mail notifier uses `smtplib` directly (it needs the declared `network`
capability, which it checks) — one of the honest caveats of a capability *contract*.

## The example module

[`examples/modules/charpente-hello`](../examples/modules/charpente-hello) registers a
command, a toolchain provider and an event, and is exercised by the test suite
(`tests/test_modules_core.py`): install, load, run, conformance.
