// Unit tests for the pure parts of Studio's front end (no browser): highlighting, completion, diffs, graph layout, helpers, RPC client.
import assert from "node:assert/strict";
import { test } from "node:test";
import { complete, currentWord, dslVariables } from "../../charpente/studio_web/js/complete.js";
import { hunkPatch, hunkStats, parseDiff } from "../../charpente/studio_web/js/diff.js";
import { newLineIndent, offsetOf, positionOf } from "../../charpente/studio_web/js/editor.js";
import { layout } from "../../charpente/studio_web/js/graph.js";
import { highlightLines, setDslNames, tokenize } from "../../charpente/studio_web/js/highlight.js";
import { applyEdits } from "../../charpente/studio_web/js/lsp.js";
import { bars } from "../../charpente/studio_web/js/panels/profile.js";
import { collect, counts } from "../../charpente/studio_web/js/panels/problems.js";
import { Rpc, RpcError } from "../../charpente/studio_web/js/rpc.js";
import { Emitter, debounce, fileUriToPath, formatBytes, formatSeconds, parseLocation, pathToFileUri, relativeToRoot, splitCommandLine, escapeHtml } from "../../charpente/studio_web/js/util.js";

// ---------------------------------------------------------------------- highlight
test("tokens cover the whole text, whatever the language", () => {
  const samples = {
    cpp: '#include <x>\nint main() { /* multi\nline */ const char* s = "a\\"b"; return 0x1F + 1.5f; } // end\n',
    python: 'import os\n@deco\ndef f(x):\n    """doc\n    string"""\n    return x + 1  # c\n',
    charpente: 'with Target("a") as t:\n    t.sources(["*.cpp"])\n    t.kind(Kind.EXECUTABLE)\n',
    json: '{"a": [1, 2.5e3, true, null], "b": "x"}',
    toml: '[section]\nkey = "v" # c\nn = 3\n',
    markdown: "# Title\n- item\n`code`\n",
    cmake: "add_executable(x ${SRC}) # c\n",
    unknown: "anything <b> & more",
  };
  for (const [lang, text] of Object.entries(samples)) {
    assert.equal(tokenize(text, lang).map((t) => t.text).join(""), text, lang);
  }
});

test("C++ tokens", () => {
  const types = (text) => Object.fromEntries(tokenize(text, "cpp").filter((t) => t.type).map((t) => [t.text.trim(), t.type]));
  const found = types('#include <x>\nint main() { return foo(1); } // hi\nconst char* s = "q";');
  assert.equal(found["#include"], "pre");
  assert.equal(found["int"], "type");
  assert.equal(found["return"], "keyword");
  assert.equal(found["foo"], "fn");
  assert.equal(found["1"], "number");
  assert.equal(found["// hi"], "comment");
  assert.equal(found['"q"'], "string");
});

test("a block comment across lines is closed and reopened on every line", () => {
  const lines = highlightLines("a /* one\ntwo\nthree */ b", "cpp");
  assert.equal(lines.length, 3);
  assert.match(lines[0], /<span class="tok-comment">\/\* one<\/span>/);
  assert.match(lines[1], /^<span class="tok-comment">two<\/span>$/);
  assert.match(lines[2], /<span class="tok-comment">three \*\/<\/span> b/);
});

