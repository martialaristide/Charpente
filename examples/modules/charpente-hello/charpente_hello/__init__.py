"""charpente-hello: the smallest useful third-party module.

It shows the three most common extension points: a command (`charpente hello`),
a toolchain provider (so a compiler Charpente does not know appears in
`charpente toolchain list`) and a custom event.
"""
from charpente.toolchains import Toolchain


class HelloCommand:
    name = "hello"
    help = "say hello (example module command)"

    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, args):
        who = " ".join(args) or "world"
        print(f"Hello, {who}! (from charpente-hello {self.ctx.manifest.version})")
        self.ctx.emit("hello.said", who=who)
        return 0


class ExampleToolchain:
    """Pretends a compiler called `example-cc` is installed when it is on PATH."""

    name = "example-cc"

    def detect(self, host_os, which):
        cc = which("example-cc")
        if not cc:
            return []
        return [Toolchain(name="example-cc", c_compiler=cc, cxx_compiler=cc, archiver="ar", linker=cc)]


def register(registry, ctx):
    registry.add_command(HelloCommand(ctx))
    registry.add_toolchain(ExampleToolchain())
