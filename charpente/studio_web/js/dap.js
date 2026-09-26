// A minimal Debug Adapter Protocol client over the server's `charpente/debug/*` relay. Only what the debug panel uses.
import { Emitter } from "./util.js";

export class DapClient extends Emitter {
  constructor(rpc) {
    super();
    this.rpc = rpc;
    this.session = null;
    this.seq = 0;
    this.pending = new Map();
    this.off = null;
    this.debugger = "";
  }

  get active() {
    return this.session !== null;
  }

  /** Start the adapter and run the DAP handshake. `configure()` runs when the debugger is ready for breakpoints (before the program starts). */
  async start({ target, config, args }, configure) {
    const started = await this.rpc.request("charpente/debug/start", {});
    this.session = started.id;
    this.debugger = started.debugger;
    this.off = this.rpc.on("charpente/dap", (message) => this.receive(message));
    try {
      await this.request("initialize", { adapterID: "charpente", clientID: "charpente-studio", linesStartAt1: true, columnsStartAt1: true, pathFormat: "path",
        supportsVariableType: true });
      const initialized = this.waitFor("initialized");
      const launched = this.request("launch", { target, config, args });
      launched.catch(() => {}); // a refused launch is reported by the await below; do not leave it unhandled meanwhile
      await Promise.race([initialized, launched]);
      if (configure) await configure(this);
      await this.request("configurationDone", {});
      await launched;
    } catch (error) {
      await this.stop();
      throw error;
    }
  }

  waitFor(event) {
    return new Promise((resolve) => {
      const off = this.on(event, (body) => {
        off();
        resolve(body);
      });
    });
  }

  request(command, args = {}) {
    return new Promise((resolve, reject) => {
      if (!this.session) {
        reject(new Error("no debugging session"));
        return;
      }
      const seq = ++this.seq;
      this.pending.set(seq, { resolve, reject, command });
      this.rpc.request("charpente/debug/send", { id: this.session, message: { seq, type: "request", command, arguments: args } }).catch((error) => {
        this.pending.delete(seq);
        reject(error);
      });
    });
  }

  receive({ id, message, exit }) {
    if (id !== this.session) return;
    if (exit !== undefined) {
      this.finish(exit);
      return;
    }
    if (message.type === "response") {
      const waiting = this.pending.get(message.request_seq);
      if (!waiting) return;
      this.pending.delete(message.request_seq);
      if (message.success) waiting.resolve(message.body || {});
      else waiting.reject(new Error(message.message || `${waiting.command} failed`));
    } else if (message.type === "event") {
      this.emit(message.event, message.body || {});
    }
  }

  finish(code) {
    const error = new Error("the debugging session ended");
    for (const { reject } of this.pending.values()) reject(error);
    this.pending.clear();
    if (this.off) this.off();
    this.off = null;
    this.session = null;
    this.emit("ended", { code });
  }

  async stop() {
    const id = this.session;
    if (!id) return;
    try {
      await Promise.race([this.request("disconnect", { terminateDebuggee: true }), new Promise((resolve) => setTimeout(resolve, 3000))]);
    } catch {
      /* the adapter may already be gone */
    }
    await this.rpc.request("charpente/debug/stop", { id }).catch(() => {});
    if (this.session === id) this.finish(0);
  }

  setBreakpoints(path, lines) {
    return this.request("setBreakpoints", { source: { path }, breakpoints: lines.map((line) => ({ line })) });
  }

  threads() { return this.request("threads"); }
  stackTrace(threadId) { return this.request("stackTrace", { threadId }); }
  scopes(frameId) { return this.request("scopes", { frameId }); }
  variables(variablesReference) { return this.request("variables", { variablesReference }); }
  continue(threadId) { return this.request("continue", { threadId }); }
  next(threadId) { return this.request("next", { threadId }); }
  stepIn(threadId) { return this.request("stepIn", { threadId }); }
  stepOut(threadId) { return this.request("stepOut", { threadId }); }
  pause(threadId) { return this.request("pause", { threadId }); }
  evaluate(expression, frameId) { return this.request("evaluate", { expression, frameId, context: "watch" }); }
}
