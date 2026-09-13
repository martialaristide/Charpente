from __future__ import annotations

from typing import List, Optional, Tuple

from ..ai import select_provider
from ._common import CommandError, load

_SYSTEM_PROMPT = (
    "You are a build-system assistant for Charpente, a Python-DSL-driven "
    "C/C++ build tool. Answer concisely and concretely. If given a build "
    "error log, identify the likely cause and suggest a specific fix "
    "(a flag to add, a missing include, a linker library) rather than "
    "generic advice."
)


def _parse_args(args: List[str]) -> Tuple[Optional[str], str]:
    """Deliberately not argparse: a question is free-form natural language
    and can legitimately start with '-' (e.g. "--verbose doesn't print
    anything") -- argparse.REMAINDER treats an unrecognized leading '-'
    token as a parse error instead of passing it through, which would make
    `charpente ask --why is this broken` crash instead of asking. The only
    real option here is --file, pulled out manually; everything else,
    dashes included, becomes the question text."""
    file_arg: Optional[str] = None
    question_parts: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--file" and i + 1 < len(args):
            file_arg = args[i + 1]
            i += 2
        else:
            question_parts.append(args[i])
            i += 1
    return file_arg, " ".join(question_parts).strip()


def execute(args: List[str]) -> int:
    file_arg, question = _parse_args(args)
    if not question:
        raise CommandError("Usage: charpente ask [--file PATH] <question>")

    provider = select_provider()
    if not provider.is_available():
        print(provider.complete(question))  # NullProvider's honest "not configured" message
        return 1

    context_lines = []
    try:
        workspace = load(file_arg)
        context_lines.append(f"Current workspace: {workspace.name!r}, targets: {sorted(workspace.targets)}")
    except CommandError:
        pass  # Answering without workspace context is still useful (e.g. a general question).

    prompt = question
    if context_lines:
        prompt = "\n".join(context_lines) + "\n\nQuestion: " + question

    print(f"(using {provider.name})")
    print(provider.complete(prompt, system=_SYSTEM_PROMPT))
    return 0
