// JSON-RPC 2.0 over one WebSocket to `charpente studio` / `charpente serve --ws`.

export class RpcError extends Error {
  constructor(message, code, data) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data;
  }
}

export class Rpc {
  /** `url` is the ws:// address including ?token=…; `WebSocketImpl` lets tests inject a fake. */
  constructor(url, WebSocketImpl = globalThis.WebSocket) {
    this.url = url;
    this.WebSocketImpl = WebSocketImpl;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map(); // method → [callback]
    this.statusListeners = [];
    this.socket = null;
    this.status = "closed";
    this.streamHandlers = new Map();
    this.streamBacklog = new Map();
    // A stream's first messages can arrive before the reply that tells us its id: keep them until someone claims the id.
    this.on("charpente/stream", (message) => {
      const handler = this.streamHandlers.get(message.id);
      if (handler) {
        handler(message);
        return;
      }
      const backlog = this.streamBacklog.get(message.id) || [];
      if (backlog.length < 2000) backlog.push(message);
      this.streamBacklog.set(message.id, backlog);
    });
  }

  /** Receive the messages of stream `id` (those already buffered first). Returns a function that stops receiving. */
  claimStream(id, handler) {
    this.streamHandlers.set(id, handler);
    const backlog = this.streamBacklog.get(id) || [];
    this.streamBacklog.delete(id);
    for (const message of backlog) handler(message);
    return () => this.streamHandlers.delete(id);
  }

  onStatus(listener) {
    this.statusListeners.push(listener);
  }

  on(method, callback) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(callback);
    return () => this.handlers.set(method, this.handlers.get(method).filter((c) => c !== callback));
  }

  setStatus(status) {
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.setStatus("connecting");
      const socket = new this.WebSocketImpl(this.url);
      this.socket = socket;
      let opened = false;
      socket.onopen = () => {
        opened = true;
        this.setStatus("open");
        resolve();
      };
      socket.onmessage = (event) => this.receive(String(event.data));
      socket.onerror = () => {
        if (!opened) reject(new Error("cannot connect to the Charpente server"));
      };
      socket.onclose = () => {
        this.setStatus("closed");
        const error = new Error("the connection to the Charpente server was closed");
        for (const { reject: fail } of this.pending.values()) fail(error);
        this.pending.clear();
        if (!opened) reject(error);
      };
    });
  }

  receive(text) {
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (message.method !== undefined && message.id === undefined) {
      for (const callback of this.handlers.get(message.method) || []) {
        try {
          callback(message.params);
        } catch (error) {
          console.error("notification handler failed", message.method, error);
        }
      }
    } else if (message.id !== undefined && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new RpcError(message.error.message, message.error.code, message.error.data));
      else resolve(message.result);
    }
  }

  request(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.socket || this.status !== "open") {
        reject(new Error("not connected to the Charpente server"));
        return;
      }
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  notify(method, params = {}) {
    if (this.socket && this.status === "open") this.socket.send(JSON.stringify({ jsonrpc: "2.0", method, params }));
  }

  close() {
    if (this.socket) this.socket.close();
  }
}
