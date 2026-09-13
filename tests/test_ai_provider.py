from charpente.ai.provider import (
    AnthropicProvider,
    LocalProvider,
    NullProvider,
    OpenAIProvider,
    select_provider,
)


def test_default_with_nothing_configured_is_null():
    provider = select_provider(env={})
    assert isinstance(provider, NullProvider)


def test_null_provider_is_never_available_but_never_raises():
    provider = NullProvider()
    assert provider.is_available() is False
    message = provider.complete("does this crash?")
    assert "not configured" in message


def test_anthropic_key_selects_anthropic_provider():
    provider = select_provider(env={"ANTHROPIC_API_KEY": "sk-ant-fake"})
    assert isinstance(provider, AnthropicProvider)


def test_openai_key_selects_openai_provider():
    provider = select_provider(env={"OPENAI_API_KEY": "sk-fake"})
    assert isinstance(provider, OpenAIProvider)


def test_anthropic_key_takes_priority_over_openai_key():
    provider = select_provider(env={"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "b"})
    assert isinstance(provider, AnthropicProvider)


def test_local_url_selects_local_provider_when_no_keys_present():
    provider = select_provider(env={"CHARPENTE_AI_URL": "http://localhost:11434/v1"})
    assert isinstance(provider, LocalProvider)


def test_explicit_provider_override_wins_even_with_keys_present():
    provider = select_provider(env={
        "CHARPENTE_AI_PROVIDER": "none",
        "ANTHROPIC_API_KEY": "a",
    })
    assert isinstance(provider, NullProvider)


def test_anthropic_provider_unavailable_without_key():
    provider = AnthropicProvider(api_key="")
    assert provider.is_available() is False


def test_local_provider_availability_just_needs_a_url():
    provider = LocalProvider("http://localhost:11434/v1")
    assert provider.is_available() is True
    assert LocalProvider("").is_available() is False


def test_local_provider_speaks_openai_compatible_json(monkeypatch):
    """Verifies the request shape without touching the network: patches
    urllib.request.urlopen with a fake that inspects what was sent and
    returns a canned OpenAI-shaped response."""
    import json
    from io import BytesIO

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "42"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LocalProvider("http://localhost:11434/v1", model="llama3")
    answer = provider.complete("what is the answer?", system="be terse")

    assert answer == "42"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["body"]["model"] == "llama3"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "be terse"}
    assert captured["body"]["messages"][1] == {"role": "user", "content": "what is the answer?"}
