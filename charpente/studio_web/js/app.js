// Charpente Studio: wires the panels, the editor and the connection to `charpente studio` together.
import { complete } from "./complete.js";
import { Editor } from "./editor.js";
import { DSL_NAMES, setDslNames } from "./highlight.js";
import { getLang, setLang, t, translatePage, LANGS } from "./i18n.js";
import { LspClient, applyEdits } from "./lsp.js";
import { mountAi } from "./panels/ai.js";
import { mountBuild } from "./panels/build.js";
import { mountDebug } from "./panels/debug.js";
import { mountDevices } from "./panels/devices.js";
import { mountFiles } from "./panels/files.js";
import { mountGit } from "./panels/git.js";
import { mountGraph } from "./panels/graph.js";
import { mountOptions } from "./panels/options.js";
import { mountPackages } from "./panels/packages.js";
import { mountProblems } from "./panels/problems.js";
import { mountProfile } from "./panels/profile.js";
import { mountTargets } from "./panels/targets.js";
import { mountTerminal } from "./panels/terminal.js";
import { Rpc } from "./rpc.js";
import { Emitter, clear, debounce, fileUriToPath, h, relativeToRoot } from "./util.js";

const CONFLICT = -32011;
const $ = (id) => document.getElementById(id);

function connectionUrl() {
  const params = new URLSearchParams(location.search);
  let token = params.get("token");
  try {
    if (token) {
      sessionStorage.setItem("charpente-token", token);
      history.replaceState(null, "", location.pathname); // the token does not stay in the address bar or the history
    } else {
      token = sessionStorage.getItem("charpente-token");
    }
  } catch {
    /* storage can be unavailable: the token from the URL is still used for this load */
  }
  return token ? `ws://${location.host}/?token=${encodeURIComponent(token)}` : null;
}

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* not persisted */
  }
}

