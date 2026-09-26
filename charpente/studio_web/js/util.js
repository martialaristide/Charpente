// Small helpers shared by every panel. Pure functions are exported separately so they can be tested without a browser.

/** Build a DOM element: h("button", {class: "x", onclick: fn, "aria-label": "…"}, "text", childElement). */
export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on") && typeof value === "function") element.addEventListener(name.slice(2), value);
    else if (name === "class") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (value === true) element.setAttribute(name, "");
    else element.setAttribute(name, String(value));
  }
  append(element, children);
  return element;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(element) {
  while (element.firstChild) element.removeChild(element.firstChild);
  return element;
}

export function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.flush = (...args) => {
    clearTimeout(timer);
    fn(...args);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

export function formatSeconds(value) {
  if (!Number.isFinite(value)) return "–";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`;
}

export function formatBytes(value) {
  if (!Number.isFinite(value)) return "–";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Split a command line into an argument list, the way a person means it: spaces separate, "double" and 'single' quotes group,
 * a backslash escapes inside double quotes. No pipes, redirections or variables: the server runs the list without a shell.
 * Throws Error on an unterminated quote.
 */
export function splitCommandLine(text) {
  const args = [];
  let current = "";
  let started = false;
  let quote = null;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
      else if (ch === "\\" && quote === '"' && (text[i + 1] === '"' || text[i + 1] === "\\")) current += text[++i];
      else current += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      started = true;
    } else if (/\s/.test(ch)) {
      if (started) {
        args.push(current);
        current = "";
        started = false;
      }
    } else {
      current += ch;
      started = true;
    }
  }
  if (quote) throw new Error(`unterminated ${quote}`);
  if (started) args.push(current);
  return args;
}

/** "file.cpp:12:5" or "C:\\x\\file.cpp(12,5)" inside a line of compiler output → {file, line, column} (or null). */
export function parseLocation(text) {
  const gnu = /((?:[A-Za-z]:)?[^\s:()"'<>|]+\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inl|charpente|py|toml|md|txt)):(\d+)(?::(\d+))?/i.exec(text);
  if (gnu) return { file: gnu[1], line: Number(gnu[2]), column: gnu[3] ? Number(gnu[3]) : 1, index: gnu.index, length: gnu[0].length };
  const msvc = /((?:[A-Za-z]:)?[^\s:()"'<>|]+\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inl))\((\d+)(?:,(\d+))?\)/i.exec(text);
  if (msvc) return { file: msvc[1], line: Number(msvc[2]), column: msvc[3] ? Number(msvc[3]) : 1, index: msvc.index, length: msvc[0].length };
  return null;
}

/** Make a path relative to the project root when it lies inside it (for opening files from compiler output). */
export function relativeToRoot(path, root) {
  const normal = String(path).replace(/\\/g, "/");
  const base = String(root || "").replace(/\\/g, "/").replace(/\/+$/, "");
  if (base && normal.toLowerCase().startsWith(base.toLowerCase() + "/")) return normal.slice(base.length + 1);
  return normal.replace(/^\.\//, "");
}

export function fileUriToPath(uri) {
  const url = new URL(uri);
  let path = decodeURIComponent(url.pathname);
  if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1);
  return path;
}

export function pathToFileUri(path) {
  const normal = String(path).replace(/\\/g, "/");
  const prefixed = normal.startsWith("/") ? normal : `/${normal}`;
  return "file://" + prefixed.split("/").map((p) => encodeURIComponent(p).replace(/%3A/g, ":")).join("/");
}

/** A tiny event emitter for the panels: `on(name, fn)` returns an unsubscribe function. */
export class Emitter {
  constructor() {
    this.listeners = new Map();
  }

  on(name, fn) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(fn);
    return () => this.listeners.get(name).delete(fn);
  }

  emit(name, detail) {
    for (const fn of [...(this.listeners.get(name) || [])]) {
      try {
        fn(detail);
      } catch (error) {
        console.error(`listener for ${name} failed`, error);
      }
    }
  }
}
