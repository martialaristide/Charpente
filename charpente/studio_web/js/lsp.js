// A minimal LSP client (clangd) speaking through the server's `charpente/lsp*` relay. Only what the editor uses:
// open/change/close, diagnostics, completion, hover, definition, rename, formatting.
import { fileUriToPath, pathToFileUri } from "./util.js";

const SEVERITY = ["error", "error", "warning", "information", "hint"]; // LSP severities are 1..4

const COMPLETION_KIND = { 2: "method", 3: "method", 4: "method", 5: "word", 6: "word", 7: "class", 8: "class", 9: "class", 10: "word", 14: "keyword", 21: "word", 22: "class" };

export class LspClient {
  constructor(rpc, root) {
    this.rpc = rpc;
    this.root = root; // absolute project path
    this.session = null;
    this.nextId = 1;
    this.pending = new Map();
    this.versions = new Map();
    this.listeners = { diagnostics: [], exit: [] };
    this.ready = false;
    this.off = rpc.on("charpente/lsp", (params) => this.receive(params));
  }

  on(event, callback) {
    this.listeners[event].push(callback);
  }

  emit(event, ...args) {
    for (const callback of this.listeners[event]) callback(...args);
  }

  uri(path) {
    const absolute = /^([A-Za-z]:)?[\\/]/.test(path) ? path : `${this.root.replace(/[\\/]+$/, "")}/${path}`;
    return pathToFileUri(absolute);
  }

  async start(config = "Debug") {
    const started = await this.rpc.request("charpente/lsp/start", { config });
    this.session = started.id;
    const result = await this.request("initialize", {
      processId: null,
      rootUri: pathToFileUri(this.root),
      capabilities: {
        textDocument: {
          synchronization: { didSave: false },
          completion: { completionItem: { snippetSupport: false } },
          hover: { contentFormat: ["plaintext", "markdown"] },
          publishDiagnostics: {},
          rename: { prepareSupport: false },
        },
        workspace: { workspaceEdit: { documentChanges: false } },
      },
    });
    this.notify("initialized", {});
    this.ready = true;
    return { server: started.server, capabilities: result.capabilities };
  }

  request(method, params) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      this.rpc.request("charpente/lsp/send", { id: this.session, message: { jsonrpc: "2.0", id, method, params } }).catch((error) => {
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  notify(method, params) {
    return this.rpc.request("charpente/lsp/send", { id: this.session, message: { jsonrpc: "2.0", method, params } }).catch(() => {});
  }

  receive({ id, message, exit }) {
    if (id !== this.session) return;
    if (exit !== undefined) {
      this.ready = false;
      this.emit("exit", exit);
      return;
    }
    if (message.id !== undefined && message.method === undefined) {
      const waiting = this.pending.get(message.id);
      if (!waiting) return;
      this.pending.delete(message.id);
      if (message.error) waiting.reject(new Error(message.error.message));
      else waiting.resolve(message.result);
    } else if (message.method === "textDocument/publishDiagnostics") {
      const path = fileUriToPath(message.params.uri);
      this.emit("diagnostics", path, message.params.diagnostics.map((d) => ({
        line: d.range.start.line, character: d.range.start.character, severity: SEVERITY[d.severity || 1], message: d.message, source: d.source || "clangd",
      })));
    } else if (message.id !== undefined && message.method) {
      // a request from the server (e.g. workDoneProgress/create): answer "no result" so it does not wait for us
      this.rpc.request("charpente/lsp/send", { id: this.session, message: { jsonrpc: "2.0", id: message.id, result: null } }).catch(() => {});
    }
  }

  languageId(path) {
    return /\.(c)$/i.test(path) ? "c" : "cpp";
  }

  open(path, text) {
    this.versions.set(path, 1);
    return this.notify("textDocument/didOpen", { textDocument: { uri: this.uri(path), languageId: this.languageId(path), version: 1, text } });
  }

  change(path, text) {
    const version = (this.versions.get(path) || 1) + 1;
    this.versions.set(path, version);
    return this.notify("textDocument/didChange", { textDocument: { uri: this.uri(path), version }, contentChanges: [{ text }] });
  }

  close(path) {
    this.versions.delete(path);
    return this.notify("textDocument/didClose", { textDocument: { uri: this.uri(path) } });
  }

  position(path, line, column) {
    return { textDocument: { uri: this.uri(path) }, position: { line: line - 1, character: column - 1 } };
  }

  async completion(path, line, column) {
    const result = await this.request("textDocument/completion", this.position(path, line, column));
    const list = Array.isArray(result) ? result : (result && result.items) || [];
    return list.slice(0, 80).map((item) => ({
      label: item.filterText || item.label.trim(), detail: item.detail || "", insertText: (item.textEdit && item.textEdit.newText) || item.insertText || item.label.trim(),
      kind: COMPLETION_KIND[item.kind] || "word",
    }));
  }

  async hover(path, line, column) {
    const result = await this.request("textDocument/hover", this.position(path, line, column));
    if (!result || !result.contents) return "";
    const c = result.contents;
    return Array.isArray(c) ? c.map((x) => x.value || x).join("\n") : c.value || String(c);
  }

  async definition(path, line, column) {
    const result = await this.request("textDocument/definition", this.position(path, line, column));
    const first = Array.isArray(result) ? result[0] : result;
    if (!first) return null;
    const target = first.uri || first.targetUri;
    const range = first.range || first.targetSelectionRange;
    return { path: fileUriToPath(target), line: range.start.line + 1, column: range.start.character + 1 };
  }

  /** {path: [{range, newText}]} for renaming the symbol at the position. */
  async rename(path, line, column, newName) {
    const result = await this.request("textDocument/rename", { ...this.position(path, line, column), newName });
    const edits = {};
    for (const [uri, list] of Object.entries((result && result.changes) || {})) edits[fileUriToPath(uri)] = list;
    return edits;
  }

  stop() {
    this.off();
    if (this.session) return this.rpc.request("charpente/lsp/stop", { id: this.session }).catch(() => {});
    return Promise.resolve();
  }
}

/** Apply LSP text edits (line/character ranges) to a text; edits are applied from the end so earlier offsets stay valid. */
export function applyEdits(text, edits) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  const offset = (position) => Math.min((starts[position.line] ?? text.length) + position.character, text.length);
  const ordered = [...edits].sort((a, b) => offset(b.range.start) - offset(a.range.start));
  let result = text;
  for (const edit of ordered) result = result.slice(0, offset(edit.range.start)) + edit.newText + result.slice(offset(edit.range.end));
  return result;
}
