"""A small Debug Adapter Protocol client for the tests: talks to `charpente debug-adapter` (or any DAP server) over stdio."""
import queue
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from charpente.serve import rpc


class DapClient:
    def __init__(self, argv: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None) -> None:
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
        self.messages: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.log: List[Dict[str, Any]] = []
        self.stderr = b""
        self.seq = 0
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()

    def _pump(self) -> None:
        try:
            while (message := rpc.read_message(self.proc.stdout)) is not None:
                self.log.append(message)
                self.messages.put(message)
        except Exception as exc:
            self.messages.put({"type": "pump-error", "error": repr(exc)})

    def _drain(self) -> None:
        self.stderr = self.proc.stderr.read()

    def send(self, command: str, arguments: Optional[Dict[str, Any]] = None) -> int:
        self.seq += 1
        message: Dict[str, Any] = {"seq": self.seq, "type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        self.proc.stdin.write(rpc.encode_message(message))
        self.proc.stdin.flush()
        return self.seq

    def wait(self, predicate, timeout: float = 90, what: str = "a message") -> Dict[str, Any]:
        end = time.time() + timeout
        seen: List[Dict[str, Any]] = []
        while time.time() < end:
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if predicate(message):
                for skipped in reversed(seen):                                      # keep what we passed over for later waits
                    self._requeue(skipped)
                return message
            seen.append(message)
        raise TimeoutError(f"timed out waiting for {what}; got {[(m.get('type'), m.get('event') or m.get('command')) for m in seen][-12:]}; stderr={self.stderr[-500:]!r}")

    def _requeue(self, message: Dict[str, Any]) -> None:
        pending = list(self.messages.queue)
        self.messages.queue.clear()
        self.messages.put(message)
        for m in pending:
            self.messages.put(m)

    def response(self, request_seq: int, timeout: float = 90) -> Dict[str, Any]:
        return self.wait(lambda m: m.get("type") == "response" and m.get("request_seq") == request_seq, timeout, f"the response to request {request_seq}")

    def request(self, command: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = 90) -> Dict[str, Any]:
        return self.response(self.send(command, arguments), timeout)

    def event(self, name: str, timeout: float = 90) -> Dict[str, Any]:
        return self.wait(lambda m: m.get("type") == "event" and m.get("event") == name, timeout, f"the {name} event")

    def output(self) -> str:
        return "".join(m["body"]["output"] for m in self.log if m.get("type") == "event" and m.get("event") == "output")

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=30)
