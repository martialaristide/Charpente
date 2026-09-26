import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import { ServerClient, ServerError } from "./client";
import {
  BuildTarget,
  TargetItem,
  TaskDefinition,
  buildArguments,
  compileCommandsJson,
  convertDiagnostics,
  debugAdapterArgv,
  errorCodeIn,
  resolveDebugConfiguration,
  statusText,
  targetItems,
  taskArgv,
} from "./model";

let client: ServerClient | undefined;
let output: vscode.OutputChannel;
let status: vscode.StatusBarItem;
let diagnostics: vscode.DiagnosticCollection;
let targetsView: TargetsProvider;
const state = { name: undefined as string | undefined, building: false, ok: undefined as boolean | undefined, error: undefined as string | undefined };

function settings() {
  const cfg = vscode.workspace.getConfiguration("charpente");
  return {
    command: cfg.get<string[]>("command", ["charpente"]),
    configuration: cfg.get<string>("configuration", "Debug"),
    platform: cfg.get<string>("platform", ""),
    buildOnSave: cfg.get<boolean>("buildOnSave", false),
    compileCommands: cfg.get<boolean>("generateCompileCommandsOnLoad", true),
  };
}

function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function refreshStatus(): void {
  status.text = statusText({ ...state, configuration: settings().configuration });
  status.tooltip = state.error ?? "Charpente: click to build";
  status.command = state.error ? "charpente.showOutput" : "charpente.build";
  status.show();
}

class TargetNode extends vscode.TreeItem {
  constructor(readonly item: TargetItem) {
    super(item.label, vscode.TreeItemCollapsibleState.None);
    this.description = item.description;
    this.contextValue = item.contextValue;
    this.tooltip = item.dependencies.length ? `uses ${item.dependencies.join(", ")}` : undefined;
    this.iconPath = new vscode.ThemeIcon(item.contextValue === "runnable" ? "symbol-method" : "package");
  }
}

class TargetsProvider implements vscode.TreeDataProvider<TargetNode> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  items: TargetItem[] = [];

  refresh(items: TargetItem[]): void {
    this.items = items;
    this.changed.fire();
  }

  getTreeItem(node: TargetNode): vscode.TreeItem {
    return node;
  }

  getChildren(): TargetNode[] {
    return this.items.map((i) => new TargetNode(i));
  }
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  const root = workspaceRoot();
  if (!root) {
    return;
  }
  const s = settings();
  const next = new ServerClient(s.command, root);
  client = next;
  next.on("stderr", (text: string) => output.append(text));
  next.on("exit", (code: number | null) => {
    if (client === next && code !== 0) {
      state.error = `The Charpente server stopped (code ${code}).`;
      refreshStatus();
    }
  });
  next.on("notification", (n: { method: string; params: any }) => onNotification(n.method, n.params));
  try {
    await next.start();
    state.error = undefined;
    await loadWorkspace();
  } catch (error) {
    reportFailure("Cannot start Charpente", error);
  }
  context.subscriptions.push({ dispose: () => void next.stop() });
}

function reportFailure(prefix: string, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  state.error = `${prefix}: ${message}`;
  output.appendLine(state.error);
  refreshStatus();
  const code = errorCodeIn(message);
  const actions = code ? ["Explain", "Show output"] : ["Show output"];
  void vscode.window.showErrorMessage(state.error, ...actions).then((choice) => {
    if (choice === "Explain" && code) {
      void explain(code);
    } else if (choice === "Show output") {
      output.show(true);
    }
  });
}

async function loadWorkspace(): Promise<void> {
  const c = client;
  if (!c) {
    return;
  }
  const info = await c.request("charpente/workspace");
  state.name = info.name;
  const targets = (await c.request("workspace/buildTargets")).targets as BuildTarget[];
  targetsView.refresh(targetItems(targets));
  refreshStatus();
  if (settings().compileCommands) {
    await generateCompileCommands(true);
  }
}

