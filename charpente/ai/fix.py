"""Ask an AI for a fix to a build error, as a diff that is checked against the real files before anyone sees it as applicable."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import patch as patch_mod
from .context import Context
from .provider import AIProvider

SYSTEM_PROMPT = (
    "You fix C/C++ build errors in a project built with Charpente. You are given the build output and the code around each reported location. "
    "Answer with at most three sentences explaining the cause, then ONE unified diff in a ```diff fenced block that fixes it. Rules for the diff: "
    "paths relative to the project root (as shown in the labels); context lines copied exactly from the code shown; change only what is needed; "
    "never delete files; never touch files that were not shown unless the fix requires a new file. If you cannot fix it from what you were "
    "given, say so and give no diff."
)


@dataclass
class Proposal:
    explanation: str
    diff: str                               # the diff as the model wrote it
    contents: Dict[str, str]                # new content per project-relative path (checked to apply cleanly)

    @property
    def files(self) -> List[str]:
        return sorted(self.contents)


def _explanation(answer: str, diff: str) -> str:
    return answer.replace(diff, "").replace("```diff", "").replace("```patch", "").replace("```", "").strip()


def request_fix(provider: AIProvider, context: Context, root: Path, *, extra_instruction: str = "") -> Proposal:
    """Send `context` (already reviewed by the user) and return a proposal that applies cleanly, or raise patch.PatchError with the reason."""
    prompt = context.render() + ("\n\n" + extra_instruction if extra_instruction else "") + "\n\nFix this build error."
    answer = provider.complete(prompt, system=SYSTEM_PROMPT)
    diff = patch_mod.extract_diff(answer)
    if not diff.strip():
        raise patch_mod.PatchError("the assistant gave no diff: " + (_explanation(answer, "")[:400] or "(empty answer)"))
    contents = patch_mod.apply_patches(root, patch_mod.parse(diff))
    return Proposal(_explanation(answer, diff), diff, contents)


def snapshot(root: Path, paths: List[str]) -> Dict[str, Optional[bytes]]:
    """The current bytes of each path (None when it does not exist yet): what to restore if the fix does not hold."""
    saved: Dict[str, Optional[bytes]] = {}
    for relative in paths:
        path = root / relative
        saved[relative] = path.read_bytes() if path.is_file() else None
    return saved


def restore(root: Path, saved: Dict[str, Optional[bytes]]) -> None:
    for relative, text in saved.items():
        path = root / relative
        if text is None:
            if path.is_file():
                path.unlink()
        else:
            path.write_bytes(text)


def apply_verified(root: Path, proposal: Proposal, verify: Callable[[], Tuple[bool, str]]) -> Tuple[bool, str]:
    """Write the proposal, run `verify()` (a build); keep the change only if it returns ok, else restore the files. Returns (kept, output)."""
    saved = snapshot(root, proposal.files)
    patch_mod.write(root, proposal.contents)
    try:
        ok, output = verify()
    except BaseException:
        restore(root, saved)
        raise
    if not ok:
        restore(root, saved)
    return ok, output
