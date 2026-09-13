"""AI-assisted diagnosis of a failed compile/link. Separate from the `ask`
command's prompt so each can be tuned independently, and so this is
reusable (currently `build`, potentially `test`/`run` later) without
importing a CLI command module.

Never invoked automatically: a build failure is common and often
self-explanatory (a typo, a missing semicolon), and every AI call costs
money/latency and sends source-adjacent text to a third party. Opt-in via
--ai-diagnose, matching the project-wide rule that nothing here talks to
an AI provider unless the user explicitly asked it to for that run.
"""
from __future__ import annotations

from .provider import AIProvider

SYSTEM_PROMPT = (
    "You are a build-error diagnostic assistant for Charpente, a "
    "Python-DSL-driven C/C++ build tool. Given a compiler or linker's raw "
    "error output, identify the most likely root cause and suggest one "
    "specific, concrete fix (an exact flag to add, a header to include, a "
    "library to link, a syntax correction) rather than generic advice. Keep "
    "the answer under 100 words unless the error genuinely requires more."
)


def diagnose(provider: AIProvider, *, target_name: str, toolchain_name: str, error_text: str) -> str:
    if not provider.is_available():
        return provider.complete(error_text)  # NullProvider's honest "not configured" message

    prompt = (
        f"Target: {target_name}\n"
        f"Toolchain: {toolchain_name}\n"
        f"Compiler/linker output:\n{error_text}\n\n"
        f"What is the likely cause, and what's the specific fix?"
    )
    return provider.complete(prompt, system=SYSTEM_PROMPT)
