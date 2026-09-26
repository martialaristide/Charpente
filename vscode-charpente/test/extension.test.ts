/**
 * Activates the real extension code against a small fake of the `vscode` module and a real `charpente serve`.
 * It checks our logic (commands, status bar, tree, diagnostics, tasks, compile_commands.json), not VS Code itself.
 */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import Module from "node:module";
import * as os from "node:os";
import * as path from "node:path";
import { after, before, test } from "node:test";

const python = process.env.CHARPENTE_PYTHON ?? (process.platform === "win32" ? "python" : "python3");

type Handler = (...args: any[]) => any;
const commands = new Map<string, Handler>();
const messages: { kind: string; text: string }[] = [];
const diagnosticSets = new Map<string, any[]>();
const outputLines: string[] = [];
const statusItem: any = { text: "", tooltip: "", command: "", show() {} };
const treeProviders = new Map<string, any>();
const taskProviders = new Map<string, any>();
const saveHandlers: Handler[] = [];
const debugFactories = new Map<string, any>();
const debugProviders = new Map<string, any>();
let root = "";
let configuration: Record<string, unknown> = {};

class EventEmitter<T> {
  private listeners: ((e: T) => void)[] = [];
  event = (listener: (e: T) => void) => {
    this.listeners.push(listener);
    return { dispose() {} };
  };
  fire(value?: T) {
    this.listeners.forEach((l) => l(value as T));
  }
}

const fakeVscode = {
  EventEmitter,
  TreeItem: class {
    description?: string;
    contextValue?: string;
    tooltip?: string;
    iconPath?: unknown;
    constructor(public label: string, public collapsibleState?: number) {}
  },
  TreeItemCollapsibleState: { None: 0 },
  ThemeIcon: class {
    constructor(public id: string) {}
  },
  StatusBarAlignment: { Left: 1 },
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  Range: class {
    constructor(public a: number, public b: number, public c: number, public d: number) {}
  },
  Diagnostic: class {
    source?: string;
    code?: unknown;
    constructor(public range: unknown, public message: string, public severity: number) {}
  },
  Uri: { parse: (value: string) => ({ toString: () => value }) },
  TaskScope: { Workspace: 2 },
  TaskGroup: { Build: "build", Test: "test" },
  ProcessExecution: class {
    constructor(public process: string, public args: string[]) {}
  },
  Task: class {
    group?: string;
    constructor(public definition: any, public scope: unknown, public name: string, public source: string, public execution: any, public problemMatchers: string[]) {}
  },
  window: {
    createOutputChannel: () => ({ append: (t: string) => outputLines.push(t), appendLine: (t: string) => outputLines.push(t), show() {}, dispose() {} }),
    createStatusBarItem: () => statusItem,
    registerTreeDataProvider: (id: string, provider: unknown) => (treeProviders.set(id, provider), { dispose() {} }),
    showErrorMessage: (text: string) => (messages.push({ kind: "error", text }), Promise.resolve(undefined)),
    showWarningMessage: (text: string) => (messages.push({ kind: "warning", text }), Promise.resolve(undefined)),
    showInformationMessage: (text: string) => (messages.push({ kind: "info", text }), Promise.resolve(undefined)),
    showQuickPick: async (items: any[]) => items[0],
    showInputBox: async () => "CH2001",
  },
  languages: {
    createDiagnosticCollection: () => ({
      set: (uri: any, items: any[]) => diagnosticSets.set(uri.toString(), items),
      dispose() {},
    }),
  },
  tasks: { registerTaskProvider: (type: string, provider: unknown) => (taskProviders.set(type, provider), { dispose() {} }) },
  commands: {
    registerCommand: (id: string, handler: Handler) => (commands.set(id, handler), { dispose() {} }),
    executeCommand: (id: string, ...args: any[]) => commands.get(id)?.(...args),
  },
  DebugAdapterExecutable: class {
    constructor(public command: string, public args: string[]) {}
  },
  debug: {
    registerDebugAdapterDescriptorFactory: (type: string, factory: unknown) => (debugFactories.set(type, factory), { dispose() {} }),
    registerDebugConfigurationProvider: (type: string, provider: unknown) => (debugProviders.set(type, provider), { dispose() {} }),
  },
  workspace: {
    get workspaceFolders() {
      return [{ uri: { fsPath: root } }];
    },
    getConfiguration: () => ({ get: (key: string, fallback: unknown) => (key in configuration ? configuration[key] : fallback) }),
    onDidSaveTextDocument: (handler: Handler) => (saveHandlers.push(handler), { dispose() {} }),
    onDidChangeConfiguration: () => ({ dispose() {} }),
  },
};

const originalLoad = (Module as any)._load;
(Module as any)._load = function (request: string, ...rest: unknown[]) {
  return request === "vscode" ? fakeVscode : originalLoad.call(this, request, ...rest);
};

const WORKSPACE = `from charpente import *

with Workspace("demo", version="1.0.0") as ws:
    with Target("lib") as lib:
        lib.kind(Kind.STATIC_LIBRARY)
        lib.standard("c++17")
        lib.sources(["src/lib.cpp"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("lib")
`;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function until(check: () => boolean, what: string, timeoutMs = 60000) {
  const begun = Date.now();
  while (!check()) {
    if (Date.now() - begun > timeoutMs) {
      throw new Error(`timed out waiting for ${what}
output: ${JSON.stringify(outputLines.slice(-15))}
messages: ${JSON.stringify(messages)}`);
    }
    await sleep(50);
  }
}

let extension: typeof import("../src/extension");