export async function start() {
  translatePage();
  applyTheme(stored("charpente-theme", "auto"));
  const url = connectionUrl();
  if (!url) {
    $("boot").textContent = t("boot.noToken");
    return null;
  }
  const rpc = new Rpc(url);
  const bus = new Emitter();
  const ctx = {
    rpc, bus, t,
    info: null, targets: [], graph: null, root: "",
    targetStatus: new Map(), diagnostics: new Map(), activePath: null, busy: false, schema: null, breakpoints: new Map(),
    config: () => $("config").value,
    platform: () => $("platform").value.trim(),
    kindOf: (name) => (ctx.graph && (ctx.graph.nodes.find((n) => n.name === name) || {}).kind) || "",
    nameOf: (uri) => { const target = ctx.targets.find((x) => x.id.uri === uri); return target ? target.displayName : new URL(uri).searchParams.get("id") || uri; },
  };
  window.studio = ctx; // handy in the browser console, and used by the end-to-end tests

  // ------------------------------------------------------------------ small UI services
  ctx.toast = (text, kind = "info") => {
    const toast = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, text);
    $("toasts").append(toast);
    setTimeout(() => toast.remove(), kind === "error" ? 9000 : 3500);
  };
  ctx.ask = (title, placeholder = "", value = "") => new Promise((resolve) => {
    const input = h("input", { type: "text", placeholder, value, "aria-label": title });
    const dialog = $("modal");
    const finish = (result) => { dialog.close(); resolve(result); };
    clear(dialog).append(h("form", { method: "dialog", onsubmit: (e) => { e.preventDefault(); finish(input.value); } },
      h("label", {}, title, input), h("div", { class: "buttons" }, h("button", { type: "button", onclick: () => finish(null) }, t("cancel")), h("button", { class: "primary", type: "submit" }, t("ok")))));
    dialog.addEventListener("cancel", () => resolve(null), { once: true });
    dialog.showModal();
    input.focus();
  });
  ctx.confirm = (message, yes = t("ok")) => new Promise((resolve) => {
    const dialog = $("modal");
    const finish = (result) => { dialog.close(); resolve(result); };
    clear(dialog).append(h("div", {}, h("p", {}, message), h("div", { class: "buttons" }, h("button", { onclick: () => finish(false) }, t("cancel")), h("button", { class: "primary", onclick: () => finish(true) }, yes))));
    dialog.addEventListener("cancel", () => resolve(false), { once: true });
    dialog.showModal();
  });

  // ------------------------------------------------------------------ connection
  rpc.onStatus((status) => {
    $("connection").dataset.status = status;
    $("connection").title = t(`connection.${status}`);
    $("connection").textContent = status === "open" ? "●" : "○";
    if (status === "closed") ctx.toast(t("connection.lost"), "error");
  });
  try {
    await rpc.connect();
  } catch (error) {
    $("boot").textContent = `${t("boot.failed")} ${error.message}`;
    return null;
  }
  await rpc.request("build/initialize", { displayName: "charpente-studio", version: "1", bspVersion: "2.1.0", capabilities: { languageIds: ["c", "cpp"] } });
  rpc.notify("build/initialized", {});
  await rpc.request("charpente/subscribe");

  // ------------------------------------------------------------------ project state
  async function loadInfo() {
    try {
      ctx.info = await rpc.request("charpente/workspace");
      ctx.root = ctx.info.root;
    } catch (error) {
      ctx.info = { name: "", root: ctx.root, options: {}, requires: [], configurations: ["Debug", "Release"], platforms: [] };
      ctx.toast(error.message, "error");
    }
    $("project").textContent = ctx.info.name || t("workspace.notLoaded");
    const configs = (ctx.info.configurations && ctx.info.configurations.length ? ctx.info.configurations : ["Debug", "Release"]);
    const current = $("config").value || stored("charpente-config", "Debug");
    clear($("config")).append(...configs.map((c) => h("option", { value: c, selected: c === current }, c)));
    bus.emit("info-changed");
  }
  ctx.refreshTargets = async () => {
    try {
      ctx.targets = (await rpc.request("workspace/buildTargets")).targets;
      ctx.graph = await rpc.request("charpente/graph");
    } catch {
      ctx.targets = [];
      ctx.graph = null;
    }
    bus.emit("targets-changed");
  };
  async function loadSchema() {
    try {
      ctx.schema = await rpc.request("charpente/dsl/schema");
      setDslNames(Object.keys(ctx.schema.classes).concat(Object.keys(ctx.schema.enums)),
        [...new Set(Object.values(ctx.schema.classes).flat().map((m) => m.name))].filter((n) => /^\w+$/.test(n)));
    } catch {
      setDslNames(DSL_NAMES.classes, DSL_NAMES.methods);
    }
  }

  // ------------------------------------------------------------------ editor and open files
  const files = new Map(); // path → {text, sha, language, dirty, view}
  let lsp = null;
  let lspTried = false;
  const editor = new Editor($("editor-host"), {
    label: t("editor.label"),
    onChange: (text) => onEdit(text),
    onSave: () => save(),
    onCursor: ({ line, column }) => ($("cursor").textContent = `${t("status.line")} ${line}, ${t("status.column")} ${column}`),
    complete: (text, offset, language, explicit) => completions(text, offset, language, explicit),
    hover: ({ line, column }) => (lsp && lsp.ready && isCpp(ctx.activePath) ? lsp.hover(ctx.activePath, line, column) : ""),
    onDefinition: ({ line, column }) => gotoDefinition(line, column),
    onBreakpoint: (line) => ctx.activePath && ctx.toggleBreakpoint(ctx.activePath, line),
  });
  // Breakpoints belong to the project and survive reloads (they are kept in this browser, per project folder).
  const breakpointKey = () => `charpente-breakpoints:${ctx.root}`;
  function loadBreakpoints() {
    try {
      const saved = JSON.parse(localStorage.getItem(breakpointKey()) || "{}");
      ctx.breakpoints = new Map(Object.entries(saved).map(([path, lines]) => [path, new Set(lines)]));
    } catch {
      ctx.breakpoints = new Map();
    }
  }
  ctx.toggleBreakpoint = (path, line) => {
    const lines = ctx.breakpoints.get(path) || new Set();
    if (lines.has(line)) lines.delete(line);
    else lines.add(line);
    if (lines.size) ctx.breakpoints.set(path, lines);
    else ctx.breakpoints.delete(path);
    try {
      localStorage.setItem(breakpointKey(), JSON.stringify(Object.fromEntries([...ctx.breakpoints].map(([p, l]) => [p, [...l]]))));
    } catch {
      /* not persisted */
    }
    if (path === ctx.activePath) editor.setBreakpoints(lines);
    bus.emit("breakpoints-changed", { path });
  };
  bus.on("execution-line", (where) => {
    if (!where) editor.setExecutionLine(null);
    else if (where.path === ctx.activePath) editor.setExecutionLine(where.line);
  });
  const isCpp = (path) => /\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl)$/i.test(path || "");

  const syncLsp = debounce((path, text) => { if (lsp && lsp.ready && isCpp(path)) lsp.change(path, text); }, 300);
  function onEdit(text) {
    const file = files.get(ctx.activePath);
    if (!file) return;
    file.dirty = editor.getText() !== file.text;
    renderTabs();
    syncLsp(ctx.activePath, text);
  }

  async function completions(text, offset, language, explicit) {
    if (lsp && lsp.ready && isCpp(ctx.activePath)) {
      const before = text.slice(0, offset);
      const line = before.split("\n").length;
      const column = offset - (before.lastIndexOf("\n") + 1) + 1;
      try {
        const items = await lsp.completion(ctx.activePath, line, column);
        const word = /[A-Za-z0-9_]*$/.exec(before)[0];
        if (items.length) return { from: offset - word.length, items: items.filter((i) => i.label.toLowerCase().startsWith(word.toLowerCase())).slice(0, 50) };
      } catch {
        /* fall back to words */
      }
    }
    return complete(text, offset, language, ctx.schema);
  }

  async function ensureLsp() {
    if (lsp || lspTried) return;
    lspTried = true;
    try {
      const client = new LspClient(rpc, ctx.root);
      client.on("diagnostics", (path, list) => {
        const relative = relativeToRoot(path, ctx.root);
        const map = ctx.diagnostics.get("clangd") || new Map();
        map.set(relative, list);
        ctx.diagnostics.set("clangd", map);
        updateDiagnostics();
      });
      client.on("exit", () => { $("lsp").textContent = t("lsp.stopped"); lsp = null; });
      const started = await client.start(ctx.config());
      lsp = client;
      $("lsp").textContent = `${started.server} ✓`;
      for (const [path, file] of files) if (isCpp(path)) client.open(path, path === ctx.activePath ? editor.getText() : file.text);
    } catch (error) {
      $("lsp").textContent = t("lsp.unavailable");
      $("lsp").title = error.message;
    }
  }

  async function gotoDefinition(line, column) {
    if (!(lsp && lsp.ready && isCpp(ctx.activePath))) return ctx.toast(t("lsp.unavailable"), "info");
    const found = await lsp.definition(ctx.activePath, line, column).catch(() => null);
    if (found) openFile(relativeToRoot(found.path, ctx.root), found.line, found.column);
    else ctx.toast(t("lsp.noDefinition"), "info");
  }

  async function renameSymbol() {
    if (!(lsp && lsp.ready && isCpp(ctx.activePath))) return ctx.toast(t("lsp.unavailable"), "info");
    const { selectionStart } = editor.input;
    const before = editor.input.value.slice(0, selectionStart);
    const line = before.split("\n").length;
    const column = selectionStart - (before.lastIndexOf("\n") + 1) + 1;
    const name = await ctx.ask(t("lsp.renameTo"));
    if (!name) return;
    try {
      const edits = await lsp.rename(ctx.activePath, line, column, name);
      let changed = 0;
      for (const [absolute, list] of Object.entries(edits)) {
        const path = relativeToRoot(absolute, ctx.root);
        const open = files.get(path);
        const current = open ? (path === ctx.activePath ? editor.getText() : open.text) : (await rpc.request("charpente/files/read", { path })).text;
        const updated = applyEdits(current, list);
        if (open) {
          if (path === ctx.activePath) editor.setText(updated);
          open.text = open.text; // unchanged on disk until saved
          open.pending = updated;
          open.dirty = true;
        } else {
          await rpc.request("charpente/files/write", { path, text: updated });
        }
        changed += list.length;
      }
      renderTabs();
      ctx.toast(t("lsp.renamed", { count: changed }), "info");
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  async function openFile(path, line = 0, column = 1) {
    if (!path) return;
    if (ctx.activePath === path && files.has(path)) {
      if (line) editor.goTo(line, column);
      return;
    }
    stash();
    if (!files.has(path)) {
      try {
        const data = await rpc.request("charpente/files/read", { path });
        files.set(path, { text: data.text, sha: data.sha256, language: data.language, dirty: false, view: null });
      } catch (error) {
        ctx.toast(`${path}: ${error.message}`, "error");
        return;
      }
      const file = files.get(path);
      if (lsp && lsp.ready && isCpp(path)) lsp.open(path, file.text);
    }
    activate(path);
    if (line) editor.goTo(line, column);
    if (isCpp(path)) ensureLsp();
  }
  ctx.openFile = openFile;

  function stash() {
    const file = files.get(ctx.activePath);
    if (file) file.pending = editor.getText();
  }

  function activate(path) {
    const file = files.get(path);
    ctx.activePath = path;
    editor.open({ text: file.pending ?? file.text, language: file.language });
    editor.setBreakpoints(ctx.breakpoints.get(path) || []);
    file.dirty = editor.getText() !== file.text;
    $("editor-empty").hidden = true;
    $("editor-host").hidden = false;
    $("language").textContent = file.language;
    $("eol").textContent = editor.eol === "\r\n" ? "CRLF" : "LF";
    updateDiagnostics();
    renderTabs();
    bus.emit("active-file", path);
    editor.focus();
  }

  function renderTabs() {
    const tabs = $("tabs");
    clear(tabs);
    for (const [path, file] of files) {
      const name = path.split("/").pop();
      tabs.append(h("div", { class: `tab${path === ctx.activePath ? " active" : ""}${file.dirty ? " dirty" : ""}`, role: "tab", "aria-selected": String(path === ctx.activePath), title: path },
        h("button", { class: "tab-name", onclick: () => switchTo(path) }, name, file.dirty ? h("span", { class: "dot", "aria-label": t("editor.unsaved") }, " ●") : null),
        h("button", { class: "tab-close", "aria-label": `${t("close")} ${name}`, onclick: () => closeFile(path) }, "✕")));
    }
  }

  function switchTo(path) {
    if (path === ctx.activePath) return;
    stash();
    activate(path);
  }

  async function closeFile(path) {
    const file = files.get(path);
    if (file && (path === ctx.activePath ? editor.getText() !== file.text : file.pending !== undefined && file.pending !== file.text)) {
      if (!(await ctx.confirm(t("editor.discard", { name: path }), t("editor.discardYes")))) return;
    }
    files.delete(path);
    if (lsp && lsp.ready && isCpp(path)) lsp.close(path);
    if (ctx.activePath === path) {
      const next = [...files.keys()].pop();
      ctx.activePath = null;
      if (next) activate(next);
      else {
        $("editor-empty").hidden = false;
        $("editor-host").hidden = true;
        $("language").textContent = "";
        renderTabs();
      }
    } else {
      renderTabs();
    }
  }

  async function save(path = ctx.activePath, { quiet = false } = {}) {
    const file = files.get(path);
    if (!file) return false;
    let text = path === ctx.activePath ? editor.getText() : file.pending ?? file.text;
    if (path === ctx.activePath && stored("charpente-format", "1") === "1" && file.language === "cpp") {
      try {
        const formatted = await rpc.request("charpente/format", { path, text });
        if (formatted.available && !formatted.error && formatted.text !== text) {
          text = formatted.text;
          editor.setText(text);
        }
      } catch {
        /* formatting is a convenience: save what the user wrote */
      }
    }
    try {
      const result = await rpc.request("charpente/files/write", { path, text, expected: file.sha });
      file.text = text;
      file.sha = result.sha256;
      file.pending = undefined;
      file.dirty = false;
    } catch (error) {
      if (error.code === CONFLICT) {
        if (!(await ctx.confirm(t("editor.conflict", { name: path }), t("editor.overwrite")))) return false;
        const result = await rpc.request("charpente/files/write", { path, text });
        file.text = text;
        file.sha = result.sha256;
        file.pending = undefined;
        file.dirty = false;
      } else {
        ctx.toast(error.message, "error");
        return false;
      }
    }
    renderTabs();
    if (!quiet) ctx.toast(t("editor.saved", { name: path }), "info");
    bus.emit("files-saved", path);
    if (path.endsWith(".charpente")) await reloadWorkspace();
    return true;
  }

  async function reloadWorkspace() {
    try {
      await rpc.request("charpente/reload");
    } catch (error) {
      ctx.toast(error.message, "error");
    }
    await loadInfo();
    await ctx.refreshTargets();
    bus.emit("files-changed");
  }

  // Files changed by other panels (packages, options): re-read the open ones that have no unsaved edits.
  bus.on("files-changed", async () => {
    for (const [path, file] of files) {
      if (file.dirty || (path === ctx.activePath && editor.getText() !== file.text)) continue;
      try {
        const data = await rpc.request("charpente/files/read", { path });
        if (data.sha256 !== file.sha) {
          file.text = data.text;
          file.sha = data.sha256;
          if (path === ctx.activePath) editor.open({ text: data.text, language: file.language });
        }
      } catch {
        /* deleted or unreadable: the next save will say so */
      }
    }
  });

  function updateDiagnostics() {
    const merged = [];
    for (const [, byPath] of ctx.diagnostics) merged.push(...(byPath.get(ctx.activePath) || []));
    editor.setDiagnostics(merged);
    bus.emit("diagnostics-changed");
  }

  // ------------------------------------------------------------------ builds
  function setStatus(name, status) {
    if (status) ctx.targetStatus.set(name, status);
    else ctx.targetStatus.delete(name);
    bus.emit("target-status");
  }

  function begin(message) {
    if (ctx.busy) {
      ctx.toast(t("busy"), "info");
      return false;
    }
    ctx.busy = true;
    $("task").textContent = message;
    document.body.classList.add("busy");
    showPanel("build");
    bus.emit("build-start", { message });
    return true;
  }

  function end(ok, message) {
    ctx.busy = false;
    ctx.tasks = (ctx.tasks || 0) + 1; // how many tasks have finished (the end-to-end tests wait on it)
    $("task").textContent = "";
    document.body.classList.remove("busy");
    bus.emit("build-end", { ok, message });
  }

  ctx.saveAll = () => saveAll();
  async function saveAll() {
    for (const [path, file] of files) {
      const dirty = path === ctx.activePath ? editor.getText() !== file.text : file.pending !== undefined && file.pending !== file.text;
      if (dirty && !(await save(path, { quiet: true }))) return false;
    }
    return true;
  }

  ctx.build = async (names) => {
    if (!(await saveAll())) return;
    const chosen = names || ctx.targets.map((x) => x.displayName);
    if (!chosen.length) return ctx.toast(t("targets.none"), "info");
    if (!begin(t("build.running"))) return;
    ctx.targetStatus.clear();
    ctx.diagnostics.set("build", new Map());
    try {
      const uris = ctx.targets.filter((x) => chosen.includes(x.displayName)).map((x) => ({ uri: x.id.uri }));
      const args = ["--config", ctx.config()];
      if (ctx.platform()) args.push("--platform", ctx.platform());
      const result = await rpc.request("buildTarget/compile", { targets: uris, arguments: args, originId: `studio-${Date.now()}` });
      end(result.statusCode === 1, null);
    } catch (error) {
      bus.emit("build-error", { message: error.message });
      end(false, null);
    }
  };

  ctx.run = async (name) => {
    if (!(await saveAll())) return;
    const target = ctx.targets.find((x) => x.displayName === name);
    if (!target || !begin(t("run.running", { name }))) return;
    try {
      const result = await rpc.request("buildTarget/run", { target: target.id, arguments: [], dataKind: "charpente/run",
        data: { config: ctx.config(), platform: ctx.platform() }, originId: `studio-${Date.now()}` });
      end(result.statusCode === 1, result.statusCode === 1 ? t("run.finished") : t("run.failed"));
    } catch (error) {
      bus.emit("build-error", { message: error.message });
      end(false, null);
    }
  };

  async function runTests() {
    if (!(await saveAll()) || !begin(t("test.running"))) return;
    try {
      const result = await rpc.request("buildTarget/test", { targets: [], arguments: ["--config", ctx.config()], originId: `studio-${Date.now()}` });
      end(result.statusCode === 1, result.statusCode === 1 ? t("test.passed") : t("test.failed"));
    } catch (error) {
      bus.emit("build-error", { message: error.message });
      end(false, null);
    }
  }

  async function runCheck() {
    if (!begin(t("check.running"))) return;
    try {
      const result = await rpc.request("charpente/check", {});
      const map = new Map();
      for (const finding of result.findings) {
        if (!finding.file) {
          bus.emit("build-log", { text: `[${finding.check}] ${finding.message}`, level: finding.severity === "error" ? "error" : "info" });
          continue;
        }
        const path = relativeToRoot(finding.file, ctx.root);
        if (!map.has(path)) map.set(path, []);
        map.get(path).push({ line: Math.max((finding.line || 1) - 1, 0), character: Math.max((finding.column || 1) - 1, 0),
          severity: finding.severity === "warning" ? "warning" : "error", message: `[${finding.check}] ${finding.message}`, source: "gate" });
      }
      ctx.diagnostics.set("gate", map);
      updateDiagnostics();
      for (const r of result.results || []) bus.emit("build-log", { text: `${r.check}: ${r.status}${r.message ? " — " + r.message : ""}`, level: r.status === "failed" ? "error" : "info" });
      end(result.ok, result.ok ? t("check.passed") : t("check.failed"));
    } catch (error) {
      bus.emit("build-error", { message: error.message });
      end(false, null);
    }
  }

  // ------------------------------------------------------------------ notifications from the server
  rpc.on("build/taskStart", (p) => bus.emit("build-task", p));
  rpc.on("build/logMessage", (p) => bus.emit("build-log", { text: p.message, level: p.type === 1 ? "error" : "info" }));
  rpc.on("build/publishDiagnostics", (p) => {
    const path = relativeToRoot(fileUriToPath(p.textDocument.uri), ctx.root);
    const map = ctx.diagnostics.get("build") || new Map();
    const items = p.diagnostics.map((d) => ({ line: d.range.start.line, character: d.range.start.character, severity: ["error", "error", "warning", "information", "hint"][d.severity] || "error",
      message: d.message, source: "build" }));
    if (items.length) map.set(path, items);
    else map.delete(path);
    ctx.diagnostics.set("build", map);
    updateDiagnostics();
  });
  rpc.on("charpente/event", (event) => {
    bus.emit("build-event", event);
    const name = event.payload && event.payload.target;
    if (event.type === "target.started") setStatus(name, "building");
    else if (event.type === "target.finished") setStatus(name, "ok");
    else if (event.type === "target.up_to_date") setStatus(name, "upToDate");
    else if (event.type === "target.failed") setStatus(name, "failed");
  });

  // ------------------------------------------------------------------ panels and layout
  const sidePanels = ["files", "targets", "options", "packages"];
  const bottomPanels = ["build", "problems", "graph", "profile", "git", "devices", "debug", "terminal", "ai"];
  function showSide(name) {
    for (const p of sidePanels) {
      $(`side-${p}`).hidden = p !== name;
      $(`sidetab-${p}`).setAttribute("aria-selected", String(p === name));
    }
  }
  function showPanel(name) {
    for (const p of bottomPanels) {
      $(`panel-${p}`).hidden = p !== name;
      $(`tab-${p}`).setAttribute("aria-selected", String(p === name));
    }
    $("bottom").hidden = false;
    bus.emit(`panel-shown:${name}`);
    ctx.activePanel = name;
  }
  ctx.showPanel = showPanel;
  for (const p of sidePanels) $(`sidetab-${p}`).addEventListener("click", () => showSide(p));
  for (const p of bottomPanels) $(`tab-${p}`).addEventListener("click", () => showPanel(p));
  bus.on("problem-counts", ({ errors, warnings }) => {
    $("tab-problems").textContent = `${t("tab.problems")} ${errors || warnings ? `(${errors ? "⛔" + errors : ""}${errors && warnings ? " " : ""}${warnings ? "⚠" + warnings : ""})` : ""}`;
    $("problem-status").textContent = `⛔ ${errors}  ⚠ ${warnings}`;
  });
  bus.on("select-target", (name) => { showSide("targets"); ctx.toast(name, "info"); });

  mountFiles(ctx, $("side-files"));
  mountTargets(ctx, $("side-targets"));
  mountOptions(ctx, $("side-options"));
  mountPackages(ctx, $("side-packages"));
  mountBuild(ctx, $("panel-build"));
  mountProblems(ctx, $("panel-problems"));
  mountGraph(ctx, $("panel-graph"));
  mountProfile(ctx, $("panel-profile"));
  mountGit(ctx, $("panel-git"));
  mountDevices(ctx, $("panel-devices"));
  mountDebug(ctx, $("panel-debug"));
  mountTerminal(ctx, $("panel-terminal"));
  mountAi(ctx, $("panel-ai"), { getSelection: () => (editor.input.selectionStart === editor.input.selectionEnd ? "" : editor.input.value.slice(editor.input.selectionStart, editor.input.selectionEnd)),
    activePath: () => ctx.activePath });
  showSide("files");
  showPanel("build");

  // ------------------------------------------------------------------ toolbar, commands, shortcuts
  const firstRunnable = () => {
    const chosen = ctx.targets.find((x) => x.capabilities.canRun && !x.tags.includes("test")) || ctx.targets.find((x) => x.capabilities.canRun);
    return chosen ? chosen.displayName : null;
  };
  const commands = [
    { id: "build", title: t("cmd.build"), keys: "F7", run: () => ctx.build(null) },
    { id: "run", title: t("cmd.run"), keys: "F5", run: () => { const name = firstRunnable(); if (name) ctx.run(name); else ctx.toast(t("run.none"), "info"); } },
    { id: "test", title: t("cmd.test"), run: runTests },
    { id: "check", title: t("cmd.check"), run: runCheck },
    { id: "reload", title: t("cmd.reload"), run: reloadWorkspace },
    { id: "save", title: t("cmd.save"), keys: "Ctrl+S", run: () => save() },
    { id: "saveAll", title: t("cmd.saveAll"), run: async () => { if (await saveAll()) ctx.toast(t("editor.savedAll"), "info"); } },
    { id: "rename", title: t("cmd.rename"), run: renameSymbol },
    { id: "definition", title: t("cmd.definition"), keys: "F12", run: () => { const { line, column } = cursorPosition(); gotoDefinition(line, column); } },
    { id: "format", title: t("cmd.formatToggle"), run: () => { const on = stored("charpente-format", "1") === "1"; remember("charpente-format", on ? "0" : "1"); ctx.toast(t(on ? "cmd.formatOff" : "cmd.formatOn"), "info"); } },
    { id: "debugStart", title: t("cmd.debugStart"), keys: "Ctrl+F5", run: () => ctx.debugCommand("start") },
    { id: "debugStop", title: t("cmd.debugStop"), keys: "Shift+F5", run: () => ctx.debugCommand("stop") },
    { id: "breakpoint", title: t("cmd.toggleBreakpoint"), keys: "F9", run: () => { if (ctx.activePath) ctx.toggleBreakpoint(ctx.activePath, cursorPosition().line); } },
    { id: "terminal", title: t("cmd.terminal"), keys: "Ctrl+`", run: () => showPanel("terminal") },
    { id: "theme", title: t("cmd.theme"), run: () => cycleTheme() },
    { id: "lang", title: t("cmd.language"), run: () => switchLang() },
    ...bottomPanels.map((p, i) => ({ id: `panel-${p}`, title: t("cmd.show", { name: t(`tab.${p}`) }), keys: `Alt+${i + 1}`, run: () => showPanel(p) })),
  ];
  ctx.commands = commands;
  function cursorPosition() {
    const before = editor.input.value.slice(0, editor.input.selectionStart);
    return { line: before.split("\n").length, column: editor.input.selectionStart - (before.lastIndexOf("\n") + 1) + 1 };
  }
  $("btn-build").addEventListener("click", () => ctx.build(null));
  $("btn-run").addEventListener("click", () => commands.find((c) => c.id === "run").run());
  $("btn-test").addEventListener("click", runTests);
  $("btn-check").addEventListener("click", runCheck);
  $("btn-reload").addEventListener("click", reloadWorkspace);
  $("btn-palette").addEventListener("click", openPalette);
  $("btn-theme").addEventListener("click", cycleTheme);
  $("config").addEventListener("change", () => remember("charpente-config", $("config").value));
  $("platform").addEventListener("change", () => remember("charpente-platform", $("platform").value));
  $("platform").value = stored("charpente-platform", "");
  clear($("lang")).append(...LANGS.map((l) => h("option", { value: l, selected: l === getLang() }, l.toUpperCase())));
  $("lang").addEventListener("change", () => switchLang($("lang").value));

  function switchLang(next) {
    const lang = next || (getLang() === "fr" ? "en" : "fr");
    setLang(lang);
    remember("charpente-lang", lang);
    location.reload();
  }

  function applyTheme(mode) {
    document.documentElement.dataset.theme = mode;
  }
  function cycleTheme() {
    const order = ["auto", "light", "dark"];
    const next = order[(order.indexOf(document.documentElement.dataset.theme) + 1) % order.length];
    applyTheme(next);
    remember("charpente-theme", next);
    ctx.toast(t(`theme.${next}`), "info");
  }

  function openPalette() {
    const dialog = $("palette");
    const input = h("input", { type: "text", placeholder: t("palette.placeholder"), "aria-label": t("palette.placeholder") });
    const list = h("ul", { role: "listbox" });
    let filtered = commands;
    let index = 0;
    const paint = () => {
      clear(list).append(...filtered.slice(0, 12).map((c, i) => h("li", { role: "option", class: i === index ? "selected" : "", "aria-selected": String(i === index),
        onclick: () => choose(c) }, h("span", {}, c.title), c.keys ? h("kbd", {}, c.keys) : null)));
    };
    const choose = (command) => { dialog.close(); command.run(); };
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase();
      filtered = commands.filter((c) => c.title.toLowerCase().includes(q));
      index = 0;
      paint();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") { index = Math.min(index + 1, Math.min(filtered.length, 12) - 1); paint(); event.preventDefault(); }
      else if (event.key === "ArrowUp") { index = Math.max(index - 1, 0); paint(); event.preventDefault(); }
      else if (event.key === "Enter" && filtered[index]) { event.preventDefault(); choose(filtered[index]); }
    });
    clear(dialog).append(input, list);
    paint();
    dialog.showModal();
    input.focus();
  }

  document.addEventListener("keydown", (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.shiftKey && event.key.toLowerCase() === "p") { event.preventDefault(); openPalette(); }
    else if (event.key === "F7") { event.preventDefault(); ctx.build(null); }
    else if (event.key === "F5" && event.shiftKey) { event.preventDefault(); ctx.debugCommand("stop"); }
    else if (event.key === "F5" && mod) { event.preventDefault(); ctx.debugCommand("start"); }
    else if (event.key === "F5") { event.preventDefault(); if (ctx.debugState() === "stopped") ctx.debugCommand("continue"); else commands.find((c) => c.id === "run").run(); }
    else if (event.key === "F9") { event.preventDefault(); commands.find((c) => c.id === "breakpoint").run(); }
    else if (event.key === "F10") { event.preventDefault(); ctx.debugCommand("over"); }
    else if (event.key === "F11") { event.preventDefault(); ctx.debugCommand(event.shiftKey ? "out" : "into"); }
    else if (mod && event.key === "`") { event.preventDefault(); showPanel("terminal"); }
    else if (event.altKey && /^[1-9]$/.test(event.key)) { event.preventDefault(); showPanel(bottomPanels[Number(event.key) - 1]); }
    else if (mod && event.key.toLowerCase() === "s" && !event.target.closest?.(".editor")) { event.preventDefault(); save(); }
  });
  window.addEventListener("beforeunload", (event) => {
    if ([...files.values()].some((f) => f.dirty)) { event.preventDefault(); event.returnValue = ""; }
  });

  // ------------------------------------------------------------------ go
  await loadInfo();
  loadBreakpoints();
  await Promise.all([ctx.refreshTargets(), loadSchema()]);
  $("boot").hidden = true;
  $("app").hidden = false;
  if (ctx.info && ctx.info.file) {
    const workspaceFile = relativeToRoot(ctx.info.file, ctx.root);
    openFile(workspaceFile);
  }
  ctx.ready = true;
  document.dispatchEvent(new CustomEvent("studio-ready"));
  return ctx;
}

start().catch((error) => {
  console.error(error);
  const boot = document.getElementById("boot");
  if (boot) boot.textContent = `${t("boot.failed")} ${error.message}`;
});
