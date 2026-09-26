/** Pure helpers between the server's answers and what the extension shows. No dependency on VS Code: unit-testable. */

export interface BuildTarget {
  id: { uri: string };
  displayName: string;
  tags: string[];
  languageIds: string[];
  dependencies: { uri: string }[];
  capabilities: { canCompile: boolean; canTest: boolean; canRun: boolean; canDebug: boolean };
}

export interface TargetItem {
  uri: string;
  label: string;
  description: string;
  /** Drives the inline buttons in the tree: "runnable" targets get Build and Run, the others only Build. */
  contextValue: "target" | "runnable";
  dependencies: string[];
}

export type Settings = { configuration: string; platform: string };

export function targetItems(targets: BuildTarget[]): TargetItem[] {
  const names = new Map(targets.map((t) => [t.id.uri, t.displayName]));
  return targets
    .map((t) => ({
      uri: t.id.uri,
      label: t.displayName,
      description: [t.tags[0] ?? "", ...(t.tags.slice(1))].filter(Boolean).join(", "),
      contextValue: (t.capabilities.canRun ? "runnable" : "target") as TargetItem["contextValue"],
      dependencies: t.dependencies.map((d) => names.get(d.uri) ?? d.uri),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** The `arguments` BSP requests carry, from the user's settings. */
export function buildArguments(settings: Settings): string[] {
  const args = ["--config", settings.configuration || "Debug"];
  if (settings.platform.trim()) {
    args.push("--platform", settings.platform.trim());
  }
  return args;
}

export type TaskDefinition = { command: "build" | "test" | "check"; target?: string; config?: string };

/** The command line of a Charpente task: `[...charpente.command, "build", ...]`. Never goes through a shell. */
export function taskArgv(command: string[], definition: TaskDefinition, settings: Settings): string[] {
  const config = definition.config || settings.configuration || "Debug";
  const argv = [...command, definition.command];
  if (definition.command === "check") {
    return argv;
  }
  argv.push("--config", config);
  if (settings.platform.trim()) {
    argv.push("--platform", settings.platform.trim());
  }
  if (definition.command === "build" && definition.target) {
    argv.push("--target", definition.target);
  }
  return argv;
}

export type Diagnostic = {
  line: number;
  character: number;
  severity: "error" | "warning" | "information" | "hint";
  message: string;
  code?: string;
  source: string;
};

const SEVERITIES: Diagnostic["severity"][] = ["error", "warning", "information", "hint"];

/** BSP `Diagnostic[]` -> what the extension turns into VS Code diagnostics (severity 1..4 -> name; unknown -> error). */
export function convertDiagnostics(items: any[]): Diagnostic[] {
  return items.map((item) => ({
    line: item?.range?.start?.line ?? 0,
    character: item?.range?.start?.character ?? 0,
    severity: SEVERITIES[(item?.severity ?? 1) - 1] ?? "error",
    message: String(item?.message ?? ""),
    code: item?.code === undefined || item?.code === null ? undefined : String(item.code),
    source: item?.source ?? "charpente",
  }));
}

export function statusText(state: { name?: string; building?: boolean; ok?: boolean; configuration: string; error?: string }): string {
  if (state.error) {
    return "$(error) Charpente";
  }
  if (state.building) {
    return `$(sync~spin) ${state.name ?? "Charpente"} ${state.configuration}`;
  }
  if (state.ok === false) {
    return `$(error) ${state.name ?? "Charpente"} ${state.configuration}`;
  }
  return `$(check) ${state.name ?? "Charpente"} ${state.configuration}`;
}

/** The `compile_commands.json` text for the server's entries (clangd reads it from the workspace root). */
export function compileCommandsJson(entries: unknown[]): string {
  return JSON.stringify(entries, null, 2) + "\n";
}

/** Extracts a `CHnnnn` error code from a message so the UI can offer "Explain". */
export function errorCodeIn(text: string): string | undefined {
  return /\bCH\d{4}\b/.exec(text)?.[0];
}

/** The command that starts the debug adapter: `[...charpente.command, "debug-adapter", "--root", folder]` (never through a shell). */
export function debugAdapterArgv(command: string[], root: string): string[] {
  return [...command, "debug-adapter", "--root", root];
}

/** Fill in what a `charpente` launch configuration leaves out (the debugger picks the target when there is only one program). */
export function resolveDebugConfiguration(config: Record<string, any>, settings: Settings): Record<string, any> {
  const resolved = { ...config };
  resolved.type = "charpente";
  resolved.request = resolved.request || "launch";
  resolved.name = resolved.name || "Charpente: debug the program";
  if (!resolved.program) {
    resolved.config = resolved.config || settings.configuration || "Debug";
    if (settings.platform.trim() && !resolved.platform) {
      resolved.platform = settings.platform.trim();
    }
  }
  return resolved;
}
