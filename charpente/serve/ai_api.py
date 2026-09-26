"""The assistant panel's methods. Two steps, on purpose: `charpente/ai/context` builds and returns exactly what would be sent (nothing leaves the
machine), and `charpente/ai/send` sends a context the user has seen, by its id. Changes proposed by the assistant are diffs, checked against the
files, applied only by `charpente/ai/apply`, which rebuilds, reverts on failure and runs the quality gate.
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from ..ai import fix as fix_mod
from ..ai import patch as patch_mod
from ..ai.context import Context, error_context, is_secret_file, workspace_summary
from ..ai.provider import AIProvider, select_provider
from ..errors import ChError
from .rpc import INVALID_PARAMS, Dispatcher, RpcError
from .state import ServerState

KEEP = 8                                                     # contexts and proposals remembered per connection
NOT_AVAILABLE = -32020

EXPLAIN_SYSTEM = (
    "You are the assistant of Charpente Studio, a C/C++ workspace. Answer concisely and concretely, in the language of the question. "
    "For a build error: name the likely cause and give one specific fix. Never invent files or APIs that were not shown."
)


class AiApi:
    def __init__(self, state: ServerState, select: Callable[[], AIProvider] = select_provider) -> None:
        self.state = state
        self._select = select
        self._contexts: "OrderedDict[str, Context]" = OrderedDict()
        self._proposals: "OrderedDict[str, fix_mod.Proposal]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _remember(store: "OrderedDict[str, Any]", value: Any) -> str:
        ident = uuid.uuid4().hex[:12]
        store[ident] = value
        while len(store) > KEEP:
            store.popitem(last=False)
        return ident

    def provider(self) -> AIProvider:
        return self._select()

    def status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = self.provider()
        return {"available": provider.is_available(), "provider": provider.name,
                "howTo": None if provider.is_available() else "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or CHARPENTE_AI_URL for a local server."}

    def context(self, params: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(params.get("kind", "question"))
        text = str(params.get("text", ""))
        workspace = self.state.require()
        root = self.state.root
        if kind == "error":
            context = error_context(root, workspace, text)
        elif kind == "selection":
            path = str(params.get("path", ""))
            if is_secret_file(path):
                raise RpcError(INVALID_PARAMS, f"{path} looks like a secrets file: it is never sent")
            context = Context()
            context.add("workspace", workspace_summary(workspace))
            context.add(f"{path} (selection)", str(params.get("selection", "")))
            if text:
                context.add("question", text)
        elif kind == "question":
            context = Context()
            context.add("workspace", workspace_summary(workspace))
            context.add("question", text)
        else:
            raise RpcError(INVALID_PARAMS, f"unknown context kind {kind!r}")
        with self._lock:
            ident = self._remember(self._contexts, context)
        provider = self.provider()
        return {"id": ident, "provider": provider.name, "available": provider.is_available(), "total": context.chars, "redactions": context.redactions,
                "items": [{"label": i.label, "chars": i.chars, "redactions": i.redactions} for i in context.items], "skipped": context.skipped,
                "text": context.render()}

    def _stored(self, ident: str) -> Context:
        with self._lock:
            context = self._contexts.get(ident)
        if context is None:
            raise RpcError(INVALID_PARAMS, "unknown context: ask for it again (contexts are shown before they are sent)")
        return context

    def _ready(self) -> AIProvider:
        provider = self.provider()
        if not provider.is_available():
            raise RpcError(NOT_AVAILABLE, "[CH8020] The AI assistant is not available: " + provider.complete("").strip(), {"code": "CH8020"})
        return provider

    def send(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a context the user has seen. mode: "explain" | "ask" (answers in text) | "fix" (a diff, checked against the files)."""
        context = self._stored(str(params.get("id", "")))
        mode = str(params.get("mode", "explain"))
        provider = self._ready()
        if mode == "fix":
            try:
                proposal = fix_mod.request_fix(provider, context, self.state.root)
            except patch_mod.PatchError as exc:
                raise RpcError(INVALID_PARAMS, f"[CH8021] The proposed change cannot be used: {exc}", {"code": "CH8021"}) from exc
            with self._lock:
                ident = self._remember(self._proposals, proposal)
            return {"mode": "fix", "proposal": ident, "explanation": proposal.explanation, "files": proposal.files,
                    "diff": patch_mod.unified(self.state.root, proposal.contents)}
        if mode not in ("explain", "ask"):
            raise RpcError(INVALID_PARAMS, f"unknown mode {mode!r}")
        suffix = "Explain the cause and give the fix." if mode == "explain" else "Answer the question."
        try:
            answer = provider.complete(context.render() + "\n\n" + suffix, system=EXPLAIN_SYSTEM)
        except Exception as exc:                                # network, quota, provider bugs: reported, never fatal
            raise RpcError(NOT_AVAILABLE, f"The assistant could not answer: {type(exc).__name__}: {exc}") from exc
        return {"mode": mode, "answer": answer}

    def apply(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write a proposal the user approved, rebuild, keep it only if the build passes (else restore), then run the quality gate."""
        with self._lock:
            proposal = self._proposals.get(str(params.get("proposal", "")))
        if proposal is None:
            raise RpcError(INVALID_PARAMS, "unknown proposal")
        root = self.state.root

        def verify() -> Tuple[bool, str]:
            self.state.load()
            ok, results, diagnostics = self.state.compile(list(self.state.own_targets()), config=str(params.get("config", "Debug")))
            failed = "\n".join(f"[{r['target']}] {r['error']}" for r in results if not r["ok"] and r["error"])
            return ok, failed or "\n".join(d.get("message", "") for d in diagnostics)

        kept, output = fix_mod.apply_verified(root, proposal, verify)
        result: Dict[str, Any] = {"kept": kept, "output": output[-2000:], "files": proposal.files}
        if kept:
            with self._lock:
                self._proposals.pop(str(params.get("proposal", "")), None)
            try:
                result["gate"] = self.state.check(level="rapide")
            except ChError as exc:
                result["gate"] = {"ok": False, "error": exc.message, "findings": []}
        else:
            self.state.load()
        return result


def register(d: Dispatcher, state: ServerState, select: Optional[Callable[[], AIProvider]] = None) -> AiApi:
    api = AiApi(state, select or select_provider)

    def method(name: str, fn: Callable[[Dict[str, Any]], Any]) -> None:
        def call(params: Any) -> Any:
            if params is not None and not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            return fn(params or {})
        d.add_method(name, call)

    method("charpente/ai/status", api.status)
    method("charpente/ai/context", api.context)
    method("charpente/ai/send", api.send)
    method("charpente/ai/apply", api.apply)
    return api
