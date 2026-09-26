"""@TITLE@: a Charpente module. `charpente module check .` verifies it against the module API."""


class HelloCommand:
    name = "@IDENT@-hello"
    help = "Say hello from the @NAME@ module"

    def __call__(self, args):
        print("Hello from the @NAME@ module!", " ".join(args))
        return 0


def register(registry, ctx):
    registry.add_command(HelloCommand())