test("HTML in code is escaped, never interpreted", () => {
  const [line] = highlightLines('x = "<img src=x onerror=alert(1)>" & 1', "python");
  assert.ok(!line.includes("<img"));
  assert.ok(line.includes("&lt;img"));
  assert.equal(escapeHtml('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;");
});

test("the DSL names highlighted come from the server's schema", () => {
  const dsl = (text) => tokenize(text, "charpente").filter((t) => t.type === "dsl").map((t) => t.text);
  assert.deepEqual(dsl("t.sources([])\nt.my_new_method(1)"), ["sources"]);
  setDslNames(["Workspace", "Target"], ["sources", "my_new_method"]);
  assert.deepEqual(dsl("t.sources([])\nt.my_new_method(1)"), ["sources", "my_new_method"]);
  assert.equal(tokenize("x = Target('a')", "charpente").find((t) => t.text === "Target").type, "type");
});

test("unterminated strings and empty input do not hang or throw", () => {
  assert.deepEqual(tokenize("", "cpp"), []);
  assert.equal(tokenize('"open', "cpp").map((t) => t.text).join(""), '"open');
  assert.equal(highlightLines("", "python").length, 1);
});

// ---------------------------------------------------------------------- completion
const SCHEMA = {
  classes: {
    Target: [{ name: "sources", signature: "(patterns)", doc: "" }, { name: "standard", signature: "(std)", doc: "" }, { name: "uses", signature: "(*names)", doc: "" }],
    Workspace: [{ name: "requires", signature: "(*specs)", doc: "" }, { name: "configurations", signature: "(names)", doc: "" }],
  },
  enums: { Kind: ["EXECUTABLE", "STATIC_LIBRARY"] },
};

test("completion after a variable bound by `with Target(...) as t` offers that class's methods", () => {
  const text = 'with Workspace("w") as ws:\n    with Target("a") as t:\n        t.s';
  assert.deepEqual(dslVariables(text), { ws: "Workspace", t: "Target" });
  const result = complete(text, text.length, "charpente", SCHEMA);
  assert.deepEqual(result.items.map((i) => i.label), ["sources", "standard"]);
  assert.equal(result.items[0].insertText, "sources(");
  assert.equal(text.slice(result.from), "s");
});

test("completion for enums, workspaces and plain words", () => {
  assert.deepEqual(complete("Kind.", 5, "charpente", SCHEMA).items.map((i) => i.label), ["EXECUTABLE", "STATIC_LIBRARY"]);
  const ws = 'with Workspace("w") as ws:\n    ws.re';
  assert.deepEqual(complete(ws, ws.length, "charpente", SCHEMA).items.map((i) => i.label), ["requires"]);
  const cpp = "int counter = 0;\nint count_all() { return cou";
  assert.ok(complete(cpp, cpp.length, "cpp").items.some((i) => i.label === "counter"));
  assert.ok(complete("ret", 3, "cpp").items.some((i) => i.label === "return"));
  assert.deepEqual(complete("x.foo", 5, "cpp").items, []);
  assert.ok(complete("", 0, "cpp").items.length > 0); // explicit completion in an empty file offers the keywords
});

test("current word handles #include and std::", () => {
  assert.deepEqual(currentWord("  #inc", 6, "cpp"), { from: 2, prefix: "#inc" });
  assert.deepEqual(currentWord("std::mov", 8, "cpp"), { from: 0, prefix: "std::mov" });
  assert.deepEqual(currentWord("foo_bar1", 8), { from: 0, prefix: "foo_bar1" });
});

// ---------------------------------------------------------------------- editor helpers
test("positions and offsets are inverse of each other", () => {
  const text = "ab\ncde\n\nfg";
  for (let offset = 0; offset <= text.length; offset++) {
    const { line, column } = positionOf(text, offset);
    assert.equal(offsetOf(text, line, column), offset);
  }
  assert.equal(offsetOf(text, 99, 1), offsetOf(text, 4, 1)); // a line past the end is the last line
  assert.equal(offsetOf(text, 2, 99), 6);
});

test("a new line keeps the indentation and goes deeper after an opening brace or colon", () => {
  assert.equal(newLineIndent("    foo();", 10), "    ");
  assert.equal(newLineIndent("if (x) {", 8), "    ");
  assert.equal(newLineIndent("  if x:", 7, "  "), "    ");
  assert.equal(newLineIndent("plain", 5), "");
  assert.equal(newLineIndent("a\n  b", 5), "  ");
});

// ---------------------------------------------------------------------- diffs
const DIFF = `diff --git a/src/a.cpp b/src/a.cpp
index 111..222 100644
--- a/src/a.cpp
+++ b/src/a.cpp
@@ -1,3 +1,3 @@
 keep
-old
+new
 keep2
@@ -20,2 +20,3 @@
 tail
+added
 end
diff --git a/b.txt b/b.txt
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-x
+y
`;

test("a git diff is split into files and hunks", () => {
  const files = parseDiff(DIFF);
  assert.deepEqual(files.map((f) => f.path), ["src/a.cpp", "b.txt"]);
  assert.equal(files[0].hunks.length, 2);
  assert.deepEqual(hunkStats(files[0].hunks[0]), { added: 1, removed: 1 });
  assert.deepEqual(hunkStats(files[0].hunks[1]), { added: 1, removed: 0 });
  assert.equal(parseDiff("").length, 0);
  assert.equal(parseDiff("garbage\nlines").length, 0);
});

test("a hunk patch holds the file header and only that hunk", () => {
  const [file] = parseDiff(DIFF);
  const patch = hunkPatch(file, file.hunks[1]);
  assert.ok(patch.startsWith("diff --git a/src/a.cpp b/src/a.cpp\n"));
  assert.ok(patch.includes("@@ -20,2 +20,3 @@") && !patch.includes("@@ -1,3"));
  assert.ok(patch.endsWith("+added\n end\n"));
});

// ---------------------------------------------------------------------- graph layout
test("dependencies sit on the left of what needs them", () => {
  const nodes = ["app", "core", "base", "tests"].map((name) => ({ name, kind: "x" }));
  const edges = [{ from: "app", to: "core" }, { from: "core", to: "base" }, { from: "tests", to: "core" }];
  const { positions, width, height } = layout(nodes, edges);
  assert.ok(positions.base.x < positions.core.x && positions.core.x < positions.app.x);
  assert.equal(positions.app.x, positions.tests.x);
  assert.notEqual(positions.app.y, positions.tests.y);
  assert.ok(width >= positions.app.x + positions.app.width && height >= positions.tests.y + positions.tests.height);
});

test("layout survives an empty graph, unknown names and a cycle", () => {
  assert.deepEqual(layout([], []).positions, {});
  assert.equal(Object.keys(layout([{ name: "a" }], [{ from: "a", to: "ghost" }]).positions).length, 1);
  const cyclic = layout([{ name: "a" }, { name: "b" }], [{ from: "a", to: "b" }, { from: "b", to: "a" }]);
  assert.equal(Object.keys(cyclic.positions).length, 2);
});

// ---------------------------------------------------------------------- panels' pure helpers
test("problems are merged across sources, sorted and counted", () => {
  const diagnostics = new Map([
    ["build", new Map([["b.cpp", [{ line: 3, character: 0, severity: "error", message: "x" }]], ["a.cpp", [{ line: 9, character: 1, severity: "warning", message: "w" }]]])],
    ["clangd", new Map([["a.cpp", [{ line: 2, character: 0, severity: "error", message: "y" }]], ["c.cpp", []]])],
  ]);
  const groups = collect(diagnostics);
  assert.deepEqual(groups.map((g) => g.path), ["a.cpp", "b.cpp"]);
  assert.deepEqual(groups[0].items.map((i) => [i.line, i.source]), [[2, "clangd"], [9, "build"]]);
  assert.deepEqual(counts(groups), { errors: 2, warnings: 1 });
});

test("bars are relative to the largest value", () => {
  assert.deepEqual(bars([{ label: "a", value: 4 }, { label: "b", value: 1 }]).map((b) => b.percent), [100, 25]);
  assert.deepEqual(bars([{ label: "a", value: 0 }]).map((b) => b.percent), [0]);
  assert.deepEqual(bars([]), []);
});

// ---------------------------------------------------------------------- util
test("command lines are split like a person means them", () => {
  assert.deepEqual(splitCommandLine('git commit -m "a message" --amend'), ["git", "commit", "-m", "a message", "--amend"]);
  assert.deepEqual(splitCommandLine("echo 'single  spaces' x"), ["echo", "single  spaces", "x"]);
  assert.deepEqual(splitCommandLine('a "b \\"c\\"" d'), ["a", 'b "c"', "d"]);
  assert.deepEqual(splitCommandLine('a "" b'), ["a", "", "b"]);
  assert.deepEqual(splitCommandLine("   "), []);
  assert.deepEqual(splitCommandLine("a|b > c"), ["a|b", ">", "c"]); // no shell: a pipe is just text
  assert.throws(() => splitCommandLine('a "open'), /unterminated/);
});

test("compiler locations are found in GNU and MSVC output", () => {
  assert.deepEqual(parseLocation("src/main.cpp:12:5: error: x"), { file: "src/main.cpp", line: 12, column: 5, index: 0, length: 17 });
  assert.equal(parseLocation("In file included from C:/p/a.hpp:3:").file, "C:/p/a.hpp");
  assert.deepEqual(parseLocation("C:\\p\\a.cpp(7,2): error C1"), { file: "C:\\p\\a.cpp", line: 7, column: 2, index: 0, length: 15 });
  assert.equal(parseLocation("nothing to see here"), null);
  assert.equal(parseLocation("time 12:30:45"), null);
});

test("paths and URIs", () => {
  assert.equal(relativeToRoot("C:\\proj\\src\\a.cpp", "C:/proj"), "src/a.cpp");
  assert.equal(relativeToRoot("c:/PROJ/src/a.cpp", "C:\\proj\\"), "src/a.cpp");
  assert.equal(relativeToRoot("./x.cpp", "/p"), "x.cpp");
  assert.equal(relativeToRoot("/other/x.cpp", "/p"), "/other/x.cpp");
  for (const p of ["C:/Users/Ada Lovelace/a b.cpp", "/home/ada/é.cpp"]) assert.equal(fileUriToPath(pathToFileUri(p)), p);
});

test("formatting numbers", () => {
  assert.equal(formatSeconds(0.25), "250 ms");
  assert.equal(formatSeconds(2.34), "2.3 s");
  assert.equal(formatSeconds(125), "2 min 5 s");
  assert.equal(formatSeconds(NaN), "–");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2.0 KB");
});

test("debounce runs once with the last arguments, and can be flushed or cancelled", async () => {
  const seen = [];
  const d = debounce((x) => seen.push(x), 20);
  d(1);
  d(2);
  d(3);
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(seen, [3]);
  d(4);
  d.cancel();
  await new Promise((r) => setTimeout(r, 40));
  assert.deepEqual(seen, [3]);
  d.flush(5);
  assert.deepEqual(seen, [3, 5]);
});

test("the emitter isolates failing listeners", () => {
  const bus = new Emitter();
  const seen = [];
  const originalError = console.error;
  console.error = () => {};
  bus.on("x", () => { throw new Error("boom"); });
  const off = bus.on("x", (v) => seen.push(v));
  bus.emit("x", 1);
  off();
  bus.emit("x", 2);
  console.error = originalError;
  assert.deepEqual(seen, [1]);
});

test("LSP edits are applied from the end so offsets stay valid", () => {
  const text = "int foo = 1;\nint bar = foo + foo;\n";
  const edit = (line, start, end) => ({ range: { start: { line, character: start }, end: { line, character: end } }, newText: "value" });
  assert.equal(applyEdits(text, [edit(0, 4, 7), edit(1, 10, 13), edit(1, 16, 19)]), "int value = 1;\nint bar = value + value;\n");
  assert.equal(applyEdits("abc", []), "abc");
});

// ---------------------------------------------------------------------- RPC client with a fake socket
class FakeSocket {
  static last = null;
  constructor(url) {
    this.url = url;
    this.sent = [];
    FakeSocket.last = this;
    queueMicrotask(() => this.onopen && this.onopen());
  }
  send(text) { this.sent.push(JSON.parse(text)); }
  close() { this.onclose && this.onclose(); }
  reply(message) { this.onmessage({ data: JSON.stringify(message) }); }
}

test("requests are matched to replies, errors are typed, notifications are routed", async () => {
  const rpc = new Rpc("ws://x/?token=t", FakeSocket);
  const states = [];
  rpc.onStatus((s) => states.push(s));
  await rpc.connect();
  assert.deepEqual(states, ["connecting", "open"]);
  const notes = [];
  rpc.on("charpente/event", (p) => notes.push(p));
  const first = rpc.request("a", { n: 1 });
  const second = rpc.request("b");
  const socket = FakeSocket.last;
  assert.deepEqual(socket.sent.map((m) => [m.id, m.method]), [[1, "a"], [2, "b"]]);
  socket.reply({ jsonrpc: "2.0", method: "charpente/event", params: { type: "x" } });
  socket.reply({ jsonrpc: "2.0", id: 2, error: { code: -32001, message: "nope", data: { code: "CH1" } } });
  socket.reply({ jsonrpc: "2.0", id: 1, result: { ok: true } });
  assert.deepEqual(await first, { ok: true });
  await assert.rejects(second, (e) => e instanceof RpcError && e.code === -32001 && e.data.code === "CH1" && e.message === "nope");
  assert.deepEqual(notes, [{ type: "x" }]);
  socket.onmessage({ data: "not json" }); // ignored
  socket.reply({ jsonrpc: "2.0", id: 999, result: 1 }); // unknown id: ignored
});

test("pending requests fail when the connection closes, and new ones are refused", async () => {
  const rpc = new Rpc("ws://x", FakeSocket);
  await rpc.connect();
  const pending = rpc.request("slow");
  FakeSocket.last.close();
  await assert.rejects(pending, /closed/);
  await assert.rejects(rpc.request("again"), /not connected/);
  assert.equal(rpc.status, "closed");
});

test("stream messages that arrive before their id is known are kept for whoever claims them", async () => {
  const rpc = new Rpc("ws://x", FakeSocket);
  await rpc.connect();
  const socket = FakeSocket.last;
  const note = (message) => socket.reply({ jsonrpc: "2.0", method: "charpente/stream", params: message });
  note({ id: "s1", line: "early" });
  note({ id: "s1", exit: 0 });
  const seen = [];
  const release = rpc.claimStream("s1", (m) => seen.push(m));
  note({ id: "s2", line: "someone else" });
  assert.deepEqual(seen, [{ id: "s1", line: "early" }, { id: "s1", exit: 0 }]);
  note({ id: "s1", line: "later" });
  assert.equal(seen.length, 3);
  release();
  note({ id: "s1", line: "after release" });
  assert.equal(seen.length, 3);
});

test("a connection that cannot open is an error", async () => {
  class Refusing {
    constructor() { queueMicrotask(() => { this.onerror && this.onerror(); this.onclose && this.onclose(); }); }
  }
  await assert.rejects(new Rpc("ws://x", Refusing).connect(), /cannot connect|closed/);
});