before(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "vscode-charpente-ext-"));
  fs.mkdirSync(path.join(root, "src"));
  fs.writeFileSync(path.join(root, "demo.charpente"), WORKSPACE);
  fs.writeFileSync(path.join(root, "src", "lib.cpp"), "int value() { return 3; }\n");
  fs.writeFileSync(path.join(root, "src", "main.cpp"), "int value();\nint main() { return value() - 3; }\n");
  process.env.CHARPENTE_TRUST_ALL = "1";
  configuration = { command: [python, "-m", "charpente"], configuration: "Debug" };
  extension = await import("../src/extension");
  await extension.activate({ subscriptions: [] } as any);
});

after(async () => {
  await extension.deactivate();
  fs.rmSync(root, { recursive: true, force: true });
});

test("activation registers every command and the views", () => {
  for (const id of [
    "charpente.build", "charpente.buildTarget", "charpente.runTarget", "charpente.test", "charpente.check", "charpente.reload",
    "charpente.explain", "charpente.generateCompileCommands", "charpente.showOutput", "charpente.restartServer",
  ]) {
    assert.ok(commands.has(id), id);
  }
  assert.ok(treeProviders.has("charpente.targets") && taskProviders.has("charpente"));
});

test("the workspace loads: targets in the tree, name in the status bar, compile_commands.json written", async () => {
  await until(() => treeProviders.get("charpente.targets").getChildren().length === 2, "the targets");
  const nodes = treeProviders.get("charpente.targets").getChildren();
  assert.deepEqual(nodes.map((n: any) => n.label), ["app", "lib"]);
  assert.equal(nodes[0].contextValue, "runnable");
  assert.equal(nodes[1].contextValue, "target");
  assert.match(statusItem.text, /demo/);
  assert.equal(statusItem.command, "charpente.build");
  await until(() => fs.existsSync(path.join(root, "compile_commands.json")), "compile_commands.json");
  const database = JSON.parse(fs.readFileSync(path.join(root, "compile_commands.json"), "utf8"));
  assert.equal(database.length, 2);
  assert.ok(database.every((e: any) => e.arguments.includes("-c") && path.isAbsolute(e.file)));
});

test("debugging is wired to the adapter of charpente", () => {
  const descriptor = debugFactories.get("charpente").createDebugAdapterDescriptor({});
  assert.equal(descriptor.command, python);
  assert.deepEqual(descriptor.args, ["-m", "charpente", "debug-adapter", "--root", root]);
  const resolved = debugProviders.get("charpente").resolveDebugConfiguration(undefined, {});
  assert.equal(resolved.type, "charpente");
  assert.equal(resolved.config, "Debug");
});

test("tasks are built from the settings without a shell", () => {
  const provider = taskProviders.get("charpente");
  const tasks = provider.provideTasks();
  assert.deepEqual(tasks.map((t: any) => t.name), ["build", "test", "check"]);
  const build = tasks[0];
  assert.equal(build.execution.process, python);
  assert.deepEqual(build.execution.args, ["-m", "charpente", "build", "--config", "Debug"]);
  assert.deepEqual(build.problemMatchers, ["$charpente-cpp"]);
  const resolved = provider.resolveTask({ definition: { type: "charpente", command: "build", target: "app", config: "Release" } });
  assert.deepEqual(resolved.execution.args, ["-m", "charpente", "build", "--config", "Release", "--target", "app"]);
  assert.equal(provider.resolveTask({ definition: { type: "charpente" } }), undefined);
});

test("building reports a compiler error as a diagnostic, then clears it when the code is fixed", async () => {
  const main = path.join(root, "src", "main.cpp");
  const good = fs.readFileSync(main, "utf8");
  fs.writeFileSync(main, good.replace("return value() - 3;", "return missing_symbol;"));
  await commands.get("charpente.build")!();
  await until(() => [...diagnosticSets.values()].some((items) => items.length > 0), "an error diagnostic");
  const [uri, items] = [...diagnosticSets.entries()].find(([, v]) => v.length > 0)!;
  assert.match(uri, /main\.cpp$/);
  assert.equal(items[0].severity, fakeVscode.DiagnosticSeverity.Error);
  assert.equal(items[0].source, "charpente");
  assert.match(statusItem.text, /error/);
  assert.ok(outputLines.some((l) => l.includes("failed")));

  fs.writeFileSync(main, good);
  await commands.get("charpente.build")!();
  await until(() => [...diagnosticSets.values()].every((items) => items.length === 0), "the diagnostics to clear");
  assert.match(statusItem.text, /check/);
});

test("running a target streams its output", async () => {
  fs.writeFileSync(path.join(root, "src", "main.cpp"), '#include <cstdio>\nint value();\nint main() { std::puts("hello from app"); return value() - 3; }\n');
  const app = treeProviders.get("charpente.targets").getChildren()[0];
  await commands.get("charpente.runTarget")!(app);
  await until(() => outputLines.some((l) => l.includes("hello from app")), "the program output");
});

test("explain shows the text of an error code", async () => {
  await commands.get("charpente.explain")!();
  await until(() => outputLines.some((l) => l.includes("CH2001")), "the explanation");
});

test("the quality gate command reports its outcome", async () => {
  await commands.get("charpente.check")!();
  await until(() => messages.some((m) => /quality gate/.test(m.text)), "the gate message", 120000);
});

test("saving a .charpente file reloads the workspace", async () => {
  fs.writeFileSync(path.join(root, "demo.charpente"), WORKSPACE.replace('version="1.0.0"', 'version="1.0.1"'));
  for (const handler of saveHandlers) {
    handler({ fileName: path.join(root, "demo.charpente") });
  }
  await sleep(1500);
  assert.equal(treeProviders.get("charpente.targets").getChildren().length, 2);
});