function onNotification(method: string, params: any): void {
  switch (method) {
    case "build/logMessage":
      output.appendLine(String(params.message ?? ""));
      break;
    case "build/taskStart":
      state.building = true;
      output.appendLine(`> ${params.message ?? "task"}`);
      refreshStatus();
      break;
    case "build/taskFinish":
      state.building = false;
      state.ok = params.status === 1;
      output.appendLine(state.ok ? "> done" : "> failed");
      refreshStatus();
      break;
    case "build/publishDiagnostics": {
      const uri = vscode.Uri.parse(params.textDocument.uri);
      diagnostics.set(
        uri,
        convertDiagnostics(params.diagnostics).map((d) => {
          const range = new vscode.Range(d.line, d.character, d.line, d.character + 1);
          const severity = {
            error: vscode.DiagnosticSeverity.Error,
            warning: vscode.DiagnosticSeverity.Warning,
            information: vscode.DiagnosticSeverity.Information,
            hint: vscode.DiagnosticSeverity.Hint,
          }[d.severity];
          const item = new vscode.Diagnostic(range, d.message, severity);
          item.source = d.source;
          item.code = d.code;
          return item;
        }),
      );
      break;
    }
    default:
      break;
  }
}

async function call<T>(label: string, method: string, params: unknown): Promise<T | undefined> {
  if (!client?.running) {
    void vscode.window.showWarningMessage("The Charpente server is not running. Use “Charpente: Restart the server”.");
    return undefined;
  }
  output.show(true);
  try {
    return (await client.request<T>(method, params)) as T;
  } catch (error) {
    if (error instanceof ServerError && error.code === -32000) {
      void vscode.window.showInformationMessage("A build is already running.");
    } else {
      reportFailure(label, error);
    }
    return undefined;
  }
}

async function build(names?: string[]): Promise<void> {
  const s = settings();
  const targets = names ?? targetsView.items.map((t) => t.label);
  const uris = targetsView.items.filter((t) => targets.includes(t.label)).map((t) => ({ uri: t.uri }));
  if (!uris.length) {
    void vscode.window.showInformationMessage("There is nothing to build.");
    return;
  }
  await call("Build", "buildTarget/compile", { targets: uris, arguments: buildArguments(s), originId: `vscode-${Date.now()}` });
}

async function pickTarget(node?: TargetNode, runnableOnly = false): Promise<TargetItem | undefined> {
  if (node) {
    return node.item;
  }
  const candidates = targetsView.items.filter((t) => !runnableOnly || t.contextValue === "runnable");
  const picked = await vscode.window.showQuickPick(
    candidates.map((t) => ({ label: t.label, description: t.description, item: t })),
    { placeHolder: runnableOnly ? "Run which target?" : "Build which target?" },
  );
  return picked?.item;
}

async function explain(code?: string): Promise<void> {
  const input = code ?? (await vscode.window.showInputBox({ prompt: "Error code (for example CH2001)", placeHolder: "CH2001" }));
  if (!input || !client?.running) {
    return;
  }
  try {
    const result = await client.request("charpente/explain", { code: input });
    output.appendLine(result.text);
    output.show(true);
  } catch (error) {
    void vscode.window.showWarningMessage(error instanceof Error ? error.message : String(error));
  }
}

