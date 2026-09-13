from __future__ import annotations

import argparse
from typing import List

from ..ai import select_provider
from ._common import CommandError, load

_SYSTEM_PROMPT = (
    "You are a build-system assistant for Charpente, a Python-DSL-driven "
    "C/C++ build tool. Answer concisely and concretely. If given a build "
    "error log, identify the likely cause and suggest a specific fix "
    "(a flag to add, a missing include, a linker library) rather than "
    "generic advice."
)


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente ask", description="Ask the AI assistant a question.")
    parser.add_argument("question", nargs=argparse.REMAINDER, help="Your question")
    parser.add_argument("--file", help="Path to the .charpente workspace file (for context)")
    parsed = parser.parse_args(args)

    question = " ".join(parsed.question).strip()
    if not question:
        raise CommandError("Usage: charpente ask <question>")

    provider = select_provider()
    if not provider.is_available():
        print(provider.complete(question))  # NullProvider's honest "not configured" message
        return 1

    context_lines = []
    try:
        workspace = load(parsed.file)
        context_lines.append(f"Current workspace: {workspace.name!r}, targets: {sorted(workspace.targets)}")
    except CommandError:
        pass  # Answering without workspace context is still useful (e.g. a general question).

    prompt = question
    if context_lines:
        prompt = "\n".join(context_lines) + "\n\nQuestion: " + question

    print(f"(using {provider.name})")
    print(provider.complete(prompt, system=_SYSTEM_PROMPT))
    return 0
