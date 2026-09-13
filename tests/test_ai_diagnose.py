from charpente.ai.diagnose import diagnose
from charpente.ai.provider import AIProvider, NullProvider


class _FakeProvider(AIProvider):
    name = "fake"

    def __init__(self):
        self.received_prompt = None
        self.received_system = None

    def is_available(self):
        return True

    def complete(self, prompt, *, system=None):
        self.received_prompt = prompt
        self.received_system = system
        return "Missing #include <vector>."


def test_null_provider_gives_honest_message_not_a_crash():
    result = diagnose(NullProvider(), target_name="app", toolchain_name="gcc", error_text="undefined reference")
    assert "not configured" in result


def test_available_provider_receives_target_toolchain_and_error():
    provider = _FakeProvider()
    result = diagnose(provider, target_name="app", toolchain_name="gcc",
                      error_text="error: 'vector' was not declared")
    assert result == "Missing #include <vector>."
    assert "app" in provider.received_prompt
    assert "gcc" in provider.received_prompt
    assert "was not declared" in provider.received_prompt
    assert provider.received_system is not None
    assert "root cause" in provider.received_system