async function generateCompileCommands(quiet = false): Promise<void> {
  const root = workspaceRoot();
  if (!root || !client?.running) {
    return;
  }
  try {
    const result = await client.request("charpente/compileCommands", { config: settings().configuration });
    const target = path.join(root, "compile_commands.json");
    const text = compileCommandsJson(result.entries);
    if (!fs.existsSync(target) || fs.readFileSync(target, "utf8") !== text) {
      fs.writeFileSync(target, text, "utf8");
    }
    if (!quiet) {
      void vscode.window.showInformationMessage(`compile_commands.json written (${result.entries.length} files).`);
    }
  } catch (error) {
    if (!quiet) {
      reportFailure("compile_commands.json", error);
    } else {
      output.appendLine(`compile_commands.json not written: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

class CharpenteTaskProvider implements vscode.TaskProvider {
  provideTasks(): vscode.Task[] {
    return (["build", "test", "check"] as const).map((command) => this.make({ type: "charpente", command } as vscode.TaskDefinition & TaskDefinition));
  }

  resolveTask(task: vscode.Task): vscode.Task | undefined {
    const definition = task.definition as vscode.TaskDefinition & TaskDefinition;
    return definition.command ? this.make(definition) : undefined;
  }

  private make(definition: vscode.TaskDefinition & TaskDefinition): vscode.Task {
    const s = settings();
    const [program, ...args] = taskArgv(s.command, definition, s);
    const task = new vscode.Task(
      definition,
      vscode.TaskScope.Workspace,
      `${definition.command}${definition.target ? " " + definition.target : ""}`,
      "charpente",
      new vscode.ProcessExecution(program, args),
      ["$charpente-cpp"],
    );
    if (definition.command === "build") {
      task.group = vscode.TaskGroup.Build;
    } else if (definition.command === "test") {
      task.group = vscode.TaskGroup.Test;
    }
    return task;
  }
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel("Charpente");
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  diagnostics = vscode.languages.createDiagnosticCollection("charpente");
  targetsView = new TargetsProvider();
  context.subscriptions.push(
    output,
    status,
    diagnostics,
    vscode.window.registerTreeDataProvider("charpente.targets", targetsView),
    vscode.tasks.registerTaskProvider("charpente", new CharpenteTaskProvider()),
    vscode.commands.registerCommand("charpente.build", () => build()),
    vscode.commands.registerCommand("charpente.buildTarget", async (node?: TargetNode) => {
      const item = await pickTarget(node);
      if (item) {
        await build([item.label]);
      }
    }),
    vscode.commands.registerCommand("charpente.runTarget", async (node?: TargetNode) => {
      const item = await pickTarget(node, true);
      if (item) {
        const s = settings();
        await call("Run", "buildTarget/run", {
          target: { uri: item.uri },
          arguments: [],
          dataKind: "charpente/run",
          data: { config: s.configuration, platform: s.platform },
          originId: `vscode-${Date.now()}`,
        });
      }
    }),
    vscode.commands.registerCommand("charpente.test", () => call("Test", "buildTarget/test", { targets: [], arguments: buildArguments(settings()) })),
    vscode.commands.registerCommand("charpente.check", async () => {
      const result = await call<any>("Quality gate", "charpente/check", {});
      if (result) {
        for (const finding of result.findings) {
          output.appendLine(`[${finding.check}] ${finding.file ?? ""}${finding.line ? ":" + finding.line : ""} ${finding.message}`);
        }
        void vscode.window.showInformationMessage(result.ok ? "The quality gate passed." : "The quality gate found problems (see the output).");
      }
    }),
    vscode.commands.registerCommand("charpente.reload", async () => {
      if (await call("Reload", "charpente/reload", {})) {
        await loadWorkspace();
      }
    }),
    vscode.commands.registerCommand("charpente.explain", () => explain()),
    vscode.commands.registerCommand("charpente.generateCompileCommands", () => generateCompileCommands()),
    vscode.commands.registerCommand("charpente.showOutput", () => output.show(true)),
    vscode.commands.registerCommand("charpente.restartServer", async () => {
      await client?.stop();
      await startServer(context);
    }),
    vscode.debug.registerDebugAdapterDescriptorFactory("charpente", {
      createDebugAdapterDescriptor: () => {
        const [program, ...args] = debugAdapterArgv(settings().command, workspaceRoot() ?? "");
        return new vscode.DebugAdapterExecutable(program, args);
      },
    }),
    vscode.debug.registerDebugConfigurationProvider("charpente", {
      resolveDebugConfiguration: (_folder, config) => resolveDebugConfiguration(config as Record<string, any>, settings()) as vscode.DebugConfiguration,
    }),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (settings().buildOnSave && /\.(c|cc|cpp|cxx|h|hh|hpp)$/i.test(doc.fileName) && !state.building) {
        void build();
      }
      if (doc.fileName.endsWith(".charpente")) {
        void vscode.commands.executeCommand("charpente.reload");
      }
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("charpente")) {
        refreshStatus();
      }
    }),
  );
  refreshStatus();
  await startServer(context);
}

export async function deactivate(): Promise<void> {
  await client?.stop();
}
